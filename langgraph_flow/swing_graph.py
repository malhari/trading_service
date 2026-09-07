"""LangGraph orchestration for swing trading decisions."""

import logging
from datetime import datetime, date
from typing import Annotated, Any, Dict, List, Optional, TypedDict
import operator

from langgraph.graph import StateGraph, END

from core.config import get_config, TradingStyle
from core.swing_tracker import get_swing_order_manager, get_swing_position_tracker
from risk.swing_risk import get_swing_risk_guard, SwingRiskCheckResult
from strategies.swing_levels import SwingLevelCalculator, TrendDirection
from strategies.swing_breakout import SwingBreakoutDetector, SwingScanner, SwingSignal

logger = logging.getLogger(__name__)


class SwingTradingState(TypedDict):
    """State for swing trading graph."""
    # Input
    symbol: str
    daily_data: Optional[Dict]  # Daily OHLC as dict
    
    # Analysis results
    trend: Optional[Dict]
    sr_levels: List[Dict]
    consolidations: List[Dict]
    
    # Signal
    signal: Optional[Dict]
    
    # Risk check
    risk_check: Optional[Dict]
    
    # LLM validation
    llm_validation: Optional[Dict]
    
    # Execution
    should_trade: bool
    trade_quantity: int
    order_id: Optional[str]
    
    # Metadata
    error: Optional[str]
    timestamp: str
    messages: Annotated[List[str], operator.add]


def create_swing_initial_state(symbol: str, daily_data: Dict) -> SwingTradingState:
    """Create initial state for swing graph."""
    return SwingTradingState(
        symbol=symbol,
        daily_data=daily_data,
        trend=None,
        sr_levels=[],
        consolidations=[],
        signal=None,
        risk_check=None,
        llm_validation=None,
        should_trade=False,
        trade_quantity=0,
        order_id=None,
        error=None,
        timestamp=datetime.now().isoformat(),
        messages=[]
    )


# ==================== Swing Graph Nodes ====================

def analyze_trend_node(state: SwingTradingState) -> SwingTradingState:
    """Analyze trend using EMAs and price structure."""
    import pandas as pd
    
    daily_data = state.get("daily_data")
    if not daily_data:
        state["messages"] = ["No daily data provided"]
        return state
    
    # Convert dict to DataFrame
    df = pd.DataFrame(daily_data)
    
    config = get_config()
    calculator = SwingLevelCalculator(
        lookback_days=config.swing_strategy.sr_lookback_days,
        pivot_type=config.swing_strategy.pivot_type,
        ema_short=config.swing_strategy.trend_ema_short,
        ema_long=config.swing_strategy.trend_ema_long
    )
    
    trend = calculator.analyze_trend(df)
    
    state["trend"] = {
        "direction": trend.direction,
        "strength": trend.strength,
        "ema_short": trend.ema_short,
        "ema_long": trend.ema_long,
        "price_vs_ema": trend.price_vs_ema,
        "atr": trend.atr,
        "atr_percent": trend.atr_percent
    }
    
    state["messages"] = [f"Trend: {trend.direction} (strength: {trend.strength:.2f})"]
    
    return state


def calculate_levels_node(state: SwingTradingState) -> SwingTradingState:
    """Calculate S/R levels for swing trading."""
    import pandas as pd
    
    daily_data = state.get("daily_data")
    if not daily_data:
        return state
    
    df = pd.DataFrame(daily_data)
    config = get_config()
    
    calculator = SwingLevelCalculator(
        lookback_days=config.swing_strategy.sr_lookback_days,
        pivot_type=config.swing_strategy.pivot_type
    )
    
    levels = calculator.calculate_all_swing_levels(df, include_weekly=True)
    
    # Find consolidation zones
    consolidations = calculator.find_consolidation_zones(
        df, 
        min_days=config.swing_strategy.consolidation_min_days
    )
    
    state["sr_levels"] = [
        {"price": l.price, "level_type": l.level_type, "strength": l.strength}
        for l in levels["all"]
    ]
    
    state["consolidations"] = [
        {
            "high": c.high,
            "low": c.low,
            "days": c.days,
            "range_percent": c.range_percent
        }
        for c in consolidations[-3:]  # Last 3
    ]
    
    state["messages"] = [f"Calculated {len(levels['all'])} S/R levels"]
    
    return state


