"""
Streak-style rule definitions for backtesting.

Allows defining entry/exit conditions using technical indicators
similar to Zerodha Streak platform.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable
import pandas as pd


class IndicatorType(str, Enum):
    """Available indicators for conditions."""
    # Price
    CLOSE = "close"
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    
    # Moving Averages
    SMA = "sma"
    EMA = "ema"
    
    # Momentum
    RSI = "rsi"
    MACD = "macd"
    MACD_SIGNAL = "macd_signal"
    MACD_HISTOGRAM = "macd_histogram"
    
    # Volatility
    ATR = "atr"
    BOLLINGER_UPPER = "bb_upper"
    BOLLINGER_LOWER = "bb_lower"
    BOLLINGER_MIDDLE = "bb_middle"
    
    # Volume
    VOLUME = "volume"
    VOLUME_SMA = "volume_sma"
    
    # Support/Resistance
    SUPPORT = "support"
    RESISTANCE = "resistance"
    
    # Custom
    NUMBER = "number"  # Fixed number value


class Comparator(str, Enum):
    """Comparison operators for conditions."""
    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="
    CROSSES_ABOVE = "crosses_above"
    CROSSES_BELOW = "crosses_below"
    EQUALS = "=="


@dataclass
class StreakCondition:
    """
    A single condition in a Streak rule.
    
    Example: RSI(14) < 30 or Close crosses_above EMA(21)
    """
    left_indicator: IndicatorType
    left_period: int = 14  # Period for indicator (e.g., RSI period, EMA period)
    comparator: Comparator = Comparator.LESS_THAN
    right_indicator: IndicatorType = IndicatorType.NUMBER
    right_period: int = 0  # Period for right indicator or fixed value
    right_value: float = 0.0  # Used when right_indicator is NUMBER
    
    def __str__(self) -> str:
        left = f"{self.left_indicator.value}({self.left_period})" if self.left_period > 0 else self.left_indicator.value
        right = f"{self.right_value}" if self.right_indicator == IndicatorType.NUMBER else \
                f"{self.right_indicator.value}({self.right_period})" if self.right_period > 0 else self.right_indicator.value
        return f"{left} {self.comparator.value} {right}"


@dataclass
class StreakRule:
    """
    A complete Streak-style trading rule with entry and exit conditions.
    """
    name: str
    description: str = ""
    
    # Entry conditions (all must be true - AND logic)
    entry_conditions: list[StreakCondition] = field(default_factory=list)
    
    # Exit conditions (any can trigger - OR logic)
    exit_conditions: list[StreakCondition] = field(default_factory=list)
    
    # Risk management
    stop_loss_percent: float = 2.0  # % below entry
    target_percent: float = 4.0  # % above entry (risk:reward = 1:2)
    trailing_sl_percent: Optional[float] = None  # Optional trailing SL
    max_holding_days: int = 30  # Max days to hold
    
    # Position sizing
    position_size_percent: float = 10.0  # % of capital per trade
    
    def __str__(self) -> str:
        return f"{self.name}: {len(self.entry_conditions)} entry, {len(self.exit_conditions)} exit conditions"


# Pre-built Streak rules based on scanner types
def get_rsi_oversold_bounce_rule() -> StreakRule:
    """RSI oversold with bounce near support."""
    return StreakRule(
        name="RSI Oversold Bounce",
        description="Buy when RSI recovers from oversold (<30) while price is near support",
        entry_conditions=[
            StreakCondition(
                left_indicator=IndicatorType.RSI,
                left_period=14,
                comparator=Comparator.LESS_THAN,
                right_indicator=IndicatorType.NUMBER,
                right_value=35
            ),
            StreakCondition(
                left_indicator=IndicatorType.RSI,
                left_period=14,
                comparator=Comparator.CROSSES_ABOVE,
                right_indicator=IndicatorType.NUMBER,
                right_value=30
            ),
            StreakCondition(
                left_indicator=IndicatorType.CLOSE,
                comparator=Comparator.GREATER_THAN,
                right_indicator=IndicatorType.EMA,
                right_period=50
            ),
        ],
        exit_conditions=[
            StreakCondition(
                left_indicator=IndicatorType.RSI,
                left_period=14,
                comparator=Comparator.GREATER_THAN,
                right_indicator=IndicatorType.NUMBER,
                right_value=70
            ),
        ],
        stop_loss_percent=3.0,
        target_percent=6.0,
        trailing_sl_percent=2.0,
        max_holding_days=20
    )


def get_macd_bullish_crossover_rule() -> StreakRule:
    """MACD bullish crossover with trend confirmation."""
    return StreakRule(
        name="MACD Bullish Crossover",
        description="Buy when MACD crosses above signal line in uptrend",
        entry_conditions=[
            StreakCondition(
                left_indicator=IndicatorType.MACD,
                comparator=Comparator.CROSSES_ABOVE,
                right_indicator=IndicatorType.MACD_SIGNAL
            ),
            StreakCondition(
                left_indicator=IndicatorType.CLOSE,
                comparator=Comparator.GREATER_THAN,
                right_indicator=IndicatorType.EMA,
                right_period=21
            ),
            StreakCondition(
                left_indicator=IndicatorType.EMA,
                left_period=21,
                comparator=Comparator.GREATER_THAN,
                right_indicator=IndicatorType.EMA,
                right_period=50
            ),
        ],
        exit_conditions=[
            StreakCondition(
                left_indicator=IndicatorType.MACD,
                comparator=Comparator.CROSSES_BELOW,
                right_indicator=IndicatorType.MACD_SIGNAL
            ),
        ],
        stop_loss_percent=2.5,
        target_percent=5.0,
        trailing_sl_percent=1.5,
        max_holding_days=15
    )


def get_ema_pullback_rule() -> StreakRule:
    """Buy on pullback to EMA in uptrend."""
    return StreakRule(
        name="EMA Pullback",
        description="Buy when price pulls back to 21 EMA in uptrend",
        entry_conditions=[
            StreakCondition(
                left_indicator=IndicatorType.EMA,
                left_period=21,
                comparator=Comparator.GREATER_THAN,
                right_indicator=IndicatorType.EMA,
                right_period=50
            ),
            StreakCondition(
                left_indicator=IndicatorType.LOW,
                comparator=Comparator.LESS_EQUAL,
                right_indicator=IndicatorType.EMA,
                right_period=21
            ),
            StreakCondition(
                left_indicator=IndicatorType.CLOSE,
                comparator=Comparator.GREATER_THAN,
                right_indicator=IndicatorType.EMA,
                right_period=21
            ),
            StreakCondition(
                left_indicator=IndicatorType.RSI,
                left_period=14,
                comparator=Comparator.GREATER_THAN,
                right_indicator=IndicatorType.NUMBER,
                right_value=40
            ),
        ],
        exit_conditions=[
            StreakCondition(
                left_indicator=IndicatorType.CLOSE,
                comparator=Comparator.LESS_THAN,
                right_indicator=IndicatorType.EMA,
                right_period=50
            ),
        ],
        stop_loss_percent=2.0,
        target_percent=4.0,
        trailing_sl_percent=1.5,
        max_holding_days=10
    )


def get_rsi_overbought_exit_rule() -> StreakRule:
    """Exit when RSI becomes overbought."""
    return StreakRule(
        name="RSI Overbought Exit",
        description="Exit when RSI reaches overbought levels (>70)",
        entry_conditions=[
            StreakCondition(
                left_indicator=IndicatorType.RSI,
                left_period=14,
                comparator=Comparator.LESS_THAN,
                right_indicator=IndicatorType.NUMBER,
                right_value=50
            ),
        ],
        exit_conditions=[
            StreakCondition(
                left_indicator=IndicatorType.RSI,
                left_period=14,
                comparator=Comparator.GREATER_THAN,
                right_indicator=IndicatorType.NUMBER,
                right_value=70
            ),
            StreakCondition(
                left_indicator=IndicatorType.RSI,
                left_period=14,
                comparator=Comparator.CROSSES_BELOW,
                right_indicator=IndicatorType.NUMBER,
                right_value=70
            ),
        ],
        stop_loss_percent=3.0,
        target_percent=8.0,
        max_holding_days=30
    )


def get_breakout_with_volume_rule() -> StreakRule:
    """Breakout above resistance with volume confirmation."""
    return StreakRule(
        name="Breakout with Volume",
        description="Buy on breakout above resistance with high volume",
        entry_conditions=[
            StreakCondition(
                left_indicator=IndicatorType.CLOSE,
                comparator=Comparator.CROSSES_ABOVE,
                right_indicator=IndicatorType.RESISTANCE
            ),
            StreakCondition(
                left_indicator=IndicatorType.VOLUME,
                comparator=Comparator.GREATER_THAN,
                right_indicator=IndicatorType.VOLUME_SMA,
                right_period=20
            ),
            StreakCondition(
                left_indicator=IndicatorType.RSI,
                left_period=14,
                comparator=Comparator.LESS_THAN,
                right_indicator=IndicatorType.NUMBER,
                right_value=70
            ),
        ],
        exit_conditions=[
            StreakCondition(
                left_indicator=IndicatorType.CLOSE,
                comparator=Comparator.LESS_THAN,
                right_indicator=IndicatorType.SUPPORT
            ),
        ],
        stop_loss_percent=2.0,
        target_percent=6.0,
        trailing_sl_percent=2.0,
        max_holding_days=20
    )


def get_all_preset_rules() -> list[StreakRule]:
    """Get all preset rules."""
    return [
        get_rsi_oversold_bounce_rule(),
        get_macd_bullish_crossover_rule(),
        get_ema_pullback_rule(),
        get_rsi_overbought_exit_rule(),
        get_breakout_with_volume_rule(),
    ]
