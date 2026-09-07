"""Swing trading support/resistance and trend analysis."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.models import SRLevel
from strategies.sr_levels import SRLevelCalculator, PivotLevels

logger = logging.getLogger(__name__)


class TrendDirection:
    """Trend direction constants."""
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    SIDEWAYS = "sideways"


@dataclass
class TrendAnalysis:
    """Trend analysis result."""
    direction: str
    strength: float  # 0 to 1
    ema_short: float
    ema_long: float
    price_vs_ema: str  # 'above', 'below', 'at'
    higher_highs: int
    higher_lows: int
    lower_highs: int
    lower_lows: int
    atr: float
    atr_percent: float


@dataclass
class ConsolidationZone:
    """Price consolidation zone."""
    high: float
    low: float
    start_date: datetime
    end_date: datetime
    days: int
    range_percent: float
    breakout_direction: Optional[str] = None


class SwingLevelCalculator(SRLevelCalculator):
    """Extended S/R calculator for swing trading."""
    
    def __init__(
        self,
        lookback_days: int = 60,
        pivot_type: str = "fibonacci",
        sr_threshold_percent: float = 1.0,
        min_touches: int = 2,
        ema_short: int = 20,
        ema_long: int = 50
    ):
        super().__init__(
            lookback_days=lookback_days,
            pivot_type=pivot_type,
            sr_threshold_percent=sr_threshold_percent,
            min_touches=min_touches
        )
        self.ema_short = ema_short
        self.ema_long = ema_long
    
    def calculate_weekly_pivots(
        self,
        weekly_df: pd.DataFrame
    ) -> Optional[PivotLevels]:
        """
        Calculate weekly pivot points.
        
        Args:
            weekly_df: Weekly OHLC data.
        
        Returns:
            PivotLevels from last week's data.
        """
        if weekly_df.empty or len(weekly_df) < 2:
            return None
        
        # Use previous week's data
        prev_week = weekly_df.iloc[-2]
        
        return self.calculate_pivot_levels(
            high=prev_week["high"],
            low=prev_week["low"],
            close=prev_week["close"]
        )
    
    def calculate_monthly_pivots(
        self,
        monthly_df: pd.DataFrame
    ) -> Optional[PivotLevels]:
        """Calculate monthly pivot points."""
        if monthly_df.empty or len(monthly_df) < 2:
            return None
        
        prev_month = monthly_df.iloc[-2]
        
        return self.calculate_pivot_levels(
            high=prev_month["high"],
            low=prev_month["low"],
            close=prev_month["close"]
        )
    
    def resample_to_weekly(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """Resample daily data to weekly."""
        if daily_df.empty:
            return pd.DataFrame()
        
        df = daily_df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)
        
        weekly = df.resample("W").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna()
        
        weekly.reset_index(inplace=True)
        return weekly
    
    def resample_to_monthly(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """Resample daily data to monthly."""
        if daily_df.empty:
            return pd.DataFrame()
        
        df = daily_df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)
        
        monthly = df.resample("ME").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna()
        
        monthly.reset_index(inplace=True)
        return monthly
    
    def calculate_ema(self, df: pd.DataFrame, period: int) -> pd.Series:
        """Calculate Exponential Moving Average."""
        return df["close"].ewm(span=period, adjust=False).mean()
    
    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Calculate Relative Strength Index (RSI).
        
        Args:
            df: DataFrame with 'close' column.
            period: RSI period (default 14).
        
        Returns:
            RSI series (0-100).
        """
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_macd(
        self, 
        df: pd.DataFrame, 
        fast: int = 12, 
        slow: int = 26, 
        signal: int = 9
    ) -> dict:
        """
        Calculate MACD (Moving Average Convergence Divergence).
        
        Args:
            df: DataFrame with 'close' column.
            fast: Fast EMA period (default 12).
            slow: Slow EMA period (default 26).
            signal: Signal line period (default 9).
        
        Returns:
            Dict with 'macd', 'signal', 'histogram' series.
        """
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        
        return {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": histogram
        }
    
    def get_indicator_signals(self, df: pd.DataFrame) -> dict:
        """
        Get trading signals from multiple indicators.
        
        Args:
            df: Daily OHLC DataFrame.
        
        Returns:
            Dict with indicator values and signals.
        """
        if len(df) < 50:
            return {"error": "Insufficient data"}
        
        # Calculate indicators
        rsi = self.calculate_rsi(df, 14)
        macd = self.calculate_macd(df)
        ema_21 = self.calculate_ema(df, 21)
        ema_50 = self.calculate_ema(df, 50)
        
        current_price = df.iloc[-1]["close"]
        current_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]
        current_macd = macd["macd"].iloc[-1]
        current_signal = macd["signal"].iloc[-1]
        prev_macd = macd["macd"].iloc[-2]
        prev_signal = macd["signal"].iloc[-2]
        current_histogram = macd["histogram"].iloc[-1]
        current_ema_21 = ema_21.iloc[-1]
        current_ema_50 = ema_50.iloc[-1]
        
        # RSI signals
        rsi_signal = "neutral"
        if current_rsi < 30:
            rsi_signal = "oversold"
        elif current_rsi > 70:
            rsi_signal = "overbought"
        elif current_rsi < 40 and current_rsi > prev_rsi:
            rsi_signal = "recovering_from_oversold"
        elif current_rsi > 60 and current_rsi < prev_rsi:
            rsi_signal = "weakening_from_overbought"
        
        # MACD signals
        macd_signal = "neutral"
        macd_crossover = False
        if current_macd > current_signal and prev_macd <= prev_signal:
            macd_signal = "bullish_crossover"
            macd_crossover = True
        elif current_macd < current_signal and prev_macd >= prev_signal:
            macd_signal = "bearish_crossover"
            macd_crossover = True
        elif current_macd > current_signal:
            macd_signal = "bullish"
        elif current_macd < current_signal:
            macd_signal = "bearish"
        
        # EMA signals
        ema_signal = "neutral"
        if current_price > current_ema_21 > current_ema_50:
            ema_signal = "strong_uptrend"
        elif current_price < current_ema_21 < current_ema_50:
            ema_signal = "strong_downtrend"
        elif current_ema_21 > current_ema_50:
            ema_signal = "uptrend"
        elif current_ema_21 < current_ema_50:
            ema_signal = "downtrend"
        
        # Combined signal strength
        bullish_count = 0
        bearish_count = 0
        
        if rsi_signal in ["oversold", "recovering_from_oversold"]:
            bullish_count += 1
        elif rsi_signal in ["overbought", "weakening_from_overbought"]:
            bearish_count += 1
        
        if macd_signal in ["bullish", "bullish_crossover"]:
            bullish_count += 1
        elif macd_signal in ["bearish", "bearish_crossover"]:
            bearish_count += 1
        
        if ema_signal in ["uptrend", "strong_uptrend"]:
            bullish_count += 1
        elif ema_signal in ["downtrend", "strong_downtrend"]:
            bearish_count += 1
        
        overall_signal = "neutral"
        if bullish_count >= 2:
            overall_signal = "bullish"
        elif bearish_count >= 2:
            overall_signal = "bearish"
        
        return {
            "rsi": {
                "value": round(current_rsi, 2),
                "signal": rsi_signal
            },
            "macd": {
                "macd": round(current_macd, 2),
                "signal_line": round(current_signal, 2),
                "histogram": round(current_histogram, 2),
                "signal": macd_signal,
                "crossover": macd_crossover
            },
            "ema": {
                "ema_21": round(current_ema_21, 2),
                "ema_50": round(current_ema_50, 2),
                "signal": ema_signal
            },
            "price": round(current_price, 2),
            "overall_signal": overall_signal,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count
        }
    
    def analyze_trend(self, df: pd.DataFrame) -> TrendAnalysis:
        """
        Analyze the trend using EMAs and price structure.
        
        Args:
            df: Daily OHLC DataFrame.
        
        Returns:
            TrendAnalysis with direction and strength.
        """
        if len(df) < self.ema_long:
            return TrendAnalysis(
                direction=TrendDirection.SIDEWAYS,
                strength=0.0,
                ema_short=0,
                ema_long=0,
                price_vs_ema="at",
                higher_highs=0,
                higher_lows=0,
                lower_highs=0,
                lower_lows=0,
                atr=0,
                atr_percent=0
            )
        
        # Calculate EMAs
        ema_short = self.calculate_ema(df, self.ema_short)
        ema_long = self.calculate_ema(df, self.ema_long)
        
        current_price = df.iloc[-1]["close"]
        current_ema_short = ema_short.iloc[-1]
        current_ema_long = ema_long.iloc[-1]
        
        # Price position relative to EMAs
        if current_price > current_ema_short > current_ema_long:
            price_vs_ema = "above"
        elif current_price < current_ema_short < current_ema_long:
            price_vs_ema = "below"
        else:
            price_vs_ema = "at"
        
        # Count swing highs/lows pattern
        highs = df["high"].values
        lows = df["low"].values
        
        higher_highs = 0
        higher_lows = 0
        lower_highs = 0
        lower_lows = 0
        
        # Analyze last 10 swings
        swing_lookback = min(20, len(df) - 1)
        for i in range(swing_lookback - 1):
            idx = -(i + 2)
            if highs[idx + 1] > highs[idx]:
                higher_highs += 1
            else:
                lower_highs += 1
            
            if lows[idx + 1] > lows[idx]:
                higher_lows += 1
            else:
                lower_lows += 1
        
        # Calculate ATR
        atr = self.calculate_atr(df, self.lookback_days)
        atr_percent = (atr / current_price) * 100 if current_price > 0 else 0
        
        # Determine trend direction
        if current_ema_short > current_ema_long and price_vs_ema == "above":
            direction = TrendDirection.UPTREND
            strength = min(1.0, (higher_highs + higher_lows) / (swing_lookback * 2))
        elif current_ema_short < current_ema_long and price_vs_ema == "below":
            direction = TrendDirection.DOWNTREND
            strength = min(1.0, (lower_highs + lower_lows) / (swing_lookback * 2))
        else:
            direction = TrendDirection.SIDEWAYS
            strength = 0.3
        
        return TrendAnalysis(
            direction=direction,
            strength=strength,
            ema_short=current_ema_short,
            ema_long=current_ema_long,
            price_vs_ema=price_vs_ema,
            higher_highs=higher_highs,
            higher_lows=higher_lows,
            lower_highs=lower_highs,
            lower_lows=lower_lows,
            atr=atr,
            atr_percent=atr_percent
        )
    
    def find_consolidation_zones(
        self,
        df: pd.DataFrame,
        min_days: int = 5,
        max_range_percent: float = 8.0
    ) -> List[ConsolidationZone]:
        """
        Find price consolidation zones (bases).
        
        Args:
            df: Daily OHLC DataFrame.
            min_days: Minimum days for consolidation.
            max_range_percent: Maximum range to be considered consolidation.
        
        Returns:
            List of consolidation zones.
        """
        zones = []
        
        if len(df) < min_days:
            return zones
        
        # Sliding window to find consolidations
        for i in range(len(df) - min_days):
            window = df.iloc[i:i + min_days]
            
            window_high = window["high"].max()
            window_low = window["low"].min()
            range_percent = ((window_high - window_low) / window_low) * 100
            
            if range_percent <= max_range_percent:
                # Extend window if consolidation continues
                end_idx = i + min_days
                while end_idx < len(df):
                    next_candle = df.iloc[end_idx]
                    extended_high = max(window_high, next_candle["high"])
                    extended_low = min(window_low, next_candle["low"])
                    extended_range = ((extended_high - extended_low) / extended_low) * 100
                    
                    if extended_range <= max_range_percent * 1.2:
                        window_high = extended_high
                        window_low = extended_low
                        end_idx += 1
                    else:
                        break
                
                zone = ConsolidationZone(
                    high=window_high,
                    low=window_low,
                    start_date=df.iloc[i]["timestamp"],
                    end_date=df.iloc[min(end_idx - 1, len(df) - 1)]["timestamp"],
                    days=end_idx - i,
                    range_percent=((window_high - window_low) / window_low) * 100
                )
                
                zones.append(zone)
        
        # Remove overlapping zones, keep longest
        zones = self._merge_overlapping_zones(zones)
        
        return zones
    
    def _merge_overlapping_zones(
        self,
        zones: List[ConsolidationZone]
    ) -> List[ConsolidationZone]:
        """Merge overlapping consolidation zones."""
        if not zones:
            return []
        
        # Sort by start date
        zones = sorted(zones, key=lambda z: z.start_date)
        
        merged = [zones[0]]
        for zone in zones[1:]:
            last = merged[-1]
            
            # Check overlap
            if zone.start_date <= last.end_date:
                # Merge if overlapping
                if zone.days > last.days:
                    merged[-1] = zone
            else:
                merged.append(zone)
        
        return merged
    
    def find_52_week_levels(self, df: pd.DataFrame) -> Dict[str, SRLevel]:
        """Find 52-week high and low levels."""
        if len(df) < 252:  # ~52 weeks
            # Use available data
            period = len(df)
        else:
            period = 252
        
        recent_df = df.tail(period)
        
        high_52w = recent_df["high"].max()
        low_52w = recent_df["low"].min()
        
        return {
            "52w_high": SRLevel(
                price=high_52w,
                level_type="resistance",
                strength=5,
                timestamp=datetime.now()
            ),
            "52w_low": SRLevel(
                price=low_52w,
                level_type="support",
                strength=5,
                timestamp=datetime.now()
            )
        }
    
    def calculate_all_swing_levels(
        self,
        daily_df: pd.DataFrame,
        include_weekly: bool = True,
        include_monthly: bool = False
    ) -> Dict[str, List[SRLevel]]:
        """
        Calculate all S/R levels for swing trading.
        
        Args:
            daily_df: Daily OHLC data.
            include_weekly: Include weekly pivot levels.
            include_monthly: Include monthly pivot levels.
        
        Returns:
            Dict with categorized SR levels.
        """
        all_levels = {
            "daily_pivot": [],
            "weekly_pivot": [],
            "monthly_pivot": [],
            "52_week": [],
            "swing": [],
            "consolidation": [],
            "all": []
        }
        
        if daily_df.empty:
            return all_levels
        
        # Daily pivots (from parent class)
        if len(daily_df) >= 2:
            prev = daily_df.iloc[-2]
            pivots = self.calculate_pivot_levels(
                high=prev["high"],
                low=prev["low"],
                close=prev["close"]
            )
            
            all_levels["daily_pivot"] = [
                SRLevel(pivots.pivot, "pivot", 2),
                SRLevel(pivots.r1, "resistance", 2),
                SRLevel(pivots.r2, "resistance", 1),
                SRLevel(pivots.s1, "support", 2),
                SRLevel(pivots.s2, "support", 1),
            ]
        
        # Weekly pivots
        if include_weekly:
            weekly_df = self.resample_to_weekly(daily_df)
            weekly_pivots = self.calculate_weekly_pivots(weekly_df)
            
            if weekly_pivots:
                all_levels["weekly_pivot"] = [
                    SRLevel(weekly_pivots.pivot, "pivot", 3),
                    SRLevel(weekly_pivots.r1, "resistance", 3),
                    SRLevel(weekly_pivots.r2, "resistance", 2),
                    SRLevel(weekly_pivots.r3, "resistance", 1),
                    SRLevel(weekly_pivots.s1, "support", 3),
                    SRLevel(weekly_pivots.s2, "support", 2),
                    SRLevel(weekly_pivots.s3, "support", 1),
                ]
        
        # Monthly pivots
        if include_monthly:
            monthly_df = self.resample_to_monthly(daily_df)
            monthly_pivots = self.calculate_monthly_pivots(monthly_df)
            
            if monthly_pivots:
                all_levels["monthly_pivot"] = [
                    SRLevel(monthly_pivots.pivot, "pivot", 4),
                    SRLevel(monthly_pivots.r1, "resistance", 3),
                    SRLevel(monthly_pivots.r2, "resistance", 2),
                    SRLevel(monthly_pivots.s1, "support", 3),
                    SRLevel(monthly_pivots.s2, "support", 2),
                ]
        
        # 52-week levels
        levels_52w = self.find_52_week_levels(daily_df)
        all_levels["52_week"] = list(levels_52w.values())
        
        # Swing levels (with longer lookback)
        swing_levels = self.find_swing_levels(daily_df, lookback=10)
        all_levels["swing"] = self.cluster_levels(swing_levels)
        
        # Consolidation zone boundaries
        consolidations = self.find_consolidation_zones(daily_df)
        for zone in consolidations[-3:]:  # Last 3 consolidations
            all_levels["consolidation"].extend([
                SRLevel(zone.high, "resistance", 4),
                SRLevel(zone.low, "support", 4)
            ])
        
        # Combine all
        all_levels["all"] = (
            all_levels["daily_pivot"] +
            all_levels["weekly_pivot"] +
            all_levels["monthly_pivot"] +
            all_levels["52_week"] +
            all_levels["swing"] +
            all_levels["consolidation"]
        )
        
        # Remove duplicates and sort
        all_levels["all"] = self.cluster_levels(all_levels["all"])
        all_levels["all"] = sorted(all_levels["all"], key=lambda x: x.price)
        
        return all_levels
    
    def get_key_levels(
        self,
        current_price: float,
        all_levels: List[SRLevel],
        count: int = 3
    ) -> Tuple[List[SRLevel], List[SRLevel]]:
        """
        Get the most important levels near current price.
        
        Args:
            current_price: Current stock price.
            all_levels: All calculated levels.
            count: Number of levels to return on each side.
        
        Returns:
            Tuple of (key supports, key resistances).
        """
        # Sort by strength and proximity
        supports = [l for l in all_levels if l.price < current_price]
        resistances = [l for l in all_levels if l.price > current_price]
        
        # Score by strength and proximity
        def score_level(level: SRLevel, price: float) -> float:
            distance = abs(level.price - price) / price
            return level.strength / (1 + distance * 10)
        
        supports = sorted(
            supports,
            key=lambda l: score_level(l, current_price),
            reverse=True
        )[:count]
        
        resistances = sorted(
            resistances,
            key=lambda l: score_level(l, current_price),
            reverse=True
        )[:count]
        
        return supports, resistances
