"""Risk management module with position sizing and daily limits."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

from core.config import get_config, RiskConfig
from core.models import (
    BreakoutSignal, DailyStats, Order, OrderSide, Position, TradeResult
)

logger = logging.getLogger(__name__)


@dataclass
class RiskCheckResult:
    """Result of a risk check."""
    allowed: bool
    reason: str
    suggested_quantity: int = 0
    adjusted_sl: float = 0.0
    adjusted_target: float = 0.0


@dataclass 
class DailyRiskState:
    """Daily risk tracking state."""
    date: date
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    peak_pnl: float = 0.0
    max_drawdown: float = 0.0
    trades_taken: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    is_circuit_breaker_triggered: bool = False
    circuit_breaker_reason: str = ""


class RiskGuard:
    """Risk management and position sizing."""
    
    def __init__(self, capital: Optional[float] = None):
        self.config = get_config()
        self.risk_config: RiskConfig = self.config.risk
        
        # Capital can be set explicitly or from config
        self._capital = capital or self.config.capital
        
        # Daily state
        self._daily_state = DailyRiskState(date=datetime.now().date())
        
        # Active positions tracking
        self._active_positions: Dict[str, Position] = {}
    
    @property
    def capital(self) -> float:
        """Get trading capital."""
        return self._capital
    
    @capital.setter
    def capital(self, value: float):
        """Update trading capital."""
        self._capital = value
    
    def reset_daily_state(self):
        """Reset daily risk state (call at start of day)."""
        self._daily_state = DailyRiskState(date=datetime.now().date())
        logger.info("Daily risk state reset")
    
    def check_daily_state(self):
        """Check and reset if it's a new day."""
        today = datetime.now().date()
        if self._daily_state.date != today:
            self.reset_daily_state()
    
    # ==================== Risk Checks ====================
    
    def check_trade_allowed(
        self,
        signal: BreakoutSignal,
        current_positions: Optional[Dict[str, Position]] = None
    ) -> RiskCheckResult:
        """
        Check if a trade is allowed based on risk rules.
        
        Args:
            signal: The breakout signal to validate.
            current_positions: Current open positions.
        
        Returns:
            RiskCheckResult with decision and details.
        """
        self.check_daily_state()
        positions = current_positions or self._active_positions
        
        # Check circuit breaker
        if self._daily_state.is_circuit_breaker_triggered:
            return RiskCheckResult(
                allowed=False,
                reason=f"Circuit breaker triggered: {self._daily_state.circuit_breaker_reason}"
            )
        
        # Check max positions
        if len(positions) >= self.risk_config.max_positions:
            return RiskCheckResult(
                allowed=False,
                reason=f"Max positions ({self.risk_config.max_positions}) reached"
            )
        
        # Check if already in this symbol
        if signal.symbol in positions:
            return RiskCheckResult(
                allowed=False,
                reason=f"Already have position in {signal.symbol}"
            )
        
        # Check daily loss limit
        total_pnl = self._daily_state.realized_pnl + self._daily_state.unrealized_pnl
        max_loss = self._capital * self.risk_config.max_daily_loss
        
        if total_pnl <= -max_loss:
            self._trigger_circuit_breaker("Daily loss limit reached")
            return RiskCheckResult(
                allowed=False,
                reason=f"Daily loss limit ({self.risk_config.max_daily_loss*100:.1f}%) reached"
            )
        
        # Check minimum risk-reward
        if signal.risk_reward_ratio < self.risk_config.move_sl_to_breakeven_at:
            return RiskCheckResult(
                allowed=False,
                reason=f"Risk-reward {signal.risk_reward_ratio:.2f} below minimum"
            )
        
        # Calculate position size
        quantity = self.calculate_position_size(
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss
        )
        
        if quantity == 0:
            return RiskCheckResult(
                allowed=False,
                reason="Calculated quantity is 0 (risk too high or capital insufficient)"
            )
        
        # All checks passed
        return RiskCheckResult(
            allowed=True,
            reason="All risk checks passed",
            suggested_quantity=quantity,
            adjusted_sl=signal.stop_loss,
            adjusted_target=signal.target
        )
    
    def _trigger_circuit_breaker(self, reason: str):
        """Trigger daily circuit breaker."""
        self._daily_state.is_circuit_breaker_triggered = True
        self._daily_state.circuit_breaker_reason = reason
        logger.warning(f"CIRCUIT BREAKER TRIGGERED: {reason}")
    
    # ==================== Position Sizing ====================
    
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
            override_risk_percent: Override the configured risk percent.
        
        Returns:
            Number of shares to trade.
        """
        risk_percent = override_risk_percent or self.risk_config.risk_per_trade
        
        # Risk amount in currency
        risk_amount = self._capital * risk_percent
        
        # Risk per share
        risk_per_share = abs(entry_price - stop_loss)
        
        if risk_per_share == 0:
            logger.warning("Risk per share is 0, cannot calculate position size")
            return 0
        
        # Calculate quantity
        quantity = int(risk_amount / risk_per_share)
        
        # Apply max capital per trade limit
        max_position_value = self._capital * self.risk_config.max_capital_per_trade
        max_quantity_by_capital = int(max_position_value / entry_price)
        
        quantity = min(quantity, max_quantity_by_capital)
        
        # Ensure minimum of 1
        return max(0, quantity)
    
    def calculate_sl_target(
        self,
        entry_price: float,
        sr_level_price: float,
        direction: str,  # 'long' or 'short'
        risk_reward: Optional[float] = None
    ) -> Tuple[float, float]:
        """
        Calculate stop loss and target prices.
        
        Args:
            entry_price: Entry price.
            sr_level_price: The S/R level that was broken.
            direction: Trade direction.
            risk_reward: Target risk-reward ratio.
        
        Returns:
            Tuple of (stop_loss, target).
        """
        rr = risk_reward or 2.0
        buffer_percent = self.risk_config.sl_buffer_percent
        buffer = sr_level_price * (buffer_percent / 100)
        
        if direction == "long":
            # SL below the broken level (now support)
            stop_loss = sr_level_price - buffer
            risk = entry_price - stop_loss
            target = entry_price + (risk * rr)
        else:
            # SL above the broken level (now resistance)
            stop_loss = sr_level_price + buffer
            risk = stop_loss - entry_price
            target = entry_price - (risk * rr)
        
        return stop_loss, target
    
    # ==================== Position Tracking ====================
    
    def add_position(self, position: Position):
        """Add a new position to tracking."""
        self._active_positions[position.symbol] = position
        self._daily_state.trades_taken += 1
        logger.info(f"Position added: {position.symbol} @ {position.entry_price}")
    
    def remove_position(self, symbol: str) -> Optional[Position]:
        """Remove a position from tracking."""
        return self._active_positions.pop(symbol, None)
    
    def update_position_price(self, symbol: str, current_price: float):
        """Update current price for a position."""
        if symbol in self._active_positions:
            self._active_positions[symbol].current_price = current_price
            self._update_unrealized_pnl()
    
    def _update_unrealized_pnl(self):
        """Update total unrealized P&L."""
        total_unrealized = sum(p.pnl for p in self._active_positions.values())
        self._daily_state.unrealized_pnl = total_unrealized
        
        # Track peak and drawdown
        total_pnl = self._daily_state.realized_pnl + total_unrealized
        if total_pnl > self._daily_state.peak_pnl:
            self._daily_state.peak_pnl = total_pnl
        
        drawdown = self._daily_state.peak_pnl - total_pnl
        if drawdown > self._daily_state.max_drawdown:
            self._daily_state.max_drawdown = drawdown
    
    def record_trade_result(self, result: TradeResult):
        """Record a completed trade result."""
        self._daily_state.realized_pnl += result.pnl
        
        if result.pnl > 0:
            self._daily_state.winning_trades += 1
        else:
            self._daily_state.losing_trades += 1
        
        logger.info(
            f"Trade closed: {result.symbol} | P&L: {result.pnl:.2f} | "
            f"Exit: {result.exit_reason}"
        )
    
    def get_active_positions(self) -> Dict[str, Position]:
        """Get all active positions."""
        return self._active_positions.copy()
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a symbol."""
        return self._active_positions.get(symbol)
    
    # ==================== Stop Loss Management ====================
    
    def should_move_sl_to_breakeven(self, position: Position) -> bool:
        """Check if SL should be moved to breakeven."""
        if position.is_sl_at_breakeven:
            return False
        
        risk = abs(position.entry_price - position.stop_loss)
        target_move = risk * self.risk_config.move_sl_to_breakeven_at
        
        if position.side == OrderSide.BUY:
            return position.current_price >= position.entry_price + target_move
        else:
            return position.current_price <= position.entry_price - target_move
    
    def calculate_trailing_sl(
        self,
        position: Position,
        atr: float,
        atr_multiplier: float = 2.0
    ) -> Optional[float]:
        """
        Calculate trailing stop loss based on ATR.
        
        Args:
            position: Current position.
            atr: Average True Range value.
            atr_multiplier: Multiplier for ATR.
        
        Returns:
            New SL price or None if no adjustment needed.
        """
        if not self.risk_config.trailing_sl_enabled:
            return None
        
        trail_distance = atr * atr_multiplier
        
        if position.side == OrderSide.BUY:
            new_sl = position.current_price - trail_distance
            # Only move SL up, never down
            if new_sl > position.stop_loss:
                return new_sl
        else:
            new_sl = position.current_price + trail_distance
            # Only move SL down, never up
            if new_sl < position.stop_loss:
                return new_sl
        
        return None
    
    # ==================== Reporting ====================
    
    def get_daily_stats(self) -> DailyStats:
        """Get daily trading statistics."""
        return DailyStats(
            date=datetime.now(),
            total_trades=self._daily_state.trades_taken,
            winning_trades=self._daily_state.winning_trades,
            losing_trades=self._daily_state.losing_trades,
            gross_pnl=self._daily_state.realized_pnl,
            charges=0,  # Can be calculated separately
            net_pnl=self._daily_state.realized_pnl,  # Minus charges when implemented
            max_drawdown=self._daily_state.max_drawdown,
            peak_pnl=self._daily_state.peak_pnl
        )
    
    def get_risk_status(self) -> dict:
        """Get current risk status."""
        total_pnl = self._daily_state.realized_pnl + self._daily_state.unrealized_pnl
        max_loss = self._capital * self.risk_config.max_daily_loss
        
        return {
            "capital": self._capital,
            "positions_count": len(self._active_positions),
            "max_positions": self.risk_config.max_positions,
            "realized_pnl": self._daily_state.realized_pnl,
            "unrealized_pnl": self._daily_state.unrealized_pnl,
            "total_pnl": total_pnl,
            "daily_loss_limit": max_loss,
            "loss_limit_used_percent": abs(min(0, total_pnl)) / max_loss * 100 if max_loss > 0 else 0,
            "max_drawdown": self._daily_state.max_drawdown,
            "circuit_breaker_triggered": self._daily_state.is_circuit_breaker_triggered,
            "trades_taken": self._daily_state.trades_taken,
            "win_rate": (
                self._daily_state.winning_trades / self._daily_state.trades_taken * 100
                if self._daily_state.trades_taken > 0 else 0
            )
        }


# Singleton instance
_risk_guard: Optional[RiskGuard] = None


def get_risk_guard() -> RiskGuard:
    """Get the singleton risk guard instance."""
    global _risk_guard
    if _risk_guard is None:
        _risk_guard = RiskGuard()
    return _risk_guard
