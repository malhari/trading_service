"""Breakout detection engine with volume confirmation."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

from core.models import BreakoutSignal, OHLC, SignalType, SRLevel, Tick
from strategies.sr_levels import SRLevelCalculator

logger = logging.getLogger(__name__)


@dataclass
class BreakoutCandidate:
    """A potential breakout being monitored."""
    symbol: str
    sr_level: SRLevel
    direction: str  # 'long' or 'short'
    approach_price: float
    approach_time: datetime
    is_confirmed: bool = False
    confirmation_candle: Optional[OHLC] = None


class BreakoutDetector:
    """Detects breakout signals with volume confirmation."""
    
    def __init__(
        self,
        volume_surge_multiplier: float = 1.5,
        breakout_threshold_percent: float = 0.2,
        confirmation_candles: int = 1,
        min_risk_reward: float = 2.0,
        sl_buffer_percent: float = 0.1
    ):
        """
        Initialize breakout detector.
        
        Args:
            volume_surge_multiplier: Minimum volume ratio vs average for confirmation.
            breakout_threshold_percent: Minimum % above/below level for valid breakout.
            confirmation_candles: Candles to wait for confirmation.
            min_risk_reward: Minimum risk-reward ratio for valid signal.
            sl_buffer_percent: Buffer below/above SR level for stop loss.
        """
        self.volume_surge_multiplier = volume_surge_multiplier
        self.breakout_threshold_percent = breakout_threshold_percent
        self.confirmation_candles = confirmation_candles
        self.min_risk_reward = min_risk_reward
        self.sl_buffer_percent = sl_buffer_percent
        
        # Track candidates being monitored
        self._candidates: Dict[str, List[BreakoutCandidate]] = {}
        
        # Volume averages per symbol
        self._avg_volumes: Dict[str, float] = {}
    
    def set_average_volume(self, symbol: str, avg_volume: float):
        """Set average volume for a symbol (calculated from historical data)."""
        self._avg_volumes[symbol] = avg_volume
    
    def calculate_average_volume(self, df: pd.DataFrame, period: int = 20) -> float:
        """Calculate average volume from historical data."""
        if len(df) < period:
            return df["volume"].mean() if not df.empty else 0
        return df["volume"].tail(period).mean()
    
    def check_approaching_level(
        self,
        tick: Tick,
        sr_levels: List[SRLevel],
        approach_threshold_percent: float = 1.0
    ) -> List[BreakoutCandidate]:
        """
        Check if price is approaching any SR level.
        
        Args:
            tick: Current tick data.
            sr_levels: List of SR levels to monitor.
            approach_threshold_percent: Distance threshold to consider approaching.
        
        Returns:
            List of new breakout candidates.
        """
        new_candidates = []
        price = tick.last_price
        
        for level in sr_levels:
            distance_percent = abs(price - level.price) / level.price * 100
            
            if distance_percent <= approach_threshold_percent:
                direction = "long" if price < level.price else "short"
                
                # Check if we're already tracking this
                existing = self._get_candidate(tick.symbol, level, direction)
                if existing is None:
                    candidate = BreakoutCandidate(
                        symbol=tick.symbol,
                        sr_level=level,
                        direction=direction,
                        approach_price=price,
                        approach_time=tick.timestamp
                    )
                    
                    if tick.symbol not in self._candidates:
                        self._candidates[tick.symbol] = []
                    self._candidates[tick.symbol].append(candidate)
                    
                    new_candidates.append(candidate)
                    logger.debug(
                        f"New breakout candidate: {tick.symbol} approaching "
                        f"{level.level_type} at {level.price:.2f}"
                    )
        
        return new_candidates
    
    def _get_candidate(
        self,
        symbol: str,
        level: SRLevel,
        direction: str
    ) -> Optional[BreakoutCandidate]:
        """Get existing candidate if tracking."""
        if symbol not in self._candidates:
            return None
        
        for candidate in self._candidates[symbol]:
            if (candidate.sr_level.price == level.price and 
                candidate.direction == direction):
                return candidate
        
        return None
    
    def check_breakout(
        self,
        candle: OHLC,
        sr_levels: List[SRLevel],
        current_volume: int
    ) -> Optional[BreakoutSignal]:
        """
        Check if a candle confirms a breakout.
        
        Args:
            candle: Completed OHLC candle.
            sr_levels: SR levels to check against.
            current_volume: Volume of the candle.
        
        Returns:
            BreakoutSignal if confirmed, None otherwise.
        """
        symbol = candle.symbol
        avg_volume = self._avg_volumes.get(symbol, 0)
        
        if avg_volume == 0:
            logger.warning(f"No average volume for {symbol}")
            return None
        
        volume_ratio = current_volume / avg_volume
        
        for level in sr_levels:
            breakout_threshold = level.price * (self.breakout_threshold_percent / 100)
            
            # Check for bullish breakout (resistance break)
            if candle.close > level.price + breakout_threshold:
                if level.level_type in ["resistance", "pdh", "orb_high", "pivot"]:
                    # Verify volume surge
                    if volume_ratio >= self.volume_surge_multiplier:
                        signal = self._create_signal(
                            candle=candle,
                            level=level,
                            direction="long",
                            volume_ratio=volume_ratio
                        )
                        if signal and signal.risk_reward_ratio >= self.min_risk_reward:
                            logger.info(
                                f"Bullish breakout: {symbol} closed above "
                                f"{level.level_type} at {level.price:.2f}"
                            )
                            return signal
            
            # Check for bearish breakout (support break)
            elif candle.close < level.price - breakout_threshold:
                if level.level_type in ["support", "pdl", "orb_low", "pivot"]:
                    if volume_ratio >= self.volume_surge_multiplier:
                        signal = self._create_signal(
                            candle=candle,
                            level=level,
                            direction="short",
                            volume_ratio=volume_ratio
                        )
                        if signal and signal.risk_reward_ratio >= self.min_risk_reward:
                            logger.info(
                                f"Bearish breakout: {symbol} closed below "
                                f"{level.level_type} at {level.price:.2f}"
                            )
                            return signal
        
        return None
    
    def _create_signal(
        self,
        candle: OHLC,
        level: SRLevel,
        direction: str,
        volume_ratio: float
    ) -> Optional[BreakoutSignal]:
        """Create a breakout signal with entry, SL, and target."""
        entry_price = candle.close
        
        # Calculate stop loss with buffer
        sl_buffer = level.price * (self.sl_buffer_percent / 100)
        
        if direction == "long":
            # For long, SL below the broken resistance (now support)
            stop_loss = level.price - sl_buffer
            
            # Target based on risk-reward
            risk = entry_price - stop_loss
            target = entry_price + (risk * self.min_risk_reward)
            
            signal_type = self._get_signal_type(level, "long")
        else:
            # For short, SL above the broken support (now resistance)
            stop_loss = level.price + sl_buffer
            
            risk = stop_loss - entry_price
            target = entry_price - (risk * self.min_risk_reward)
            
            signal_type = self._get_signal_type(level, "short")
        
        # Confidence based on volume ratio and level strength
        confidence = min(1.0, (volume_ratio / 3) * 0.5 + (level.strength / 5) * 0.5)
        
        return BreakoutSignal(
            symbol=candle.symbol,
            signal_type=signal_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            sr_level=level,
            volume_ratio=volume_ratio,
            timestamp=candle.timestamp,
            confidence=confidence
        )
    
    def _get_signal_type(self, level: SRLevel, direction: str) -> SignalType:
        """Determine signal type based on level and direction."""
        if level.level_type in ["orb_high", "orb_low"]:
            return SignalType.ORB_LONG if direction == "long" else SignalType.ORB_SHORT
        return SignalType.BREAKOUT_LONG if direction == "long" else SignalType.BREAKOUT_SHORT
    
    def check_false_breakout(
        self,
        candle: OHLC,
        signal: BreakoutSignal,
        confirmation_period: int = 2
    ) -> bool:
        """
        Check if a breakout signal has become a false breakout.
        
        Args:
            candle: Latest candle.
            signal: The breakout signal to check.
            confirmation_period: Candles since breakout.
        
        Returns:
            True if false breakout detected.
        """
        level_price = signal.sr_level.price
        
        if signal.signal_type in [SignalType.BREAKOUT_LONG, SignalType.ORB_LONG]:
            # Long breakout fails if price closes back below level
            if candle.close < level_price:
                logger.warning(
                    f"False breakout detected: {candle.symbol} closed back below "
                    f"{level_price:.2f}"
                )
                return True
        else:
            # Short breakout fails if price closes back above level
            if candle.close > level_price:
                logger.warning(
                    f"False breakout detected: {candle.symbol} closed back above "
                    f"{level_price:.2f}"
                )
                return True
        
        return False
    
    def check_retest_entry(
        self,
        tick: Tick,
        signal: BreakoutSignal,
        retest_buffer_percent: float = 0.3
    ) -> bool:
        """
        Check if price is retesting the breakout level (better entry).
        
        Args:
            tick: Current tick.
            signal: Original breakout signal.
            retest_buffer_percent: Buffer for retest zone.
        
        Returns:
            True if in retest zone.
        """
        level_price = signal.sr_level.price
        buffer = level_price * (retest_buffer_percent / 100)
        
        if signal.signal_type in [SignalType.BREAKOUT_LONG, SignalType.ORB_LONG]:
            # For long, retest zone is just above the broken level
            return level_price <= tick.last_price <= level_price + buffer
        else:
            # For short, retest zone is just below the broken level
            return level_price - buffer <= tick.last_price <= level_price
    
    def scan_for_breakouts(
        self,
        symbol: str,
        current_candle: OHLC,
        sr_levels: List[SRLevel],
        volume: int
    ) -> Optional[BreakoutSignal]:
        """
        Main scanning method to detect breakouts.
        
        Args:
            symbol: Trading symbol.
            current_candle: Current/latest candle.
            sr_levels: SR levels for the symbol.
            volume: Current candle volume.
        
        Returns:
            BreakoutSignal if found, None otherwise.
        """
        # Check for breakout
        signal = self.check_breakout(current_candle, sr_levels, volume)
        
        if signal:
            # Remove from candidates
            self._clear_candidates(symbol)
            return signal
        
        return None
    
    def _clear_candidates(self, symbol: str):
        """Clear all candidates for a symbol."""
        if symbol in self._candidates:
            self._candidates[symbol] = []
    
    def get_active_candidates(self, symbol: Optional[str] = None) -> List[BreakoutCandidate]:
        """Get active breakout candidates."""
        if symbol:
            return self._candidates.get(symbol, [])
        
        all_candidates = []
        for candidates in self._candidates.values():
            all_candidates.extend(candidates)
        return all_candidates


class MultiSymbolBreakoutScanner:
    """Scan multiple symbols for breakout opportunities."""
    
    def __init__(
        self,
        sr_calculator: SRLevelCalculator,
        detector: BreakoutDetector
    ):
        self.sr_calculator = sr_calculator
        self.detector = detector
        
        # Cache SR levels per symbol
        self._sr_cache: Dict[str, Dict[str, List[SRLevel]]] = {}
        self._cache_timestamp: Dict[str, datetime] = {}
        self._cache_ttl_minutes: int = 30
    
    def update_sr_levels(
        self,
        symbol: str,
        daily_df: pd.DataFrame,
        intraday_df: Optional[pd.DataFrame] = None
    ):
        """Update SR levels cache for a symbol."""
        levels = self.sr_calculator.calculate_all_levels(
            daily_df=daily_df,
            intraday_df=intraday_df
        )
        
        self._sr_cache[symbol] = levels
        self._cache_timestamp[symbol] = datetime.now()
        
        # Update average volume
        avg_vol = self.detector.calculate_average_volume(daily_df)
        self.detector.set_average_volume(symbol, avg_vol)
        
        logger.info(f"Updated SR levels for {symbol}: {len(levels['all'])} levels")
    
    def get_sr_levels(self, symbol: str) -> List[SRLevel]:
        """Get cached SR levels for a symbol."""
        if symbol not in self._sr_cache:
            return []
        
        # Check cache freshness
        cached_time = self._cache_timestamp.get(symbol)
        if cached_time:
            age = (datetime.now() - cached_time).total_seconds() / 60
            if age > self._cache_ttl_minutes:
                logger.debug(f"SR cache stale for {symbol}")
        
        return self._sr_cache[symbol].get("all", [])
    
    def scan_all(
        self,
        candles: Dict[str, OHLC],
        volumes: Dict[str, int]
    ) -> List[BreakoutSignal]:
        """
        Scan all symbols for breakout signals.
        
        Args:
            candles: Dict of symbol -> latest candle.
            volumes: Dict of symbol -> current volume.
        
        Returns:
            List of breakout signals.
        """
        signals = []
        
        for symbol, candle in candles.items():
            sr_levels = self.get_sr_levels(symbol)
            volume = volumes.get(symbol, 0)
            
            if not sr_levels or volume == 0:
                continue
            
            signal = self.detector.scan_for_breakouts(
                symbol=symbol,
                current_candle=candle,
                sr_levels=sr_levels,
                volume=volume
            )
            
            if signal:
                signals.append(signal)
        
        return signals