def detect_signal_node(state: SwingTradingState) -> SwingTradingState:
    """Detect swing breakout signal."""
    import pandas as pd
    from core.models import SRLevel
    from strategies.swing_levels import TrendAnalysis, ConsolidationZone
    
    daily_data = state.get("daily_data")
    trend_data = state.get("trend")
    sr_levels_data = state.get("sr_levels", [])
    consolidations_data = state.get("consolidations", [])
    
    if not daily_data or not trend_data:
        state["messages"] = ["Missing data for signal detection"]
        return state
    
    df = pd.DataFrame(daily_data)
    config = get_config()
    
    # Reconstruct objects
    trend = TrendAnalysis(
        direction=trend_data["direction"],
        strength=trend_data["strength"],
        ema_short=trend_data["ema_short"],
        ema_long=trend_data["ema_long"],
        price_vs_ema=trend_data["price_vs_ema"],
        higher_highs=0,
        higher_lows=0,
        lower_highs=0,
        lower_lows=0,
        atr=trend_data["atr"],
        atr_percent=trend_data["atr_percent"]
    )
    
    sr_levels = [
        SRLevel(price=l["price"], level_type=l["level_type"], strength=l["strength"])
        for l in sr_levels_data
    ]
    
    consolidation = None
    if consolidations_data:
        c = consolidations_data[-1]
        consolidation = ConsolidationZone(
            high=c["high"],
            low=c["low"],
            start_date=datetime.now(),
            end_date=datetime.now(),
            days=c["days"],
            range_percent=c["range_percent"]
        )
    
    detector = SwingBreakoutDetector(
        volume_surge_multiplier=config.swing_strategy.volume_surge_multiplier,
        min_risk_reward=config.swing_strategy.min_risk_reward,
        atr_multiplier_sl=config.swing_strategy.atr_multiplier_sl,
        consolidation_min_days=config.swing_strategy.consolidation_min_days
    )
    
    # Set average volume
    avg_vol = df["volume"].tail(20).mean()
    detector.set_average_volume(state["symbol"], avg_vol)
    
    signal = detector.detect_breakout(
        symbol=state["symbol"],
        df=df,
        sr_levels=sr_levels,
        trend=trend,
        consolidation=consolidation
    )
    
    if signal:
        state["signal"] = {
            "symbol": signal.symbol,
            "signal_type": signal.signal_type,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "target_1": signal.target_1,
            "target_2": signal.target_2,
            "target_3": signal.target_3,
            "risk_reward_1": signal.risk_reward_1,
            "volume_ratio": signal.volume_ratio,
            "confidence": signal.confidence,
            "holding_days_estimate": signal.holding_days_estimate,
            "consolidation_days": signal.consolidation_days
        }
        state["messages"] = [f"Signal detected: {signal.signal_type} (confidence: {signal.confidence:.2f})"]
    else:
        state["messages"] = ["No swing signal detected"]
    
    return state


def swing_risk_check_node(state: SwingTradingState) -> SwingTradingState:
    """Perform swing-specific risk checks."""
    signal_data = state.get("signal")
    
    if not signal_data:
        state["messages"] = ["No signal to check"]
        return state
    
    # Reconstruct signal for risk check
    from strategies.swing_breakout import SwingSignal
    from strategies.swing_levels import TrendAnalysis
    from core.models import SRLevel
    
    trend_data = state.get("trend", {})
    trend = TrendAnalysis(
        direction=trend_data.get("direction", "sideways"),
        strength=trend_data.get("strength", 0),
        ema_short=trend_data.get("ema_short", 0),
        ema_long=trend_data.get("ema_long", 0),
        price_vs_ema=trend_data.get("price_vs_ema", "at"),
        higher_highs=0, higher_lows=0, lower_highs=0, lower_lows=0,
        atr=trend_data.get("atr", 0),
        atr_percent=trend_data.get("atr_percent", 0)
    )
    
    signal = SwingSignal(
        symbol=signal_data["symbol"],
        signal_type=signal_data["signal_type"],
        entry_price=signal_data["entry_price"],
        stop_loss=signal_data["stop_loss"],
        target_1=signal_data["target_1"],
        target_2=signal_data["target_2"],
        target_3=signal_data["target_3"],
        sr_level=SRLevel(price=signal_data["entry_price"], level_type="breakout"),
        trend=trend,
        volume_ratio=signal_data["volume_ratio"],
        atr=trend.atr,
        consolidation_days=signal_data["consolidation_days"],
        timestamp=datetime.now(),
        confidence=signal_data["confidence"],
        holding_days_estimate=signal_data["holding_days_estimate"]
    )
    
    risk_guard = get_swing_risk_guard()
    result = risk_guard.check_trade_allowed(signal)
    
    state["risk_check"] = {
        "allowed": result.allowed,
        "reason": result.reason,
        "suggested_quantity": result.suggested_quantity,
        "position_value": result.position_value,
        "portfolio_risk": result.portfolio_risk,
        "sector_exposure": result.sector_exposure
    }
    
    if result.allowed:
        state["trade_quantity"] = result.suggested_quantity
        state["messages"] = [f"Risk check passed: qty={result.suggested_quantity}"]
    else:
        state["should_trade"] = False
        state["messages"] = [f"Risk check failed: {result.reason}"]
    
    return state


