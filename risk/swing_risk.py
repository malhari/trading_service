"""Swing trading risk management with multi-day position handling."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

from core.config import get_config, SwingRiskConfig, TradingStyle
from core.models import DailyStats, OrderSide, Position, TradeResult
from strategies.swing_breakout import SwingSignal

logger = logging.getLogger(__name__)


@dataclass
class SwingRiskCheckResult:
    """Result of swing trade risk check."""
    allowed: bool
    reason: str
    suggested_quantity: int = 0
    position_value: float = 0.0
    portfolio_risk: float = 0.0
    sector_exposure: float = 0.0


@dataclass
class SwingPosition:
    """Extended position for swing trading."""
    symbol: str
    side: OrderSide
    quantity: int
    entry_price: float
    current_price: float
    stop_loss: float
    target_1: float
    target_2: float
    target_3: float
    entry_date: date
    entry_order_id: str
    sector: str = "unknown"
    sl_order_id: Optional[str] = None
    partial_exits: int = 0  # Track partial profit booking
    highest_price: float = 0.0  # For trailing SL
    lowest_price: float = 0.0
    is_trailing_sl_active: bool = False
    notes: str = ""
    
    @property
    def holding_days(self) -> int:
        return (date.today() - self.entry_date).days
    
    @property
    def pnl(self) -> float:
        if self.side == OrderSide.BUY:
            return (self.current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.current_price) * self.quantity
    
    @property
    def pnl_percent(self) -> float:
        if self.entry_price > 0:
            return (self.pnl / (self.entry_price * self.quantity)) * 100
        return 0.0
    
    @property
    def position_value(self) -> float:
        return self.current_price * self.quantity
    
    @property
    def risk_amount(self) -> float:
        return abs(self.entry_price - self.stop_loss) * self.quantity


@dataclass
class WeeklyRiskState:
    """Weekly risk tracking for swing trading."""
    week_start: date
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    peak_equity: float = 0.0
    max_drawdown: float = 0.0
    trades_opened: int = 0
    trades_closed: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    is_circuit_breaker_triggered: bool = False
    circuit_breaker_reason: str = ""


# Sector mapping for Indian stocks
SECTOR_MAP = {
    # Banking & Finance
    "HDFCBANK": "banking", "ICICIBANK": "banking", "KOTAKBANK": "banking",
    "SBIN": "banking", "AXISBANK": "banking", "BAJFINANCE": "finance",
    "BAJAJFINSV": "finance", "HDFC": "finance",
    
    # IT
    "TCS": "it", "INFY": "it", "WIPRO": "it", "HCLTECH": "it",
    "TECHM": "it", "LTIM": "it",
    
    # Oil & Gas
    "RELIANCE": "oil_gas", "ONGC": "oil_gas", "BPCL": "oil_gas",
    "IOC": "oil_gas", "GAIL": "oil_gas",
    
    # Metals
    "TATASTEEL": "metals", "JSWSTEEL": "metals", "HINDALCO": "metals",
    "COALINDIA": "metals", "VEDL": "metals",
    
    # Auto
    "MARUTI": "auto", "TATAMOTORS": "auto", "M&M": "auto",
    "BAJAJ-AUTO": "auto", "HEROMOTOCO": "auto", "EICHERMOT": "auto",
    
    # FMCG
    "HINDUNILVR": "fmcg", "ITC": "fmcg", "NESTLEIND": "fmcg",
    "BRITANNIA": "fmcg", "DABUR": "fmcg",
    
    # Pharma
    "SUNPHARMA": "pharma", "DRREDDY": "pharma", "CIPLA": "pharma",
    "DIVISLAB": "pharma", "APOLLOHOSP": "pharma",
    
    # Telecom
    "BHARTIARTL": "telecom",
    
    # Power
    "NTPC": "power", "POWERGRID": "power", "TATAPOWER": "power",
    "ADANIGREEN": "power",
    
    # Infrastructure
    "LT": "infra", "ADANIPORTS": "infra", "ULTRACEMCO": "infra",
    
    # Consumer
    "TITAN": "consumer", "ASIANPAINT": "consumer", "PIDILITIND": "consumer",
}


class SwingRiskGuard:
    """Risk management for swing trading."""
    
    def __init__(self, capital: Optional[float] = None):
        self.config = get_config()
        self.risk_config: SwingRiskConfig = self.config.swing_risk
        
        self._capital = capital or self.config.capital
        self._weekly_state = self._init_weekly_state()
        self._positions: Dict[str, SwingPosition] = {}
        self._trade_history: List[TradeResult] = []
    
    def _init_weekly_state(self) -> WeeklyRiskState:
        """Initialize weekly state."""
        today = date.today()
        # Get Monday of current week
        week_start = today - timedelta(days=today.weekday())
        return WeeklyRiskState(week_start=week_start)
    
    @property
    def capital(self) -> float:
        return self._capital
    
    @capital.setter
    def capital(self, value: float):
        self._capital = value
    
    def check_and_reset_weekly(self):
        """Check if we need to reset weekly state."""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        
        if self._weekly_state.week_start != week_start:
            logger.info("New week - resetting weekly risk state")
            self._weekly_state = self._init_weekly_state()
    
    def get_sector(self, symbol: str) -> str:
        """Get sector for a symbol."""
        return SECTOR_MAP.get(symbol, "unknown")
    
    def get_sector_exposure(self, sector: str) -> float:
        """Calculate current exposure to a sector."""
        sector_value = sum(
            p.position_value for p in self._positions.values()
            if p.sector == sector
        )
        return sector_value / self._capital if self._capital > 0 else 0
    
    def check_trade_allowed(
        self,
        signal: SwingSignal
    ) -> SwingRiskCheckResult:
        """
        Check if a swing trade is allowed.
        
        Args:
            signal: Swing trading signal.
        
        Returns:
            SwingRiskCheckResult with decision.
        """
        self.check_and_reset_weekly()
        
        # Check circuit breaker
        if self._weekly_state.is_circuit_breaker_triggered:
            return SwingRiskCheckResult(
                allowed=False,
                reason=f"Weekly circuit breaker: {self._weekly_state.circuit_breaker_reason}"
            )
        
        # Check max positions
        if len(self._positions) >= self.risk_config.max_positions:
            return SwingRiskCheckResult(
                allowed=False,
                reason=f"Max positions ({self.risk_config.max_positions}) reached"
            )
        
        # Check if already in position
        if signal.symbol in self._positions:
            return SwingRiskCheckResult(
                allowed=False,
                reason=f"Already have position in {signal.symbol}"
            )
        
        # Check weekly loss limit
        total_pnl = self._weekly_state.realized_pnl + self._weekly_state.unrealized_pnl
        max_loss = self._capital * self.risk_config.max_weekly_loss
        
        if total_pnl <= -max_loss:
            self._trigger_circuit_breaker("Weekly loss limit reached")
            return SwingRiskCheckResult(
                allowed=False,
                reason=f"Weekly loss limit ({self.risk_config.max_weekly_loss*100:.1f}%) reached"
            )
        
        # Check sector exposure
        sector = self.get_sector(signal.symbol)
        current_sector_exposure = self.get_sector_exposure(sector)
        
        # Calculate new position value
        quantity = self.calculate_position_size(
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss
        )
        
        if quantity == 0:
            return SwingRiskCheckResult(
                allowed=False,
                reason="Calculated quantity is 0"
            )
        
        new_position_value = signal.entry_price * quantity
        new_sector_exposure = (
            current_sector_exposure + 
            (new_position_value / self._capital)
        )
        
        if new_sector_exposure > self.risk_config.max_sector_exposure:
            return SwingRiskCheckResult(
                allowed=False,
                reason=f"Sector exposure ({sector}) would exceed {self.risk_config.max_sector_exposure*100:.0f}%"
            )
        
        # Calculate portfolio risk
        current_risk = sum(p.risk_amount for p in self._positions.values())
        new_risk = abs(signal.entry_price - signal.stop_loss) * quantity
        total_risk = current_risk + new_risk
        portfolio_risk_percent = total_risk / self._capital
        
        # All checks passed
        return SwingRiskCheckResult(
            allowed=True,
            reason="All checks passed",
            suggested_quantity=quantity,
            position_value=new_position_value,
            portfolio_risk=portfolio_risk_percent,
            sector_exposure=new_sector_exposure
        )
    
    def _trigger_circuit_breaker(self, reason: str):
        """Trigger weekly circuit breaker."""
        self._weekly_state.is_circuit_breaker_triggered = True
        self._weekly_state.circuit_breaker_reason = reason
        logger.warning(f"WEEKLY CIRCUIT BREAKER: {reason}")
    
    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        override_risk_percent: Optional[float] = None
    ) -> int:
        """
        Calculate position size based on risk per trade.
        
        Args:
            entry_price: Entry price.
            stop_loss: Stop loss price.
            override_risk_percent: Override configured risk.
        
        Returns:
            Number of shares.
        """
        risk_percent = override_risk_percent or self.risk_config.risk_per_trade
        risk_amount = self._capital * risk_percent
        
        risk_per_share = abs(entry_price - stop_loss)
        
        if risk_per_share == 0:
            return 0
        
        quantity = int(risk_amount / risk_per_share)
        
        # Apply max capital per trade
        max_position = self._capital * self.risk_config.max_capital_per_trade
        max_quantity = int(max_position / entry_price)
        
        return min(quantity, max_quantity)
    
    def add_position(self, position: SwingPosition):
        """Add a new swing position."""
        position.sector = self.get_sector(position.symbol)
        position.highest_price = position.entry_price
        position.lowest_price = position.entry_price
        
        self._positions[position.symbol] = position
        self._weekly_state.trades_opened += 1
        
        logger.info(
            f"Swing position opened: {position.symbol} | {position.side.value} "
            f"{position.quantity} @ {position.entry_price}"
        )
    
    def update_position_price(self, symbol: str, current_price: float):
        """Update price and check for trailing SL adjustment."""
        if symbol not in self._positions:
            return
        
        position = self._positions[symbol]
        position.current_price = current_price
        
        # Track high/low
        if current_price > position.highest_price:
            position.highest_price = current_price
        if current_price < position.lowest_price:
            position.lowest_price = current_price
        
        # Check trailing SL
        if self.risk_config.trailing_sl_enabled:
            self._check_trailing_sl(position)
        
        # Update unrealized P&L
        self._update_unrealized_pnl()
    
    def _check_trailing_sl(self, position: SwingPosition):
        """Check and update trailing stop loss."""
        if not position.is_trailing_sl_active:
            # Activate trailing after reaching 1.5:1 R:R
            risk = abs(position.entry_price - position.stop_loss)
            min_move = risk * self.risk_config.move_sl_to_breakeven_at
            
            if position.side == OrderSide.BUY:
                if position.current_price >= position.entry_price + min_move:
                    position.is_trailing_sl_active = True
                    position.stop_loss = position.entry_price  # Move to breakeven
                    logger.info(f"{position.symbol}: SL moved to breakeven")
            else:
                if position.current_price <= position.entry_price - min_move:
                    position.is_trailing_sl_active = True
                    position.stop_loss = position.entry_price
                    logger.info(f"{position.symbol}: SL moved to breakeven")
        
        else:
            # Trail the stop loss
            # Using a simple approach: trail at 2x ATR from high/low
            # In production, you'd pass ATR here
            trail_percent = 0.03  # 3% trailing
            
            if position.side == OrderSide.BUY:
                new_sl = position.highest_price * (1 - trail_percent)
                if new_sl > position.stop_loss:
                    position.stop_loss = new_sl
                    logger.debug(f"{position.symbol}: Trailing SL updated to {new_sl:.2f}")
            else:
                new_sl = position.lowest_price * (1 + trail_percent)
                if new_sl < position.stop_loss:
                    position.stop_loss = new_sl
                    logger.debug(f"{position.symbol}: Trailing SL updated to {new_sl:.2f}")
    
    def _update_unrealized_pnl(self):
        """Update total unrealized P&L."""
        total = sum(p.pnl for p in self._positions.values())
        self._weekly_state.unrealized_pnl = total
        
        # Track peak and drawdown
        total_pnl = self._weekly_state.realized_pnl + total
        if total_pnl > self._weekly_state.peak_equity:
            self._weekly_state.peak_equity = total_pnl
        
        drawdown = self._weekly_state.peak_equity - total_pnl
        if drawdown > self._weekly_state.max_drawdown:
            self._weekly_state.max_drawdown = drawdown
    
    def close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str
    ) -> Optional[TradeResult]:
        """Close a swing position."""
        position = self._positions.pop(symbol, None)
        if not position:
            return None
        
        pnl = (
            (exit_price - position.entry_price) * position.quantity
            if position.side == OrderSide.BUY
            else (position.entry_price - exit_price) * position.quantity
        )
        
        result = TradeResult(
            trade_id=f"SWING_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            symbol=symbol,
            side=position.side,
            quantity=position.quantity,
            entry_price=position.entry_price,
            exit_price=exit_price,
            entry_time=datetime.combine(position.entry_date, datetime.min.time()),
            exit_time=datetime.now(),
            pnl=pnl,
            exit_reason=exit_reason,
            signal_type=None
        )
        
        self._trade_history.append(result)
        self._weekly_state.realized_pnl += pnl
        self._weekly_state.trades_closed += 1
        
        if pnl > 0:
            self._weekly_state.winning_trades += 1
        else:
            self._weekly_state.losing_trades += 1
        
        logger.info(
            f"Swing position closed: {symbol} | {exit_reason} @ {exit_price} | "
            f"P&L: {pnl:.2f} | Days held: {position.holding_days}"
        )
        
        return result
    
    def book_partial_profit(
        self,
        symbol: str,
        quantity: int,
        exit_price: float
    ) -> Optional[float]:
        """
        Book partial profit on a position.
        
        Args:
            symbol: Symbol to partially exit.
            quantity: Quantity to exit.
            exit_price: Exit price.
        
        Returns:
            P&L from partial exit.
        """
        position = self._positions.get(symbol)
        if not position or quantity >= position.quantity:
            return None
        
        # Calculate partial P&L
        if position.side == OrderSide.BUY:
            partial_pnl = (exit_price - position.entry_price) * quantity
        else:
            partial_pnl = (position.entry_price - exit_price) * quantity
        
        position.quantity -= quantity
        position.partial_exits += 1
        
        self._weekly_state.realized_pnl += partial_pnl
        
        logger.info(
            f"Partial profit booked: {symbol} | {quantity} shares @ {exit_price} | "
            f"P&L: {partial_pnl:.2f} | Remaining: {position.quantity}"
        )
        
        return partial_pnl
    
    def get_position(self, symbol: str) -> Optional[SwingPosition]:
        """Get position by symbol."""
        return self._positions.get(symbol)
    
    def get_all_positions(self) -> List[SwingPosition]:
        """Get all swing positions."""
        return list(self._positions.values())
    
    def get_positions_to_review(self, max_holding_days: int = 15) -> List[SwingPosition]:
        """Get positions that need review (approaching max holding)."""
        return [
            p for p in self._positions.values()
            if p.holding_days >= max_holding_days - 2
        ]
    
    def get_risk_status(self) -> dict:
        """Get current risk status."""
        total_value = sum(p.position_value for p in self._positions.values())
        total_risk = sum(p.risk_amount for p in self._positions.values())
        
        # Sector breakdown
        sector_exposure = {}
        for p in self._positions.values():
            sector = p.sector
            if sector not in sector_exposure:
                sector_exposure[sector] = 0
            sector_exposure[sector] += p.position_value / self._capital
        
        return {
            "capital": self._capital,
            "positions_count": len(self._positions),
            "max_positions": self.risk_config.max_positions,
            "total_position_value": total_value,
            "total_risk_amount": total_risk,
            "portfolio_utilization": total_value / self._capital,
            "realized_pnl_weekly": self._weekly_state.realized_pnl,
            "unrealized_pnl": self._weekly_state.unrealized_pnl,
            "total_pnl_weekly": self._weekly_state.realized_pnl + self._weekly_state.unrealized_pnl,
            "max_drawdown_weekly": self._weekly_state.max_drawdown,
            "sector_exposure": sector_exposure,
            "circuit_breaker": self._weekly_state.is_circuit_breaker_triggered,
            "trades_this_week": self._weekly_state.trades_closed,
            "win_rate_weekly": (
                self._weekly_state.winning_trades / self._weekly_state.trades_closed * 100
                if self._weekly_state.trades_closed > 0 else 0
            )
        }
    
    def get_portfolio_summary(self) -> List[Dict]:
        """Get summary of all positions."""
        return [
            {
                "symbol": p.symbol,
                "side": p.side.value,
                "quantity": p.quantity,
                "entry": p.entry_price,
                "current": p.current_price,
                "pnl": p.pnl,
                "pnl_percent": p.pnl_percent,
                "stop_loss": p.stop_loss,
                "target_1": p.target_1,
                "holding_days": p.holding_days,
                "sector": p.sector,
                "trailing_active": p.is_trailing_sl_active
            }
            for p in self._positions.values()
        ]


# Singleton
_swing_risk_guard: Optional[SwingRiskGuard] = None


def get_swing_risk_guard() -> SwingRiskGuard:
    """Get singleton swing risk guard."""
    global _swing_risk_guard
    if _swing_risk_guard is None:
        _swing_risk_guard = SwingRiskGuard()
    return _swing_risk_guard
