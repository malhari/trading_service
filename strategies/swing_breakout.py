"""Swing trading breakout detection on daily timeframes."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.models import BreakoutSignal, OHLC, SignalType, SRLevel
from strategies.swing_levels import (
    SwingLevelCalculator, TrendAnalysis, TrendDirection, ConsolidationZone
)

logger = logging.getLogger(__name__)


class SwingSignalType:
    """Swing-specific signal types."""
    TREND_CONTINUATION = "TREND_CONTINUATION"
    BREAKOUT_LONG = "BREAKOUT_LONG"
    BREAKOUT_SHORT = "BREAKOUT_SHORT"
    PULLBACK_BUY = "PULLBACK_BUY"
    PULLBACK_SELL = "PULLBACK_SELL"
    CONSOLIDATION_BREAKOUT = "CONSOLIDATION_BREAKOUT"
    RANGE_BREAKOUT = "RANGE_BREAKOUT"


@dataclass
class SwingSignal:
    """Swing trading signal."""
    symbol: str
    signal_type: str
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    target_3: float
    sr_level: SRLevel
    trend: TrendAnalysis
    volume_ratio: float
    atr: float
    consolidation_days: int
    timestamp: datetime
    confidence: float = 0.0
    holding_days_estimate: int = 5
    
    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.stop_loss)
    
    @property
    def reward_1(self) -> float:
        return abs(self.target_1 - self.entry_price)
    
    @property
    def risk_reward_1(self) -> float:
        return self.reward_1 / self.risk if self.risk > 0 else 0
    
    @property
    def risk_reward_2(self) -> float:
        reward = abs(self.target_2 - self.entry_price)
        return reward / self.risk if self.risk > 0 else 0


class SwingBreakoutDetector:
    """Detects swing trading breakout opportunities on daily charts."""
    
    def __init__(
        self,
        volume_surge_multiplier: float = 1.3,
        min_risk_reward: float = 2.5,
        atr_multiplier_sl: float = 2.0,
        consolidation_min_days: int = 5,
        breakout_confirmation_days: int = 1
    ):
        """
        Initialize swing breakout detector.
        
        Args:
            volume_surge_multiplier: Minimum volume vs 20-day average.
            min_risk_reward: Minimum risk-reward for signals.
            atr_multiplier_sl: ATR multiplier for stop loss.
            consolidation_min_days: Minimum days for consolidation pattern.
            breakout_confirmation_days: Days to confirm breakout.
        """
        self.volume_surge_multiplier = volume_surge_multiplier
        self.min_risk_reward = min_risk_reward
        self.atr_multiplier_sl = atr_multiplier_sl
        self.consolidation_min_days = consolidation_min_days
        self.breakout_confirmation_days = breakout_confirmation_days
        
        self._avg_volumes: Dict[str, float] = {}
    
    def set_average_volume(self, symbol: str, avg_volume: float):
        """Set 20-day average volume for a symbol."""
        self._avg_volumes[symbol] = avg_volume
    
    def calculate_average_volume(self, df: pd.DataFrame, period: int = 20) -> float:
        """Calculate average volume from historical data."""
        if len(df) < period:
            return df["volume"].mean() if not df.empty else 0
        return df["volume"].tail(period).mean()
    
    def detect_breakout(
        self,
        symbol: str,
        df: pd.DataFrame,
        sr_levels: List[SRLevel],
        trend: TrendAnalysis,
        consolidation: Optional[ConsolidationZone] = None
    ) -> Optional[SwingSignal]:
        """
        Detect swing breakout signal from daily data.
        
        Args:
            symbol: Trading symbol.
            df: Daily OHLC DataFrame.
            sr_levels: S/R levels for the symbol.
            trend: Trend analysis result.
            consolidation: Recent consolidation zone if any.
        
        Returns:
            SwingSignal if breakout detected, None otherwise.
        """
        if len(df) < 5:
            return None
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        avg_volume = self._avg_volumes.get(symbol, 0)
        if avg_volume == 0:
            avg_volume = self.calculate_average_volume(df)
            self._avg_volumes[symbol] = avg_volume
        
        volume_ratio = current["volume"] / avg_volume if avg_volume > 0 else 0
        
        # Check for breakout above resistance
        for level in sr_levels:
            if level.level_type in ["resistance", "52w_high"]:
                signal = self._check_resistance_breakout(
                    symbol=symbol,
                    current=current,
                    prev=prev,
                    level=level,
                    trend=trend,
                    volume_ratio=volume_ratio,
                    consolidation=consolidation
                )
                if signal:
                    return signal
            
            elif level.level_type in ["support", "52w_low"]:
                signal = self._check_support_breakdown(
                    symbol=symbol,
                    current=current,
                    prev=prev,
                    level=level,
                    trend=trend,
                    volume_ratio=volume_ratio,
                    consolidation=consolidation
                )
                if signal:
                    return signal
        
        # Check for pullback entries in trend
        if trend.direction == TrendDirection.UPTREND and trend.strength > 0.5:
            signal = self._check_pullback_buy(
                symbol=symbol,
                df=df,
                trend=trend,
                sr_levels=sr_levels
            )
            if signal:
                return signal
        
        elif trend.direction == TrendDirection.DOWNTREND and trend.strength > 0.5:
            signal = self._check_pullback_sell(
                symbol=symbol,
                df=df,
                trend=trend,
                sr_levels=sr_levels
            )
            if signal:
                return signal
        
        return None
    
    def _check_resistance_breakout(
        self,
        symbol: str,
        current: pd.Series,
        prev: pd.Series,
        level: SRLevel,
        trend: TrendAnalysis,
        volume_ratio: float,
        consolidation: Optional[ConsolidationZone]
    ) -> Optional[SwingSignal]:
        """Check for breakout above resistance."""
        # Price must close above resistance
        if current["close"] <= level.price:
            return None
        
        # Previous close should be at or below level
        if prev["close"] > level.price * 1.02:  # 2% buffer
            return None
        
        # Volume confirmation
        if volume_ratio < self.volume_surge_multiplier:
            logger.debug(f"{symbol}: Breakout without volume ({volume_ratio:.2f}x)")
            return None
        
        # Trend alignment preferred
        trend_bonus = 0.2 if trend.direction == TrendDirection.UPTREND else 0
        
        # Calculate targets and stop loss
        entry = current["close"]
        atr = trend.atr
        
        # Stop loss below the broken resistance (now support)
        stop_loss = level.price - (atr * 0.5)
        
        # Multiple targets based on ATR
        target_1 = entry + (atr * 2)
        target_2 = entry + (atr * 3)
        target_3 = entry + (atr * 5)
        
        risk = entry - stop_loss
        reward = target_1 - entry
        
        if risk <= 0 or reward / risk < self.min_risk_reward:
            return None
        
        # Confidence scoring
        confidence = 0.5
        confidence += trend_bonus
        confidence += min(0.2, (volume_ratio - 1) * 0.1)
        confidence += min(0.1, level.strength * 0.02)
        
        # Consolidation bonus
        consolidation_days = 0
        if consolidation and abs(consolidation.high - level.price) / level.price < 0.02:
            confidence += 0.15
            consolidation_days = consolidation.days
        
        signal_type = (
            SwingSignalType.CONSOLIDATION_BREAKOUT 
            if consolidation_days > 0 
            else SwingSignalType.BREAKOUT_LONG
        )
        
        return SwingSignal(
            symbol=symbol,
            signal_type=signal_type,
            entry_price=entry,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            target_3=target_3,
            sr_level=level,
            trend=trend,
            volume_ratio=volume_ratio,
            atr=atr,
            consolidation_days=consolidation_days,
            timestamp=datetime.now(),
            confidence=min(1.0, confidence),
            holding_days_estimate=self._estimate_holding_days(atr, trend)
        )
    
    def _check_support_breakdown(
        self,
        symbol: str,
        current: pd.Series,
        prev: pd.Series,
        level: SRLevel,
        trend: TrendAnalysis,
        volume_ratio: float,
        consolidation: Optional[ConsolidationZone]
    ) -> Optional[SwingSignal]:
        """Check for breakdown below support."""
        # Price must close below support
        if current["close"] >= level.price:
            return None
        
        # Previous close should be at or above level
        if prev["close"] < level.price * 0.98:
            return None
        
        # Volume confirmation
        if volume_ratio < self.volume_surge_multiplier:
            return None
        
        # Trend alignment
        trend_bonus = 0.2 if trend.direction == TrendDirection.DOWNTREND else 0
        
        entry = current["close"]
        atr = trend.atr
        
        # Stop loss above the broken support (now resistance)
        stop_loss = level.price + (atr * 0.5)
        
        # Targets
        target_1 = entry - (atr * 2)
        target_2 = entry - (atr * 3)
        target_3 = entry - (atr * 5)
        
        risk = stop_loss - entry
        reward = entry - target_1
        
        if risk <= 0 or reward / risk < self.min_risk_reward:
            return None
        
        confidence = 0.5 + trend_bonus
        confidence += min(0.2, (volume_ratio - 1) * 0.1)
        
        consolidation_days = 0
        if consolidation and abs(consolidation.low - level.price) / level.price < 0.02:
            confidence += 0.15
            consolidation_days = consolidation.days
        
        return SwingSignal(
            symbol=symbol,
            signal_type=SwingSignalType.BREAKOUT_SHORT,
            entry_price=entry,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            target_3=target_3,
            sr_level=level,
            trend=trend,
            volume_ratio=volume_ratio,
            atr=atr,
            consolidation_days=consolidation_days,
            timestamp=datetime.now(),
            confidence=min(1.0, confidence),
            holding_days_estimate=self._estimate_holding_days(atr, trend)
        )
    
    def _check_pullback_buy(
        self,
        symbol: str,
        df: pd.DataFrame,
        trend: TrendAnalysis,
        sr_levels: List[SRLevel]
    ) -> Optional[SwingSignal]:
        """Check for pullback buy entry in uptrend."""
        current = df.iloc[-1]
        
        # Price should be pulling back to EMA
        ema_distance = (current["close"] - trend.ema_short) / trend.ema_short * 100
        
        # Looking for price near or slightly below short EMA
        if not (-2 < ema_distance < 1):
            return None
        
        # Find nearest support
        supports = [l for l in sr_levels if l.price < current["close"]]
        if not supports:
            return None
        
        nearest_support = max(supports, key=lambda l: l.price)
        
        entry = current["close"]
        atr = trend.atr
        
        stop_loss = nearest_support.price - (atr * 0.3)
        target_1 = entry + (atr * 2)
        target_2 = entry + (atr * 3)
        target_3 = entry + (atr * 4)
        
        risk = entry - stop_loss
        if risk <= 0:
            return None
        
        if (target_1 - entry) / risk < self.min_risk_reward:
            return None
        
        avg_vol = self._avg_volumes.get(symbol, df["volume"].tail(20).mean())
        volume_ratio = current["volume"] / avg_vol if avg_vol > 0 else 1
        
        return SwingSignal(
            symbol=symbol,
            signal_type=SwingSignalType.PULLBACK_BUY,
            entry_price=entry,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            target_3=target_3,
            sr_level=nearest_support,
            trend=trend,
            volume_ratio=volume_ratio,
            atr=atr,
            consolidation_days=0,
            timestamp=datetime.now(),
            confidence=0.6 + (trend.strength * 0.2),
            holding_days_estimate=self._estimate_holding_days(atr, trend)
        )
    
    def _check_pullback_sell(
        self,
        symbol: str,
        df: pd.DataFrame,
        trend: TrendAnalysis,
        sr_levels: List[SRLevel]
    ) -> Optional[SwingSignal]:
        """Check for pullback sell entry in downtrend."""
        current = df.iloc[-1]
        
        # Price should be pulling back to EMA
        ema_distance = (current["close"] - trend.ema_short) / trend.ema_short * 100
        
        # Looking for price near or slightly above short EMA
        if not (-1 < ema_distance < 2):
            return None
        
        # Find nearest resistance
        resistances = [l for l in sr_levels if l.price > current["close"]]
        if not resistances:
            return None
        
        nearest_resistance = min(resistances, key=lambda l: l.price)
        
        entry = current["close"]
        atr = trend.atr
        
        stop_loss = nearest_resistance.price + (atr * 0.3)
        target_1 = entry - (atr * 2)
        target_2 = entry - (atr * 3)
        target_3 = entry - (atr * 4)
        
        risk = stop_loss - entry
        if risk <= 0:
            return None
        
        if (entry - target_1) / risk < self.min_risk_reward:
            return None
        
        avg_vol = self._avg_volumes.get(symbol, df["volume"].tail(20).mean())
        volume_ratio = current["volume"] / avg_vol if avg_vol > 0 else 1
        
        return SwingSignal(
            symbol=symbol,
            signal_type=SwingSignalType.PULLBACK_SELL,
            entry_price=entry,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            target_3=target_3,
            sr_level=nearest_resistance,
            trend=trend,
            volume_ratio=volume_ratio,
            atr=atr,
            consolidation_days=0,
            timestamp=datetime.now(),
            confidence=0.6 + (trend.strength * 0.2),
            holding_days_estimate=self._estimate_holding_days(atr, trend)
        )
    
    def _estimate_holding_days(
        self,
        atr: float,
        trend: TrendAnalysis
    ) -> int:
        """Estimate holding period based on ATR and trend."""
        # Higher ATR = faster moves = shorter holding
        # Stronger trend = faster moves = shorter holding
        base_days = 7
        
        atr_factor = max(0.5, 1 - (trend.atr_percent / 5))  # Higher ATR = shorter hold
        trend_factor = max(0.5, 1 - (trend.strength * 0.3))  # Stronger trend = shorter
        
        estimated = int(base_days * atr_factor * trend_factor)
        return max(2, min(15, estimated))


class SwingScanner:
    """Scans multiple symbols for swing trading opportunities."""
    
    def __init__(
        self,
        level_calculator: SwingLevelCalculator,
        detector: SwingBreakoutDetector
    ):
        self.level_calculator = level_calculator
        self.detector = detector
        
        # Cache
        self._sr_cache: Dict[str, Dict[str, List[SRLevel]]] = {}
        self._trend_cache: Dict[str, TrendAnalysis] = {}
        self._consolidation_cache: Dict[str, List[ConsolidationZone]] = {}
    
    def analyze_symbol(
        self,
        symbol: str,
        daily_df: pd.DataFrame
    ) -> Dict:
        """
        Full analysis for a symbol.
        
        Args:
            symbol: Trading symbol.
            daily_df: Daily OHLC DataFrame.
        
        Returns:
            Analysis dict with levels, trend, consolidations, signal.
        """
        # Calculate S/R levels
        levels = self.level_calculator.calculate_all_swing_levels(daily_df)
        self._sr_cache[symbol] = levels
        
        # Analyze trend
        trend = self.level_calculator.analyze_trend(daily_df)
        self._trend_cache[symbol] = trend
        
        # Find consolidations
        consolidations = self.level_calculator.find_consolidation_zones(daily_df)
        self._consolidation_cache[symbol] = consolidations
        
        # Set average volume
        avg_vol = self.detector.calculate_average_volume(daily_df)
        self.detector.set_average_volume(symbol, avg_vol)
        
        # Detect signal
        recent_consolidation = consolidations[-1] if consolidations else None
        signal = self.detector.detect_breakout(
            symbol=symbol,
            df=daily_df,
            sr_levels=levels["all"],
            trend=trend,
            consolidation=recent_consolidation
        )
        
        return {
            "symbol": symbol,
            "levels": levels,
            "trend": trend,
            "consolidations": consolidations,
            "signal": signal,
            "current_price": daily_df.iloc[-1]["close"] if not daily_df.empty else 0
        }
    
    def scan_all(
        self,
        symbol_data: Dict[str, pd.DataFrame]
    ) -> List[SwingSignal]:
        """
        Scan all symbols for swing signals.
        
        Args:
            symbol_data: Dict of symbol -> daily DataFrame.
        
        Returns:
            List of swing signals, sorted by confidence.
        """
        signals = []
        
        for symbol, df in symbol_data.items():
            try:
                analysis = self.analyze_symbol(symbol, df)
                
                if analysis["signal"]:
                    signals.append(analysis["signal"])
                    logger.info(
                        f"Swing signal: {symbol} | {analysis['signal'].signal_type} | "
                        f"Confidence: {analysis['signal'].confidence:.2f}"
                    )
                    
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
        
        # Sort by confidence
        signals = sorted(signals, key=lambda s: s.confidence, reverse=True)
        
        return signals
    
    def get_watchlist_summary(
        self,
        symbol_data: Dict[str, pd.DataFrame]
    ) -> List[Dict]:
        """
        Get summary for all symbols in watchlist.
        
        Args:
            symbol_data: Dict of symbol -> daily DataFrame.
        
        Returns:
            List of symbol summaries.
        """
        summaries = []
        
        for symbol, df in symbol_data.items():
            if df.empty:
                continue
            
            analysis = self.analyze_symbol(symbol, df)
            trend = analysis["trend"]
            current_price = analysis["current_price"]
            
            # Get key levels
            supports, resistances = self.level_calculator.get_key_levels(
                current_price=current_price,
                all_levels=analysis["levels"]["all"]
            )
            
            summary = {
                "symbol": symbol,
                "price": current_price,
                "trend": trend.direction,
                "trend_strength": trend.strength,
                "atr_percent": trend.atr_percent,
                "nearest_support": supports[0].price if supports else None,
                "nearest_resistance": resistances[0].price if resistances else None,
                "in_consolidation": len(analysis["consolidations"]) > 0,
                "has_signal": analysis["signal"] is not None,
                "signal_type": analysis["signal"].signal_type if analysis["signal"] else None
            }
            
            summaries.append(summary)
        
        return summaries