def swing_llm_validation_node(state: SwingTradingState) -> SwingTradingState:
    """Optional LLM validation for swing trades."""
    config = get_config()
    
    if not config.llm.enabled:
        state["llm_validation"] = {"skipped": True}
        state["messages"] = ["LLM validation skipped"]
        return state
    
    signal = state.get("signal")
    risk_check = state.get("risk_check", {})
    
    if not signal or not risk_check.get("allowed"):
        return state
    
    from llm.llm_router import get_llm_router
    
    llm = get_llm_router()
    result = llm.validate_trade_setup(
        symbol=signal["symbol"],
        signal_type=signal["signal_type"],
        entry=signal["entry_price"],
        sl=signal["stop_loss"],
        target=signal["target_1"],
        volume_ratio=signal["volume_ratio"]
    )
    
    state["llm_validation"] = result
    
    if not result.get("allow_trade", True):
        state["should_trade"] = False
        state["messages"] = [f"LLM rejected: {result.get('reason', 'No reason')}"]
    else:
        state["messages"] = ["LLM approved swing trade"]
    
    return state


def execute_swing_trade_node(state: SwingTradingState) -> SwingTradingState:
    """Execute swing trade."""
    if not state.get("should_trade", True):
        state["messages"] = ["Trade execution skipped"]
        return state
    
    signal_data = state.get("signal")
    risk_check = state.get("risk_check", {})
    
    if not signal_data or not risk_check.get("allowed"):
        state["messages"] = ["Cannot execute - missing signal or risk approval"]
        return state
    
    quantity = state.get("trade_quantity", 0)
    if quantity == 0:
        state["messages"] = ["Cannot execute - quantity is 0"]
        return state
    
    # Reconstruct signal
    from strategies.swing_breakout import SwingSignal
    from strategies.swing_levels import TrendAnalysis
    from core.models import SRLevel
    
    trend_data = state.get("trend", {})
    trend = TrendAnalysis(
        direction=trend_data.get("direction", "sideways"),
        strength=trend_data.get("strength", 0),
        ema_short=trend_data.get("ema_short", 0),
        ema_long=trend_data.get("ema_long", 0),
        price_vs_ema=trend_data.get("price_vs_ema", "at"),
        higher_highs=0, higher_lows=0, lower_highs=0, lower_lows=0,
        atr=trend_data.get("atr", 0),
        atr_percent=trend_data.get("atr_percent", 0)
    )
    
    signal = SwingSignal(
        symbol=signal_data["symbol"],
        signal_type=signal_data["signal_type"],
        entry_price=signal_data["entry_price"],
        stop_loss=signal_data["stop_loss"],
        target_1=signal_data["target_1"],
        target_2=signal_data["target_2"],
        target_3=signal_data["target_3"],
        sr_level=SRLevel(price=signal_data["entry_price"], level_type="breakout"),
        trend=trend,
        volume_ratio=signal_data["volume_ratio"],
        atr=trend.atr,
        consolidation_days=signal_data["consolidation_days"],
        timestamp=datetime.now(),
        confidence=signal_data["confidence"],
        holding_days_estimate=signal_data["holding_days_estimate"]
    )
    
    order_manager = get_swing_order_manager()
    position_tracker = get_swing_position_tracker()
    
    try:
        # Place entry order
        order_id = order_manager.place_entry_order(signal, quantity)
        
        if order_id:
            # Open position
            position = position_tracker.open_position(
                signal=signal,
                quantity=quantity,
                entry_order_id=order_id,
                entry_price=signal.entry_price
            )
            
            state["order_id"] = order_id
            state["should_trade"] = True
            state["messages"] = [
                f"Swing trade executed: {order_id}",
                f"Position: {signal.symbol} qty={quantity} @ {signal.entry_price}",
                f"Est. holding: {signal.holding_days_estimate} days"
            ]
            
            logger.info(
                f"Swing trade: {signal.symbol} | {signal.signal_type} | "
                f"qty={quantity} @ {signal.entry_price}"
            )
        else:
            state["error"] = "Order placement failed"
            state["messages"] = ["Order placement failed"]
            
    except Exception as e:
        state["error"] = str(e)
        state["messages"] = [f"Execution error: {e}"]
        logger.error(f"Swing execution error: {e}")
    
    return state


# ==================== Routing ====================

def should_continue_after_trend(state: SwingTradingState) -> str:
    """Route after trend analysis."""
    trend = state.get("trend", {})
    
    # Skip if trend is too weak (for trend-following strategies)
    if trend.get("strength", 0) < 0.3 and trend.get("direction") == "sideways":
        # Still continue - might be consolidation breakout
        pass
    
    return "calculate_levels"


