"""Support and Resistance level calculator."""

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.models import OHLC, SRLevel

logger = logging.getLogger(__name__)


@dataclass
class PivotLevels:
    """Classic pivot point levels."""
    pivot: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float


class SRLevelCalculator:
    """Calculator for support and resistance levels."""
    
    def __init__(
        self,
        lookback_days: int = 20,
        pivot_type: str = "standard",
        sr_threshold_percent: float = 0.5,
        min_touches: int = 2
    ):
        """
        Initialize SR calculator.
        
        Args:
            lookback_days: Days of history to analyze.
            pivot_type: Type of pivot calculation (standard, fibonacci, camarilla).
            sr_threshold_percent: Threshold to consider price levels as same zone.
            min_touches: Minimum touches to confirm a level.
        """
        self.lookback_days = lookback_days
        self.pivot_type = pivot_type
        self.sr_threshold_percent = sr_threshold_percent
        self.min_touches = min_touches
    
    def calculate_pivot_levels(
        self,
        high: float,
        low: float,
        close: float
    ) -> PivotLevels:
        """
        Calculate pivot point levels from previous day's OHLC.
        
        Args:
            high: Previous day high.
            low: Previous day low.
            close: Previous day close.
        
        Returns:
            PivotLevels object with all pivot levels.
        """
        if self.pivot_type == "fibonacci":
            return self._fibonacci_pivots(high, low, close)
        elif self.pivot_type == "camarilla":
            return self._camarilla_pivots(high, low, close)
        else:
            return self._standard_pivots(high, low, close)
    
    def _standard_pivots(self, high: float, low: float, close: float) -> PivotLevels:
        """Standard pivot calculation."""
        pivot = (high + low + close) / 3
        
        return PivotLevels(
            pivot=pivot,
            r1=(2 * pivot) - low,
            r2=pivot + (high - low),
            r3=high + 2 * (pivot - low),
            s1=(2 * pivot) - high,
            s2=pivot - (high - low),
            s3=low - 2 * (high - pivot)
        )
    
    def _fibonacci_pivots(self, high: float, low: float, close: float) -> PivotLevels:
        """Fibonacci pivot calculation."""
        pivot = (high + low + close) / 3
        range_hl = high - low
        
        return PivotLevels(
            pivot=pivot,
            r1=pivot + (0.382 * range_hl),
            r2=pivot + (0.618 * range_hl),
            r3=pivot + (1.0 * range_hl),
            s1=pivot - (0.382 * range_hl),
            s2=pivot - (0.618 * range_hl),
            s3=pivot - (1.0 * range_hl)
        )
    
    def _camarilla_pivots(self, high: float, low: float, close: float) -> PivotLevels:
        """Camarilla pivot calculation."""
        range_hl = high - low
        
        return PivotLevels(
            pivot=(high + low + close) / 3,
            r1=close + (range_hl * 1.1 / 12),
            r2=close + (range_hl * 1.1 / 6),
            r3=close + (range_hl * 1.1 / 4),
            s1=close - (range_hl * 1.1 / 12),
            s2=close - (range_hl * 1.1 / 6),
            s3=close - (range_hl * 1.1 / 4)
        )
    
    def get_previous_day_levels(self, df: pd.DataFrame) -> Dict[str, SRLevel]:
        """
        Get previous day high, low, close as SR levels.
        
        Args:
            df: DataFrame with daily OHLC data.
        
        Returns:
            Dict with PDH, PDL, PDC levels.
        """
        if df.empty or len(df) < 2:
            return {}
        
        # Get previous day's data (second last row since last is today)
        prev_day = df.iloc[-2]
        
        return {
            "pdh": SRLevel(
                price=prev_day["high"],
                level_type="pdh",
                strength=3,
                timestamp=prev_day["timestamp"]
            ),
            "pdl": SRLevel(
                price=prev_day["low"],
                level_type="pdl",
                strength=3,
                timestamp=prev_day["timestamp"]
            ),
            "pdc": SRLevel(
                price=prev_day["close"],
                level_type="pdc",
                strength=2,
                timestamp=prev_day["timestamp"]
            )
        }
    
    def calculate_opening_range(
        self,
        intraday_df: pd.DataFrame,
        orb_minutes: int = 15
    ) -> Optional[Tuple[SRLevel, SRLevel]]:
        """
        Calculate Opening Range Breakout levels.
        
        Args:
            intraday_df: Intraday OHLC data.
            orb_minutes: Minutes for opening range (15 or 30).
        
        Returns:
            Tuple of (ORB high level, ORB low level) or None.
        """
        if intraday_df.empty:
            return None
        
        # Filter for opening range candles
        market_open = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
        orb_end = market_open + timedelta(minutes=orb_minutes)
        
        # Ensure timestamp column is datetime
        intraday_df["timestamp"] = pd.to_datetime(intraday_df["timestamp"])
        
        orb_candles = intraday_df[
            (intraday_df["timestamp"] >= market_open) &
            (intraday_df["timestamp"] < orb_end)
        ]
        
        if orb_candles.empty:
            return None
        
        orb_high = orb_candles["high"].max()
        orb_low = orb_candles["low"].min()
        
        return (
            SRLevel(
                price=orb_high,
                level_type="orb_high",
                strength=4,
                timestamp=datetime.now()
            ),
            SRLevel(
                price=orb_low,
                level_type="orb_low",
                strength=4,
                timestamp=datetime.now()
            )
        )
    
    def find_swing_levels(
        self,
        df: pd.DataFrame,
        lookback: int = 5
    ) -> List[SRLevel]:
        """
        Find swing high/low levels from historical data.
        
        Args:
            df: Daily OHLC DataFrame.
            lookback: Lookback period for swing detection.
        
        Returns:
            List of SR levels from swing highs/lows.
        """
        levels = []
        
        if len(df) < lookback * 2 + 1:
            return levels
        
        highs = df["high"].values
        lows = df["low"].values
        timestamps = df["timestamp"].values
        
        # Find swing highs (local maxima)
        for i in range(lookback, len(df) - lookback):
            is_swing_high = True
            is_swing_low = True
            
            for j in range(1, lookback + 1):
                if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                    is_swing_high = False
                if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                    is_swing_low = False
            
            if is_swing_high:
                levels.append(SRLevel(
                    price=highs[i],
                    level_type="resistance",
                    strength=1,
                    timestamp=pd.Timestamp(timestamps[i]).to_pydatetime()
                ))
            
            if is_swing_low:
                levels.append(SRLevel(
                    price=lows[i],
                    level_type="support",
                    strength=1,
                    timestamp=pd.Timestamp(timestamps[i]).to_pydatetime()
                ))
        
        return levels
    
    def cluster_levels(self, levels: List[SRLevel]) -> List[SRLevel]:
        """
        Cluster nearby levels into zones and calculate strength.
        
        Args:
            levels: List of raw SR levels.
        
        Returns:
            Clustered levels with updated strength.
        """
        if not levels:
            return []
        
        # Sort by price
        sorted_levels = sorted(levels, key=lambda x: x.price)
        
        clustered = []
        current_cluster = [sorted_levels[0]]
        
        for level in sorted_levels[1:]:
            # Check if level is within threshold of current cluster
            cluster_avg = sum(l.price for l in current_cluster) / len(current_cluster)
            threshold = cluster_avg * (self.sr_threshold_percent / 100)
            
            if abs(level.price - cluster_avg) <= threshold:
                current_cluster.append(level)
            else:
                # Create clustered level
                clustered.append(self._merge_cluster(current_cluster))
                current_cluster = [level]
        
        # Don't forget the last cluster
        if current_cluster:
            clustered.append(self._merge_cluster(current_cluster))
        
        # Filter by minimum touches
        return [l for l in clustered if l.strength >= self.min_touches]
    
    def _merge_cluster(self, cluster: List[SRLevel]) -> SRLevel:
        """Merge a cluster of levels into one."""
        avg_price = sum(l.price for l in cluster) / len(cluster)
        
        # Determine level type based on majority
        types = [l.level_type for l in cluster]
        level_type = max(set(types), key=types.count)
        
        # Latest timestamp
        timestamps = [l.timestamp for l in cluster if l.timestamp]
        latest_timestamp = max(timestamps) if timestamps else None
        
        return SRLevel(
            price=avg_price,
            level_type=level_type,
            strength=len(cluster),
            timestamp=latest_timestamp
        )
    
    def calculate_all_levels(
        self,
        daily_df: pd.DataFrame,
        intraday_df: Optional[pd.DataFrame] = None,
        orb_minutes: int = 15
    ) -> Dict[str, List[SRLevel]]:
        """
        Calculate all SR levels for a symbol.
        
        Args:
            daily_df: Daily OHLC data.
            intraday_df: Intraday OHLC data for ORB.
            orb_minutes: Opening range minutes.
        
        Returns:
            Dict with categorized SR levels.
        """
        all_levels = {
            "pivot": [],
            "pdh_pdl": [],
            "orb": [],
            "swing": [],
            "all": []
        }
        
        if daily_df.empty:
            return all_levels
        
        # Previous day levels
        pdl_levels = self.get_previous_day_levels(daily_df)
        all_levels["pdh_pdl"] = list(pdl_levels.values())
        
        # Pivot levels from previous day
        if len(daily_df) >= 2:
            prev = daily_df.iloc[-2]
            pivots = self.calculate_pivot_levels(
                high=prev["high"],
                low=prev["low"],
                close=prev["close"]
            )
            
            all_levels["pivot"] = [
                SRLevel(pivots.pivot, "pivot", 3),
                SRLevel(pivots.r1, "resistance", 2),
                SRLevel(pivots.r2, "resistance", 2),
                SRLevel(pivots.r3, "resistance", 1),
                SRLevel(pivots.s1, "support", 2),
                SRLevel(pivots.s2, "support", 2),
                SRLevel(pivots.s3, "support", 1),
            ]
        
        # ORB levels
        if intraday_df is not None and not intraday_df.empty:
            orb = self.calculate_opening_range(intraday_df, orb_minutes)
            if orb:
                all_levels["orb"] = list(orb)
        
        # Swing levels
        swing_levels = self.find_swing_levels(daily_df)
        all_levels["swing"] = self.cluster_levels(swing_levels)
        
        # Combine all
        all_levels["all"] = (
            all_levels["pivot"] +
            all_levels["pdh_pdl"] +
            all_levels["orb"] +
            all_levels["swing"]
        )
        
        # Sort by price
        all_levels["all"] = sorted(all_levels["all"], key=lambda x: x.price)
        
        return all_levels
    
    def find_nearest_levels(
        self,
        price: float,
        levels: List[SRLevel],
        count: int = 2
    ) -> Tuple[List[SRLevel], List[SRLevel]]:
        """
        Find nearest support and resistance levels.
        
        Args:
            price: Current price.
            levels: List of all SR levels.
            count: Number of levels to return on each side.
        
        Returns:
            Tuple of (nearest supports, nearest resistances).
        """
        supports = [l for l in levels if l.price < price]
        resistances = [l for l in levels if l.price > price]
        
        # Sort supports descending (closest first)
        supports = sorted(supports, key=lambda x: x.price, reverse=True)[:count]
        
        # Sort resistances ascending (closest first)
        resistances = sorted(resistances, key=lambda x: x.price)[:count]
        
        return supports, resistances
    
    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """
        Calculate Average True Range.
        
        Args:
            df: OHLC DataFrame.
            period: ATR period.
        
        Returns:
            ATR value.
        """
        if len(df) < period:
            return 0.0
        
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        
        tr_list = []
        for i in range(1, len(df)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
            tr_list.append(tr)
        
        if len(tr_list) < period:
            return np.mean(tr_list) if tr_list else 0.0
        
        return np.mean(tr_list[-period:])
