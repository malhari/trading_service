"""
Streak-style Backtesting Engine.

Runs backtests on historical data using Streak rules and generates
comprehensive performance metrics.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional
from enum import Enum
import pandas as pd
import numpy as np

from backtesting.streak_rules import (
    StreakRule, StreakCondition, IndicatorType, Comparator
)


class TradeStatus(str, Enum):
    """Trade outcome status."""
    TARGET_HIT = "target_hit"
    STOP_LOSS_HIT = "stop_loss_hit"
    TRAILING_SL_HIT = "trailing_sl_hit"
    EXIT_CONDITION = "exit_condition"
    MAX_DAYS = "max_days"
    OPEN = "open"


@dataclass
class BacktestTrade:
    """A single trade in the backtest."""
    entry_date: date
    entry_price: float
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    status: TradeStatus = TradeStatus.OPEN
    pnl: float = 0.0
    pnl_percent: float = 0.0
    holding_days: int = 0
    max_profit_percent: float = 0.0
    max_drawdown_percent: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0


@dataclass
class BacktestConfig:
    """Configuration for backtesting."""
    initial_capital: float = 100000.0
    position_size_percent: float = 10.0  # % of capital per trade
    max_open_positions: int = 5
    commission_percent: float = 0.1  # Brokerage + taxes
    slippage_percent: float = 0.05  # Slippage assumption
    
    # Date range
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    lookback_days: int = 365  # Default 1 year backtest


@dataclass
class BacktestResult:
    """Complete backtest result with metrics."""
    rule_name: str
    symbol: str
    config: BacktestConfig
    
    # Trade list
    trades: list[BacktestTrade] = field(default_factory=list)
    
    # Summary metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    
    # P&L metrics
    total_pnl: float = 0.0
    total_pnl_percent: float = 0.0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    avg_profit_percent: float = 0.0
    avg_loss_percent: float = 0.0
    largest_profit: float = 0.0
    largest_loss: float = 0.0
    
    # Risk metrics
    profit_factor: float = 0.0
    risk_reward_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_percent: float = 0.0
    sharpe_ratio: float = 0.0
    
    # Time metrics
    avg_holding_days: float = 0.0
    max_holding_days: int = 0
    avg_winning_days: float = 0.0
    avg_losing_days: float = 0.0
    
    # Exit analysis
    target_hits: int = 0
    stop_loss_hits: int = 0
    trailing_sl_hits: int = 0
    exit_condition_hits: int = 0
    max_days_exits: int = 0
    
    # Equity curve
    equity_curve: list[tuple[date, float]] = field(default_factory=list)


class BacktestEngine:
    """
    Engine to run backtests using Streak-style rules.
    """
    
    def __init__(self, config: Optional[BacktestConfig] = None):
        """Initialize backtest engine."""
        self.config = config or BacktestConfig()
        self._indicator_cache: dict[str, pd.Series] = {}
    
    def run_backtest(
        self,
        rule: StreakRule,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN"
    ) -> BacktestResult:
        """
        Run backtest for a rule on historical data.
        
        Args:
            rule: Streak rule to backtest.
            df: DataFrame with OHLCV data (must have: open, high, low, close, volume, date).
            symbol: Symbol name for reporting.
        
        Returns:
            BacktestResult with all metrics.
        """
        # Prepare data
        df = df.copy()
        df = df.sort_values('date' if 'date' in df.columns else df.index.name)
        df = df.reset_index(drop=True)
        
        # Calculate all indicators
        self._calculate_indicators(df)
        
        # Initialize result
        result = BacktestResult(
            rule_name=rule.name,
            symbol=symbol,
            config=self.config
        )
        
        # Trading state
        capital = self.config.initial_capital
        open_trade: Optional[BacktestTrade] = None
        equity_curve = [(df.iloc[0]['date'] if 'date' in df.columns else df.index[0], capital)]
        
        # Iterate through each day
        for i in range(50, len(df)):  # Start after warmup period
            row = df.iloc[i]
            prev_row = df.iloc[i-1]
            current_date = row['date'] if 'date' in row else df.index[i]
            
            if open_trade is None:
                # Check entry conditions
                if self._check_entry(rule, df, i):
                    entry_price = row['close'] * (1 + self.config.slippage_percent / 100)
                    position_value = capital * (rule.position_size_percent / 100)
                    
                    open_trade = BacktestTrade(
                        entry_date=current_date,
                        entry_price=entry_price,
                        stop_loss=entry_price * (1 - rule.stop_loss_percent / 100),
                        target=entry_price * (1 + rule.target_percent / 100)
                    )
            else:
                # Update trade stats
                open_trade.holding_days += 1
                current_profit_pct = ((row['high'] - open_trade.entry_price) / open_trade.entry_price) * 100
                current_loss_pct = ((row['low'] - open_trade.entry_price) / open_trade.entry_price) * 100
                
                open_trade.max_profit_percent = max(open_trade.max_profit_percent, current_profit_pct)
                open_trade.max_drawdown_percent = min(open_trade.max_drawdown_percent, current_loss_pct)
                
                # Update trailing SL if enabled
                if rule.trailing_sl_percent and current_profit_pct > rule.trailing_sl_percent:
                    new_sl = row['high'] * (1 - rule.trailing_sl_percent / 100)
                    if new_sl > open_trade.stop_loss:
                        open_trade.stop_loss = new_sl
                
                # Check exit conditions
                exit_price = None
                exit_status = None
                
                # 1. Stop loss hit (check with low)
                if row['low'] <= open_trade.stop_loss:
                    exit_price = open_trade.stop_loss * (1 - self.config.slippage_percent / 100)
                    exit_status = TradeStatus.TRAILING_SL_HIT if rule.trailing_sl_percent and \
                                  open_trade.stop_loss > open_trade.entry_price * (1 - rule.stop_loss_percent / 100) \
                                  else TradeStatus.STOP_LOSS_HIT
                
                # 2. Target hit (check with high)
                elif row['high'] >= open_trade.target:
                    exit_price = open_trade.target * (1 - self.config.slippage_percent / 100)
                    exit_status = TradeStatus.TARGET_HIT
                
                # 3. Exit conditions met
                elif self._check_exit(rule, df, i):
                    exit_price = row['close'] * (1 - self.config.slippage_percent / 100)
                    exit_status = TradeStatus.EXIT_CONDITION
                
                # 4. Max holding days
                elif open_trade.holding_days >= rule.max_holding_days:
                    exit_price = row['close'] * (1 - self.config.slippage_percent / 100)
                    exit_status = TradeStatus.MAX_DAYS
                
                # Close trade if exit triggered
                if exit_price:
                    open_trade.exit_date = current_date
                    open_trade.exit_price = exit_price
                    open_trade.status = exit_status
                    
                    # Calculate P&L
                    position_value = capital * (rule.position_size_percent / 100)
                    shares = position_value / open_trade.entry_price
                    gross_pnl = (exit_price - open_trade.entry_price) * shares
                    commission = position_value * (self.config.commission_percent / 100) * 2  # Entry + exit
                    
                    open_trade.pnl = gross_pnl - commission
                    open_trade.pnl_percent = (open_trade.pnl / position_value) * 100
                    
                    # Update capital
                    capital += open_trade.pnl
                    
                    result.trades.append(open_trade)
                    open_trade = None
            
            # Update equity curve
            if open_trade:
                unrealized_pnl = (row['close'] - open_trade.entry_price) / open_trade.entry_price
                current_equity = capital + (capital * rule.position_size_percent / 100) * unrealized_pnl
            else:
                current_equity = capital
            
            equity_curve.append((current_date, current_equity))
        
        # Close any open trade at end
        if open_trade:
            last_row = df.iloc[-1]
            open_trade.exit_date = last_row['date'] if 'date' in last_row else df.index[-1]
            open_trade.exit_price = last_row['close']
            open_trade.status = TradeStatus.OPEN
            
            position_value = capital * (rule.position_size_percent / 100)
            shares = position_value / open_trade.entry_price
            open_trade.pnl = (open_trade.exit_price - open_trade.entry_price) * shares
            open_trade.pnl_percent = (open_trade.pnl / position_value) * 100
            
            result.trades.append(open_trade)
        
        result.equity_curve = equity_curve
        
        # Calculate final metrics
        self._calculate_metrics(result)
        
        return result
    
    def _calculate_indicators(self, df: pd.DataFrame) -> None:
        """Calculate all technical indicators on DataFrame."""
        # EMAs
        for period in [9, 12, 21, 26, 50, 100, 200]:
            df[f'ema_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
        
        # SMAs
        for period in [20, 50, 100, 200]:
            df[f'sma_{period}'] = df['close'].rolling(window=period).mean()
        
        # RSI
        for period in [7, 14, 21]:
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            df[f'rsi_{period}'] = 100 - (100 / (1 + rs))
        
        # MACD
        ema_12 = df['close'].ewm(span=12, adjust=False).mean()
        ema_26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema_12 - ema_26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr_14'] = tr.rolling(window=14).mean()
        
        # Bollinger Bands
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        
        # Volume SMA
        df['volume_sma_20'] = df['volume'].rolling(window=20).mean()
        
        # Support/Resistance (simple pivot-based)
        df['support'] = df['low'].rolling(window=20).min()
        df['resistance'] = df['high'].rolling(window=20).max()
    
    def _get_indicator_value(
        self,
        df: pd.DataFrame,
        idx: int,
        indicator: IndicatorType,
        period: int = 0,
        offset: int = 0
    ) -> float:
        """Get indicator value at specific index."""
        row = df.iloc[idx - offset]
        
        if indicator == IndicatorType.CLOSE:
            return row['close']
        elif indicator == IndicatorType.OPEN:
            return row['open']
        elif indicator == IndicatorType.HIGH:
            return row['high']
        elif indicator == IndicatorType.LOW:
            return row['low']
        elif indicator == IndicatorType.VOLUME:
            return row['volume']
        elif indicator == IndicatorType.EMA:
            return row.get(f'ema_{period}', row['close'])
        elif indicator == IndicatorType.SMA:
            return row.get(f'sma_{period}', row['close'])
        elif indicator == IndicatorType.RSI:
            return row.get(f'rsi_{period}', 50)
        elif indicator == IndicatorType.MACD:
            return row.get('macd', 0)
        elif indicator == IndicatorType.MACD_SIGNAL:
            return row.get('macd_signal', 0)
        elif indicator == IndicatorType.MACD_HISTOGRAM:
            return row.get('macd_histogram', 0)
        elif indicator == IndicatorType.ATR:
            return row.get(f'atr_{period}', row.get('atr_14', 0))
        elif indicator == IndicatorType.BOLLINGER_UPPER:
            return row.get('bb_upper', row['close'] * 1.02)
        elif indicator == IndicatorType.BOLLINGER_LOWER:
            return row.get('bb_lower', row['close'] * 0.98)
        elif indicator == IndicatorType.BOLLINGER_MIDDLE:
            return row.get('bb_middle', row['close'])
        elif indicator == IndicatorType.VOLUME_SMA:
            return row.get(f'volume_sma_{period}', row.get('volume_sma_20', row['volume']))
        elif indicator == IndicatorType.SUPPORT:
            return row.get('support', row['low'])
        elif indicator == IndicatorType.RESISTANCE:
            return row.get('resistance', row['high'])
        
        return 0.0
    
    def _check_condition(
        self,
        condition: StreakCondition,
        df: pd.DataFrame,
        idx: int
    ) -> bool:
        """Check if a single condition is met."""
        left_val = self._get_indicator_value(df, idx, condition.left_indicator, condition.left_period)
        
        if condition.right_indicator == IndicatorType.NUMBER:
            right_val = condition.right_value
        else:
            right_val = self._get_indicator_value(df, idx, condition.right_indicator, condition.right_period)
        
        # Handle crossover conditions
        if condition.comparator in [Comparator.CROSSES_ABOVE, Comparator.CROSSES_BELOW]:
            if idx < 1:
                return False
            
            left_prev = self._get_indicator_value(df, idx, condition.left_indicator, condition.left_period, offset=1)
            if condition.right_indicator == IndicatorType.NUMBER:
                right_prev = condition.right_value
            else:
                right_prev = self._get_indicator_value(df, idx, condition.right_indicator, condition.right_period, offset=1)
            
            if condition.comparator == Comparator.CROSSES_ABOVE:
                return left_prev <= right_prev and left_val > right_val
            else:  # CROSSES_BELOW
                return left_prev >= right_prev and left_val < right_val
        
        # Standard comparisons
        if condition.comparator == Comparator.GREATER_THAN:
            return left_val > right_val
        elif condition.comparator == Comparator.LESS_THAN:
            return left_val < right_val
        elif condition.comparator == Comparator.GREATER_EQUAL:
            return left_val >= right_val
        elif condition.comparator == Comparator.LESS_EQUAL:
            return left_val <= right_val
        elif condition.comparator == Comparator.EQUALS:
            return abs(left_val - right_val) < 0.0001
        
        return False
    
    def _check_entry(self, rule: StreakRule, df: pd.DataFrame, idx: int) -> bool:
        """Check if all entry conditions are met (AND logic)."""
        if not rule.entry_conditions:
            return False
        
        return all(self._check_condition(cond, df, idx) for cond in rule.entry_conditions)
    
    def _check_exit(self, rule: StreakRule, df: pd.DataFrame, idx: int) -> bool:
        """Check if any exit condition is met (OR logic)."""
        if not rule.exit_conditions:
            return False
        
        return any(self._check_condition(cond, df, idx) for cond in rule.exit_conditions)
    
    def _calculate_metrics(self, result: BacktestResult) -> None:
        """Calculate all performance metrics from trades."""
        if not result.trades:
            return
        
        trades = result.trades
        result.total_trades = len(trades)
        
        # Win/Loss analysis
        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl <= 0]
        
        result.winning_trades = len(winning)
        result.losing_trades = len(losing)
        result.win_rate = (result.winning_trades / result.total_trades) * 100 if result.total_trades > 0 else 0
        
        # P&L metrics
        result.total_pnl = sum(t.pnl for t in trades)
        result.total_pnl_percent = (result.total_pnl / result.config.initial_capital) * 100
        
        if winning:
            result.avg_profit = sum(t.pnl for t in winning) / len(winning)
            result.avg_profit_percent = sum(t.pnl_percent for t in winning) / len(winning)
            result.largest_profit = max(t.pnl for t in winning)
        
        if losing:
            result.avg_loss = sum(t.pnl for t in losing) / len(losing)
            result.avg_loss_percent = sum(t.pnl_percent for t in losing) / len(losing)
            result.largest_loss = min(t.pnl for t in losing)
        
        # Risk metrics
        total_profit = sum(t.pnl for t in winning) if winning else 0
        total_loss = abs(sum(t.pnl for t in losing)) if losing else 1
        result.profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
        
        if result.avg_loss != 0:
            result.risk_reward_ratio = abs(result.avg_profit / result.avg_loss)
        
        # Drawdown calculation from equity curve
        if result.equity_curve:
            equities = [e[1] for e in result.equity_curve]
            peak = equities[0]
            max_dd = 0
            max_dd_pct = 0
            
            for equity in equities:
                if equity > peak:
                    peak = equity
                dd = peak - equity
                dd_pct = (dd / peak) * 100
                if dd > max_dd:
                    max_dd = dd
                    max_dd_pct = dd_pct
            
            result.max_drawdown = max_dd
            result.max_drawdown_percent = max_dd_pct
        
        # Sharpe ratio (simplified - annualized)
        if len(trades) > 1:
            returns = [t.pnl_percent for t in trades]
            avg_return = np.mean(returns)
            std_return = np.std(returns)
            if std_return > 0:
                # Annualize assuming ~20 trades per year
                result.sharpe_ratio = (avg_return / std_return) * np.sqrt(20)
        
        # Time metrics
        holding_days = [t.holding_days for t in trades]
        result.avg_holding_days = np.mean(holding_days)
        result.max_holding_days = max(holding_days)
        
        if winning:
            result.avg_winning_days = np.mean([t.holding_days for t in winning])
        if losing:
            result.avg_losing_days = np.mean([t.holding_days for t in losing])
        
        # Exit analysis
        result.target_hits = len([t for t in trades if t.status == TradeStatus.TARGET_HIT])
        result.stop_loss_hits = len([t for t in trades if t.status == TradeStatus.STOP_LOSS_HIT])
        result.trailing_sl_hits = len([t for t in trades if t.status == TradeStatus.TRAILING_SL_HIT])
        result.exit_condition_hits = len([t for t in trades if t.status == TradeStatus.EXIT_CONDITION])
        result.max_days_exits = len([t for t in trades if t.status == TradeStatus.MAX_DAYS])
    
    def run_multi_symbol_backtest(
        self,
        rule: StreakRule,
        symbols_data: dict[str, pd.DataFrame]
    ) -> dict[str, BacktestResult]:
        """
        Run backtest on multiple symbols.
        
        Args:
            rule: Streak rule to test.
            symbols_data: Dict of symbol -> DataFrame.
        
        Returns:
            Dict of symbol -> BacktestResult.
        """
        results = {}
        for symbol, df in symbols_data.items():
            try:
                results[symbol] = self.run_backtest(rule, df, symbol)
            except Exception as e:
                print(f"Error backtesting {symbol}: {e}")
        return results
    
    def compare_rules(
        self,
        rules: list[StreakRule],
        df: pd.DataFrame,
        symbol: str = "UNKNOWN"
    ) -> pd.DataFrame:
        """
        Compare multiple rules on same data.
        
        Returns DataFrame with comparison metrics.
        """
        comparison = []
        
        for rule in rules:
            result = self.run_backtest(rule, df, symbol)
            comparison.append({
                'Rule': rule.name,
                'Trades': result.total_trades,
                'Win Rate': f"{result.win_rate:.1f}%",
                'Total P&L': f"Rs.{result.total_pnl:.0f}",
                'Return': f"{result.total_pnl_percent:.1f}%",
                'Profit Factor': f"{result.profit_factor:.2f}",
                'Max DD': f"{result.max_drawdown_percent:.1f}%",
                'Sharpe': f"{result.sharpe_ratio:.2f}",
                'Avg Days': f"{result.avg_holding_days:.1f}"
            })
        
        return pd.DataFrame(comparison)
