"""Configuration management for trading service."""

import os
from enum import Enum
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from core.models import TradingMode


# Load environment variables
load_dotenv()


class TradingStyle(str, Enum):
    """Trading style enum."""
    INTRADAY = "intraday"
    SWING = "swing"


class BrokerConfig(BaseModel):
    """Broker configuration."""
    name: str = "zerodha"
    api_key: str = Field(default_factory=lambda: os.getenv("KITE_API_KEY", ""))
    api_secret: str = Field(default_factory=lambda: os.getenv("KITE_API_SECRET", ""))


class IntradayConfig(BaseModel):
    """Intraday trading session configuration."""
    start_time: str = "09:15"
    last_entry_time: str = "14:30"
    square_off_time: str = "15:15"
    opening_range_minutes: int = 15
    pre_market_start: str = "09:00"


class SwingConfig(BaseModel):
    """Swing trading configuration."""
    min_holding_days: int = 2
    max_holding_days: int = 15
    entry_window_start: str = "09:30"
    entry_window_end: str = "15:00"
    weekly_analysis_day: str = "friday"
    use_weekly_pivots: bool = True
    trend_lookback_days: int = 50


class StrategyConfig(BaseModel):
    """Intraday strategy configuration."""
    type: str = "breakout"
    sr_lookback_days: int = 20
    volume_surge_multiplier: float = 1.5
    min_risk_reward: float = 2.0
    breakout_confirmation_candles: int = 1
    atr_period: int = 14
    pivot_type: str = "standard"  # standard, fibonacci, camarilla


class SwingStrategyConfig(BaseModel):
    """Swing strategy configuration."""
    type: str = "trend_breakout"
    sr_lookback_days: int = 60
    volume_surge_multiplier: float = 1.3
    min_risk_reward: float = 2.5
    atr_period: int = 14
    atr_multiplier_sl: float = 2.0
    pivot_type: str = "fibonacci"
    trend_ema_short: int = 20
    trend_ema_long: int = 50
    breakout_confirmation_days: int = 1
    consolidation_min_days: int = 5


class RiskConfig(BaseModel):
    """Intraday risk management configuration."""
    max_positions: int = 5
    risk_per_trade: float = 0.005  # 0.5% of capital
    max_daily_loss: float = 0.02  # 2% of capital
    sl_buffer_percent: float = 0.1
    move_sl_to_breakeven_at: float = 1.0  # Move SL to BE at 1:1 RR
    trailing_sl_enabled: bool = False
    max_capital_per_trade: float = 0.2  # Max 20% capital per trade


class SwingRiskConfig(BaseModel):
    """Swing risk management configuration."""
    max_positions: int = 8
    risk_per_trade: float = 0.01  # 1% of capital (wider stops)
    max_weekly_loss: float = 0.05  # 5% weekly loss limit
    sl_buffer_percent: float = 0.2
    move_sl_to_breakeven_at: float = 1.5  # Move SL to BE at 1.5:1 RR
    trailing_sl_enabled: bool = True
    trailing_sl_atr_multiplier: float = 1.5
    max_capital_per_trade: float = 0.15  # Max 15% capital per trade
    max_sector_exposure: float = 0.30  # Max 30% in one sector


class LLMConfig(BaseModel):
    """LLM configuration."""
    enabled: bool = True
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    validate_all_trades: bool = False  # If True, LLM validates every trade
    sentiment_check: bool = False


class WatchlistConfig(BaseModel):
    """Watchlist configuration."""
    symbols: List[str] = Field(default_factory=lambda: [
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
        "KOTAKBANK", "SBIN", "BHARTIARTL", "ITC", "HINDUNILVR"
    ])
    exchange: str = "NSE"


class TradingConfig(BaseSettings):
    """Main trading configuration."""
    mode: TradingMode = TradingMode.PAPER
    trading_style: TradingStyle = TradingStyle.INTRADAY
    capital: float = 100000.0  # Trading capital
    
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    intraday: IntradayConfig = Field(default_factory=IntradayConfig)
    swing: SwingConfig = Field(default_factory=SwingConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    swing_strategy: SwingStrategyConfig = Field(default_factory=SwingStrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    swing_risk: SwingRiskConfig = Field(default_factory=SwingRiskConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    watchlist: WatchlistConfig = Field(default_factory=WatchlistConfig)
    swing_watchlist: WatchlistConfig = Field(default_factory=WatchlistConfig)
    
    class Config:
        env_prefix = "TRADING_"
    
    def get_active_watchlist(self) -> WatchlistConfig:
        """Get watchlist based on trading style."""
        if self.trading_style == TradingStyle.SWING:
            return self.swing_watchlist
        return self.watchlist
    
    def get_active_risk_config(self):
        """Get risk config based on trading style."""
        if self.trading_style == TradingStyle.SWING:
            return self.swing_risk
        return self.risk
    
    def get_active_strategy_config(self):
        """Get strategy config based on trading style."""
        if self.trading_style == TradingStyle.SWING:
            return self.swing_strategy
        return self.strategy


def load_config(config_path: Optional[str] = None) -> TradingConfig:
    """Load configuration from YAML file and environment."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"
    
    config_dict = {}
    
    if Path(config_path).exists():
        with open(config_path, "r") as f:
            config_dict = yaml.safe_load(f) or {}
    
    # Override mode from environment if set
    env_mode = os.getenv("TRADING_MODE")
    if env_mode:
        config_dict["mode"] = env_mode
    
    return TradingConfig(**config_dict)


# Global config instance
_config: Optional[TradingConfig] = None


def get_config() -> TradingConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config(config_path: Optional[str] = None) -> TradingConfig:
    """Reload configuration from file."""
    global _config
    _config = load_config(config_path)
    return _config