def should_continue_after_signal(state: SwingTradingState) -> str:
    """Route after signal detection."""
    if state.get("signal"):
        return "risk_check"
    return END


def should_continue_after_risk(state: SwingTradingState) -> str:
    """Route after risk check."""
    if state.get("risk_check", {}).get("allowed"):
        return "llm_validation"
    return END


def should_continue_after_llm(state: SwingTradingState) -> str:
    """Route after LLM validation."""
    llm = state.get("llm_validation", {})
    if llm.get("skipped") or llm.get("allow_trade", True):
        return "execute"
    return END


# ==================== Graph Builder ====================

def build_swing_trading_graph() -> StateGraph:
    """Build the swing trading decision graph."""
    
    graph = StateGraph(SwingTradingState)
    
    # Add nodes
    graph.add_node("analyze_trend", analyze_trend_node)
    graph.add_node("calculate_levels", calculate_levels_node)
    graph.add_node("detect_signal", detect_signal_node)
    graph.add_node("risk_check", swing_risk_check_node)
    graph.add_node("llm_validation", swing_llm_validation_node)
    graph.add_node("execute", execute_swing_trade_node)
    
    # Entry
    graph.set_entry_point("analyze_trend")
    
    # Edges
    graph.add_conditional_edges(
        "analyze_trend",
        should_continue_after_trend,
        {"calculate_levels": "calculate_levels"}
    )
    
    graph.add_edge("calculate_levels", "detect_signal")
    
    graph.add_conditional_edges(
        "detect_signal",
        should_continue_after_signal,
        {"risk_check": "risk_check", END: END}
    )
    
    graph.add_conditional_edges(
        "risk_check",
        should_continue_after_risk,
        {"llm_validation": "llm_validation", END: END}
    )
    
    graph.add_conditional_edges(
        "llm_validation",
        should_continue_after_llm,
        {"execute": "execute", END: END}
    )
    
    graph.add_edge("execute", END)
    
    return graph.compile()


# ==================== Swing Trading Engine ====================

class SwingTradingEngine:
    """Main swing trading engine."""
    
    def __init__(self):
        self.graph = build_swing_trading_graph()
        self.scanner = None
        self._initialized = False
    
    def initialize(self):
        """Initialize the engine."""
        config = get_config()
        
        level_calculator = SwingLevelCalculator(
            lookback_days=config.swing_strategy.sr_lookback_days,
            pivot_type=config.swing_strategy.pivot_type,
            ema_short=config.swing_strategy.trend_ema_short,
            ema_long=config.swing_strategy.trend_ema_long
        )
        
        detector = SwingBreakoutDetector(
            volume_surge_multiplier=config.swing_strategy.volume_surge_multiplier,
            min_risk_reward=config.swing_strategy.min_risk_reward,
            atr_multiplier_sl=config.swing_strategy.atr_multiplier_sl,
            consolidation_min_days=config.swing_strategy.consolidation_min_days
        )
        
        self.scanner = SwingScanner(level_calculator, detector)
        self._initialized = True
        
        logger.info("Swing trading engine initialized")
    
    def process_symbol(self, symbol: str, daily_df) -> Dict[str, Any]:
        """
        Process a symbol through the swing trading graph.
        
        Args:
            symbol: Trading symbol.
            daily_df: Daily OHLC DataFrame.
        
        Returns:
            Result dict with analysis and execution.
        """
        if not self._initialized:
            self.initialize()
        
        # Convert DataFrame to dict for state
        daily_data = daily_df.to_dict('list')
        
        initial_state = create_swing_initial_state(symbol, daily_data)
        
        result = self.graph.invoke(initial_state)
        
        logger.debug(f"Swing graph result for {symbol}: {result.get('messages', [])}")
        
        return result
    
    def scan_watchlist(self, symbol_data: Dict) -> List[SwingSignal]:
        """
        Scan entire watchlist for swing signals.
        
        Args:
            symbol_data: Dict of symbol -> daily DataFrame.
        
        Returns:
            List of swing signals sorted by confidence.
        """
        if not self._initialized:
            self.initialize()
        
        return self.scanner.scan_all(symbol_data)
    
    def get_watchlist_summary(self, symbol_data: Dict) -> List[Dict]:
        """Get analysis summary for watchlist."""
        if not self._initialized:
            self.initialize()
        
        return self.scanner.get_watchlist_summary(symbol_data)


# Singleton
_swing_engine: Optional[SwingTradingEngine] = None


def get_swing_trading_engine() -> SwingTradingEngine:
    """Get singleton swing trading engine."""
    global _swing_engine
    if _swing_engine is None:
        _swing_engine = SwingTradingEngine()
    return _swing_engine
