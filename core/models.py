"""Core data models for the trading service."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TradingMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ProductType(str, Enum):
    MIS = "MIS"  # Intraday
    CNC = "CNC"  # Delivery
    NRML = "NRML"  # F&O


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class SignalType(str, Enum):
    BREAKOUT_LONG = "BREAKOUT_LONG"
    BREAKOUT_SHORT = "BREAKOUT_SHORT"
    ORB_LONG = "ORB_LONG"
    ORB_SHORT = "ORB_SHORT"


@dataclass
class Tick:
    """Real-time market tick data."""
    symbol: str
    instrument_token: int
    last_price: float
    volume: int
    timestamp: datetime
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    change: float = 0.0
    average_price: float = 0.0
    
    @property
    def change_percent(self) -> float:
        if self.close > 0:
            return ((self.last_price - self.close) / self.close) * 100
        return 0.0


@dataclass
class OHLC:
    """OHLC candle data."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    
    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)
    
    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)
    
    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low
    
    @property
    def is_bullish(self) -> bool:
        return self.close > self.open


@dataclass
class SRLevel:
    """Support or Resistance level."""
    price: float
    level_type: str  # 'support', 'resistance', 'pivot', 'pdh', 'pdl', 'orb_high', 'orb_low'
    strength: int = 1  # Number of touches
    timestamp: Optional[datetime] = None
    
    def is_near(self, price: float, threshold_percent: float = 0.5) -> bool:
        """Check if price is near this level."""
        threshold = self.price * (threshold_percent / 100)
        return abs(price - self.price) <= threshold


@dataclass
class BreakoutSignal:
    """Breakout signal with entry details."""
    symbol: str
    signal_type: SignalType
    entry_price: float
    stop_loss: float
    target: float
    sr_level: SRLevel
    volume_ratio: float
    timestamp: datetime
    confidence: float = 0.0  # 0 to 1
    
    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.stop_loss)
    
    @property
    def reward(self) -> float:
        return abs(self.target - self.entry_price)
    
    @property
    def risk_reward_ratio(self) -> float:
        if self.risk > 0:
            return self.reward / self.risk
        return 0.0


@dataclass
class Order:
    """Order representation."""
    order_id: str
    symbol: str
    instrument_token: int
    side: OrderSide
    quantity: int
    order_type: OrderType
    product: ProductType
    price: float = 0.0
    trigger_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    average_price: float = 0.0
    placed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    rejection_reason: str = ""


@dataclass
class Position:
    """Active position."""
    symbol: str
    instrument_token: int
    side: OrderSide
    quantity: int
    entry_price: float
    current_price: float
    stop_loss: float
    target: float
    product: ProductType
    entry_time: datetime
    entry_order_id: str
    sl_order_id: Optional[str] = None
    target_order_id: Optional[str] = None
    is_sl_at_breakeven: bool = False
    
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
    def risk_taken(self) -> float:
        return abs(self.entry_price - self.stop_loss) * self.quantity


@dataclass
class TradeResult:
    """Completed trade record."""
    trade_id: str
    symbol: str
    side: OrderSide
    quantity: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    exit_reason: str  # 'target', 'stop_loss', 'square_off', 'manual'
    signal_type: SignalType
    
    @property
    def holding_duration_minutes(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds() / 60


@dataclass
class DailyStats:
    """Daily trading statistics."""
    date: datetime
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_pnl: float = 0.0
    charges: float = 0.0
    net_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_pnl: float = 0.0
    
    @property
    def win_rate(self) -> float:
        if self.total_trades > 0:
            return (self.winning_trades / self.total_trades) * 100
        return 0.0
