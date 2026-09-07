"""Backtesting module for swing trading strategies."""

from backtesting.backtest_engine import BacktestEngine, BacktestConfig, BacktestResult
from backtesting.streak_rules import StreakRule, StreakCondition, IndicatorType

__all__ = [
    "BacktestEngine",
    "BacktestConfig", 
    "BacktestResult",
    "StreakRule",
    "StreakCondition",
    "IndicatorType"
]
