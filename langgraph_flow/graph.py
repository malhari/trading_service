"""LangGraph orchestration for trading decisions."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, TypedDict
import operator

from langgraph.graph import StateGraph, END

from core.config import get_config
from core.models import BreakoutSignal, OHLC, Position, Tick
from core.session_manager import get_session_manager
from core.position_tracker import get_order_manager, get_position_tracker
from risk.risk_guard import get_risk_guard, RiskCheckResult
from strategies.breakout_detector import BreakoutDetector, MultiSymbolBreakoutScanner
from strategies.sr_levels import SRLevelCalculator
from llm.llm_router import get_llm_router

logger = logging.getLogger(__name__)


class TradingState(TypedDict):
    """State passed through the trading graph."""
    # Input data
    symbol: str
    tick: Optional[Dict]
    candle: Optional[Dict]
    sr_levels: List[Dict]
    
    # Processing results
    signal: Optional[Dict]
    risk_check: Optional[Dict]
    llm_validation: Optional[Dict]
    
    # Decision
    should_trade: bool
    trade_quantity: int
    
    # Execution result
    order_id: Optional[str]
    error: Optional[str]
    
    # Metadata
    timestamp: str
    messages: Annotated[List[str], operator.add]


def create_initial_state(
    symbol: str,
    tick: Optional[Tick] = None,
    candle: Optional[OHLC] = None,
    sr_levels: Optional[List] = None
) -> TradingState:
    """Create initial state for the graph."""
    return TradingState(
        symbol=symbol,
        tick=tick.__dict__ if tick else None,
        candle=candle.__dict__ if candle else None,
        sr_levels=[l.__dict__ for l in sr_levels] if sr_levels else [],
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


# ==================== Graph Nodes ====================

def check_session_node(state: TradingState) -> TradingState:
    """Check if trading session allows new trades."""
    session = get_session_manager()
    
    if not session.is_trading_allowed():
        phase = session.get_current_phase()
        state["messages"] = [f"Trading not allowed in {phase.value} phase"]
        state["should_trade"] = False
        return state
    
    state["messages"] = ["Session check: Trading allowed"]
    return state


def scan_breakout_node(state: TradingState) -> TradingState:
    """Scan for breakout signals."""
    if not state.get("candle") or not state.get("sr_levels"):
        state["messages"] = ["No candle or SR levels data"]
        return state
    
    config = get_config()
    
    detector = BreakoutDetector(
        volume_surge_multiplier=config.strategy.volume_surge_multiplier,
        min_risk_reward=config.strategy.min_risk_reward,
        sl_buffer_percent=config.risk.sl_buffer_percent
    )
    
    # Reconstruct objects from state
    from core.models import OHLC, SRLevel
    
    candle_data = state["candle"]
    candle = OHLC(
        symbol=candle_data["symbol"],
        timestamp=datetime.fromisoformat(candle_data["timestamp"]) if isinstance(candle_data["timestamp"], str) else candle_data["timestamp"],
        open=candle_data["open"],
        high=candle_data["high"],
        low=candle_data["low"],
        close=candle_data["close"],
        volume=candle_data["volume"]
    )
    
    sr_levels = [
        SRLevel(
            price=l["price"],
            level_type=l["level_type"],
            strength=l.get("strength", 1)
        )
        for l in state["sr_levels"]
    ]
    
    # Set average volume (should be calculated beforehand)
    avg_volume = candle.volume * 0.7  # Placeholder
    detector.set_average_volume(state["symbol"], avg_volume)
    
    signal = detector.scan_for_breakouts(
        symbol=state["symbol"],
        current_candle=candle,
        sr_levels=sr_levels,
        volume=candle.volume
    )
    
    if signal:
        state["signal"] = {
            "symbol": signal.symbol,
            "signal_type": signal.signal_type.value,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "target": signal.target,
            "risk_reward_ratio": signal.risk_reward_ratio,
            "volume_ratio": signal.volume_ratio,
            "confidence": signal.confidence
        }
        state["messages"] = [f"Breakout signal detected: {signal.signal_type.value}"]
    else:
        state["messages"] = ["No breakout signal"]
    
    return state


def risk_check_node(state: TradingState) -> TradingState:
    """Perform risk checks on the signal."""
    if not state.get("signal"):
        state["messages"] = ["No signal to check"]
        return state
    
    risk_guard = get_risk_guard()
    signal_data = state["signal"]
    
    # Reconstruct signal
    from core.models import BreakoutSignal, SignalType, SRLevel
    
    signal = BreakoutSignal(
        symbol=signal_data["symbol"],
        signal_type=SignalType(signal_data["signal_type"]),
        entry_price=signal_data["entry_price"],
        stop_loss=signal_data["stop_loss"],
        target=signal_data["target"],
        sr_level=SRLevel(price=signal_data["entry_price"], level_type="breakout"),
        volume_ratio=signal_data["volume_ratio"],
        timestamp=datetime.now(),
        confidence=signal_data["confidence"]
    )
    
    # Get current positions
    position_tracker = get_position_tracker()
    positions = {p.symbol: p for p in position_tracker.get_all_positions()}
    
    result = risk_guard.check_trade_allowed(signal, positions)
    
    state["risk_check"] = {
        "allowed": result.allowed,
        "reason": result.reason,
        "suggested_quantity": result.suggested_quantity
    }
    
    if result.allowed:
        state["trade_quantity"] = result.suggested_quantity
        state["messages"] = [f"Risk check passed: qty={result.suggested_quantity}"]
    else:
        state["should_trade"] = False
        state["messages"] = [f"Risk check failed: {result.reason}"]
    
    return state


def llm_validation_node(state: TradingState) -> TradingState:
    """Optional LLM validation of the trade."""
    config = get_config()
    
    if not config.llm.enabled or not config.llm.validate_all_trades:
        state["llm_validation"] = {"skipped": True}
        state["messages"] = ["LLM validation skipped"]
        return state
    
    if not state.get("signal") or not state.get("risk_check", {}).get("allowed"):
        return state
    
    llm_router = get_llm_router()
    signal_data = state["signal"]
    
    prompt = f"""
    Analyze this breakout trade signal:
    
    Symbol: {signal_data['symbol']}
    Signal Type: {signal_data['signal_type']}
    Entry Price: {signal_data['entry_price']}
    Stop Loss: {signal_data['stop_loss']}
    Target: {signal_data['target']}
    Risk-Reward: {signal_data['risk_reward_ratio']:.2f}
    Volume Ratio: {signal_data['volume_ratio']:.2f}
    Confidence: {signal_data['confidence']:.2f}
    
    Should this trade be taken? Consider:
    1. Is the risk-reward acceptable?
    2. Is the volume confirmation strong?
    3. Any concerns with the setup?
    
    Respond with JSON: {{"allow_trade": true/false, "reason": "explanation"}}
    """
    
    result = llm_router.run(prompt)
    
    state["llm_validation"] = result
    
    if not result.get("allow_trade", True):
        state["should_trade"] = False
        state["messages"] = [f"LLM rejected: {result.get('reason', 'No reason')}"]
    else:
        state["messages"] = ["LLM approved trade"]
    
    return state


def execute_trade_node(state: TradingState) -> TradingState:
    """Execute the trade if all checks passed."""
    if not state.get("should_trade", True):
        state["messages"] = ["Trade execution skipped"]
        return state
    
    if not state.get("signal") or state.get("trade_quantity", 0) == 0:
        state["messages"] = ["No valid signal or quantity"]
        return state
    
    risk_check = state.get("risk_check", {})
    if not risk_check.get("allowed"):
        state["messages"] = ["Risk check did not pass"]
        return state
    
    signal_data = state["signal"]
    quantity = state["trade_quantity"]
    
    # Reconstruct signal for order placement
    from core.models import BreakoutSignal, SignalType, SRLevel
    
    signal = BreakoutSignal(
        symbol=signal_data["symbol"],
        signal_type=SignalType(signal_data["signal_type"]),
        entry_price=signal_data["entry_price"],
        stop_loss=signal_data["stop_loss"],
        target=signal_data["target"],
        sr_level=SRLevel(price=signal_data["entry_price"], level_type="breakout"),
        volume_ratio=signal_data["volume_ratio"],
        timestamp=datetime.now(),
        confidence=signal_data["confidence"]
    )
    
    order_manager = get_order_manager()
    position_tracker = get_position_tracker()
    risk_guard = get_risk_guard()
    
    try:
        # Place entry order
        order_id = order_manager.place_entry_order(signal, quantity)
        
        if order_id:
            # Open position (assuming market order fills immediately)
            position = position_tracker.open_position(
                signal=signal,
                quantity=quantity,
                entry_order_id=order_id,
                entry_price=signal.entry_price
            )
            
            # Update risk guard
            risk_guard.add_position(position)
            
            state["order_id"] = order_id
            state["should_trade"] = True
            state["messages"] = [f"Trade executed: Order {order_id}"]
            
            logger.info(
                f"Trade executed: {signal.symbol} | {signal.signal_type.value} | "
                f"qty={quantity} @ {signal.entry_price}"
            )
        else:
            state["error"] = "Order placement failed"
            state["messages"] = ["Order placement failed"]
            
    except Exception as e:
        state["error"] = str(e)
        state["messages"] = [f"Execution error: {e}"]
        logger.error(f"Trade execution error: {e}")
    
    return state


# ==================== Routing Functions ====================

def should_continue_after_session(state: TradingState) -> str:
    """Route after session check."""
    if "Trading not allowed" in str(state.get("messages", [])):
        return END
    return "scan_breakout"


def should_continue_after_scan(state: TradingState) -> str:
    """Route after breakout scan."""
    if state.get("signal"):
        return "risk_check"
    return END


def should_continue_after_risk(state: TradingState) -> str:
    """Route after risk check."""
    if state.get("risk_check", {}).get("allowed"):
        return "llm_validation"
    return END


def should_continue_after_llm(state: TradingState) -> str:
    """Route after LLM validation."""
    llm_result = state.get("llm_validation", {})
    if llm_result.get("skipped") or llm_result.get("allow_trade", True):
        return "execute_trade"
    return END


# ==================== Graph Builder ====================

def build_trading_graph() -> StateGraph:
    """Build the trading decision graph."""
    
    # Create graph
    graph = StateGraph(TradingState)
    
    # Add nodes
    graph.add_node("check_session", check_session_node)
    graph.add_node("scan_breakout", scan_breakout_node)
    graph.add_node("risk_check", risk_check_node)
    graph.add_node("llm_validation", llm_validation_node)
    graph.add_node("execute_trade", execute_trade_node)
    
    # Set entry point
    graph.set_entry_point("check_session")
    
    # Add conditional edges
    graph.add_conditional_edges(
        "check_session",
        should_continue_after_session,
        {
            "scan_breakout": "scan_breakout",
            END: END
        }
    )
    
    graph.add_conditional_edges(
        "scan_breakout",
        should_continue_after_scan,
        {
            "risk_check": "risk_check",
            END: END
        }
    )
    
    graph.add_conditional_edges(
        "risk_check",
        should_continue_after_risk,
        {
            "llm_validation": "llm_validation",
            END: END
        }
    )
    
    graph.add_conditional_edges(
        "llm_validation",
        should_continue_after_llm,
        {
            "execute_trade": "execute_trade",
            END: END
        }
    )
    
    # Execute trade is terminal
    graph.add_edge("execute_trade", END)
    
    return graph.compile()


# ==================== Trading Engine ====================

class TradingEngine:
    """Main trading engine using LangGraph."""
    
    def __init__(self):
        self.graph = build_trading_graph()
        self.sr_calculator = SRLevelCalculator(
            lookback_days=get_config().strategy.sr_lookback_days,
            pivot_type=get_config().strategy.pivot_type
        )
        self._sr_levels_cache: Dict[str, List] = {}
    
    def update_sr_levels(self, symbol: str, daily_df, intraday_df=None):
        """Update SR levels for a symbol."""
        levels = self.sr_calculator.calculate_all_levels(
            daily_df=daily_df,
            intraday_df=intraday_df,
            orb_minutes=get_config().intraday.opening_range_minutes
        )
        self._sr_levels_cache[symbol] = levels.get("all", [])
        logger.info(f"Updated {len(self._sr_levels_cache[symbol])} SR levels for {symbol}")
    
    def process_candle(self, symbol: str, candle: OHLC) -> Dict[str, Any]:
        """
        Process a completed candle through the trading graph.
        
        Args:
            symbol: Trading symbol.
            candle: Completed OHLC candle.
        
        Returns:
            Final state dict with decision and results.
        """
        sr_levels = self._sr_levels_cache.get(symbol, [])
        
        initial_state = create_initial_state(
            symbol=symbol,
            candle=candle,
            sr_levels=sr_levels
        )
        
        # Run graph
        result = self.graph.invoke(initial_state)
        
        logger.debug(f"Graph result for {symbol}: {result.get('messages', [])}")
        
        return result
    
    def process_tick(self, tick: Tick) -> Optional[Dict[str, Any]]:
        """
        Process a real-time tick (for monitoring, not trading decisions).
        
        Args:
            tick: Real-time tick data.
        
        Returns:
            Update info if any action needed.
        """
        # Update position prices
        position_tracker = get_position_tracker()
        position_tracker.update_price(tick.symbol, tick.last_price)
        
        # Check if SL should move to breakeven
        risk_guard = get_risk_guard()
        position = risk_guard.get_position(tick.symbol)
        
        if position and risk_guard.should_move_sl_to_breakeven(position):
            position_tracker.move_sl_to_breakeven(tick.symbol)
            return {"action": "sl_moved_to_breakeven", "symbol": tick.symbol}
        
        return None


# Singleton
_trading_engine: Optional[TradingEngine] = None


def get_trading_engine() -> TradingEngine:
    """Get singleton trading engine."""
    global _trading_engine
    if _trading_engine is None:
        _trading_engine = TradingEngine()
    return _trading_engine
