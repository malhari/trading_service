"""
Swing Trading Scanner - Combines RSI, MACD, EMA with S/R levels.

Scans for swing trading setups based on:
- RSI oversold/overbought with reversal
- MACD crossovers
- Price near support/resistance levels
- Volume confirmation
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import pandas as pd
from datetime import datetime
import logging

from strategies.swing_levels import SwingLevelCalculator
from scanner.equity_scanner import get_scanner

logger = logging.getLogger(__name__)


class ScanType(str, Enum):
    RSI_OVERSOLD = "rsi_oversold"
    RSI_OVERBOUGHT = "rsi_overbought"
    MACD_BULLISH_CROSS = "macd_bullish_cross"
    MACD_BEARISH_CROSS = "macd_bearish_cross"
    NEAR_SUPPORT = "near_support"
    NEAR_RESISTANCE = "near_resistance"
    BOUNCE_FROM_SUPPORT = "bounce_from_support"
    REJECTION_FROM_RESISTANCE = "rejection_from_resistance"
    COMBINED_BULLISH = "combined_bullish"
    COMBINED_BEARISH = "combined_bearish"


@dataclass
class ScanResult:
    """Result from a swing scan."""
    symbol: str
    scan_type: ScanType
    score: float  # 0-100
    price: float
    rsi: float
    macd_signal: str
    ema_signal: str
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    distance_to_support_pct: Optional[float] = None
    distance_to_resistance_pct: Optional[float] = None
    volume_ratio: float = 1.0
    recommendation: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    details: dict = field(default_factory=dict)


class SwingScanner:
    """
    Scans for swing trading setups using multiple indicators.
    """
    
    def __init__(
        self,
        rsi_oversold: float = 30,
        rsi_overbought: float = 70,
        support_proximity_pct: float = 2.0,
        resistance_proximity_pct: float = 2.0,
        volume_threshold: float = 1.2
    ):
        """
        Initialize scanner.
        
        Args:
            rsi_oversold: RSI level for oversold (default 30)
            rsi_overbought: RSI level for overbought (default 70)
            support_proximity_pct: % distance to support for "near" (default 2%)
            resistance_proximity_pct: % distance to resistance for "near" (default 2%)
            volume_threshold: Volume ratio vs 20-day avg for confirmation (default 1.2x)
        """
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.support_proximity_pct = support_proximity_pct
        self.resistance_proximity_pct = resistance_proximity_pct
        self.volume_threshold = volume_threshold
        self.calc = SwingLevelCalculator()
        self.scanner = get_scanner()
    
    def scan_symbol(self, symbol: str, df: Optional[pd.DataFrame] = None) -> Optional[ScanResult]:
        """
        Scan a single symbol for swing trading setups.
        
        Args:
            symbol: Stock symbol.
            df: Optional pre-loaded DataFrame.
        
        Returns:
            ScanResult if setup found, None otherwise.
        """
        try:
            if df is None:
                df = self.scanner.get_historical_data(symbol)
            
            if df.empty or len(df) < 60:
                return None
            
            # Get indicators
            indicators = self.calc.get_indicator_signals(df)
            if "error" in indicators:
                return None
            
            # Get S/R levels
            levels = self.calc.calculate_all_swing_levels(df)
            current_price = df.iloc[-1]["close"]
            supports, resistances = self.calc.get_key_levels(
                current_price, levels["all"], count=3
            )
            
            # Calculate distances to nearest levels
            nearest_support = supports[0].price if supports else None
            nearest_resistance = resistances[0].price if resistances else None
            
            dist_to_support = None
            dist_to_resistance = None
            
            if nearest_support:
                dist_to_support = ((current_price - nearest_support) / nearest_support) * 100
            if nearest_resistance:
                dist_to_resistance = ((nearest_resistance - current_price) / current_price) * 100
            
            # Calculate volume ratio
            if len(df) >= 20:
                avg_volume = df["volume"].tail(20).mean()
                current_volume = df.iloc[-1]["volume"]
                volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
            else:
                volume_ratio = 1.0
            
            # Determine scan type and score
            scan_type, score, recommendation = self._evaluate_setup(
                indicators, dist_to_support, dist_to_resistance, volume_ratio
            )
            
            if scan_type is None:
                return None
            
            return ScanResult(
                symbol=symbol,
                scan_type=scan_type,
                score=score,
                price=current_price,
                rsi=indicators["rsi"]["value"],
                macd_signal=indicators["macd"]["signal"],
                ema_signal=indicators["ema"]["signal"],
                nearest_support=nearest_support,
                nearest_resistance=nearest_resistance,
                distance_to_support_pct=dist_to_support,
                distance_to_resistance_pct=dist_to_resistance,
                volume_ratio=round(volume_ratio, 2),
                recommendation=recommendation,
                details={
                    "macd_histogram": indicators["macd"]["histogram"],
                    "macd_crossover": indicators["macd"]["crossover"],
                    "bullish_count": indicators["bullish_count"],
                    "bearish_count": indicators["bearish_count"]
                }
            )
            
        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}")
            return None
    
    def _evaluate_setup(
        self,
        indicators: dict,
        dist_to_support: Optional[float],
        dist_to_resistance: Optional[float],
        volume_ratio: float
    ) -> tuple[Optional[ScanType], float, str]:
        """
        Evaluate the setup quality and type.
        
        Returns:
            (scan_type, score, recommendation)
        """
        rsi_val = indicators["rsi"]["value"]
        rsi_sig = indicators["rsi"]["signal"]
        macd_sig = indicators["macd"]["signal"]
        macd_cross = indicators["macd"]["crossover"]
        ema_sig = indicators["ema"]["signal"]
        bullish = indicators["bullish_count"]
        bearish = indicators["bearish_count"]
        
        scan_type = None
        score = 0.0
        recommendation = ""
        
        # Check for combined bullish setup
        if bullish >= 2:
            near_support = dist_to_support is not None and dist_to_support < self.support_proximity_pct
            
            if rsi_sig == "recovering_from_oversold" and near_support:
                scan_type = ScanType.BOUNCE_FROM_SUPPORT
                score = 85 + (5 if volume_ratio > self.volume_threshold else 0)
                recommendation = "Strong buy signal: RSI recovering from oversold near support"
            elif rsi_val < self.rsi_oversold and near_support:
                scan_type = ScanType.RSI_OVERSOLD
                score = 75 + (5 if volume_ratio > self.volume_threshold else 0)
                recommendation = "Potential buy: RSI oversold near support, wait for reversal"
            elif macd_cross and macd_sig == "bullish_crossover":
                scan_type = ScanType.MACD_BULLISH_CROSS
                score = 70 + (5 if "uptrend" in ema_sig else 0)
                recommendation = "Buy signal: MACD bullish crossover"
            elif near_support:
                scan_type = ScanType.NEAR_SUPPORT
                score = 60 + (bullish * 10)
                recommendation = f"Watch: Price near support with {bullish} bullish indicators"
            else:
                scan_type = ScanType.COMBINED_BULLISH
                score = 55 + (bullish * 10)
                recommendation = f"Bullish: {bullish} indicators aligned"
        
        # Check for combined bearish setup (for existing longs to exit)
        elif bearish >= 2:
            near_resistance = dist_to_resistance is not None and dist_to_resistance < self.resistance_proximity_pct
            
            if rsi_sig == "weakening_from_overbought" and near_resistance:
                scan_type = ScanType.REJECTION_FROM_RESISTANCE
                score = 85
                recommendation = "Strong exit signal: RSI weakening from overbought near resistance"
            elif rsi_val > self.rsi_overbought and near_resistance:
                scan_type = ScanType.RSI_OVERBOUGHT
                score = 75
                recommendation = "Consider exit: RSI overbought near resistance"
            elif macd_cross and macd_sig == "bearish_crossover":
                scan_type = ScanType.MACD_BEARISH_CROSS
                score = 70
                recommendation = "Exit signal: MACD bearish crossover"
            elif near_resistance:
                scan_type = ScanType.NEAR_RESISTANCE
                score = 60
                recommendation = f"Watch for exit: Price near resistance"
            else:
                scan_type = ScanType.COMBINED_BEARISH
                score = 55
                recommendation = f"Bearish: {bearish} indicators aligned, consider exit"
        
        # Individual strong signals
        elif rsi_val < self.rsi_oversold:
            scan_type = ScanType.RSI_OVERSOLD
            score = 50
            recommendation = "RSI oversold, watch for reversal signal"
        elif rsi_val > self.rsi_overbought:
            scan_type = ScanType.RSI_OVERBOUGHT
            score = 50
            recommendation = "RSI overbought, watch for weakness"
        elif macd_cross:
            scan_type = ScanType.MACD_BULLISH_CROSS if "bullish" in macd_sig else ScanType.MACD_BEARISH_CROSS
            score = 55
            recommendation = f"MACD {macd_sig.replace('_', ' ')}"
        
        return scan_type, score, recommendation
    
    def scan_watchlist(
        self,
        symbols: list[str],
        min_score: float = 50
    ) -> list[ScanResult]:
        """
        Scan multiple symbols and return sorted results.
        
        Args:
            symbols: List of symbols to scan.
            min_score: Minimum score to include in results.
        
        Returns:
            List of ScanResults sorted by score descending.
        """
        results = []
        
        for symbol in symbols:
            result = self.scan_symbol(symbol)
            if result and result.score >= min_score:
                results.append(result)
        
        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        
        return results
    
    def get_bullish_setups(self, symbols: list[str]) -> list[ScanResult]:
        """Get only bullish setups from watchlist."""
        results = self.scan_watchlist(symbols)
        bullish_types = {
            ScanType.RSI_OVERSOLD,
            ScanType.MACD_BULLISH_CROSS,
            ScanType.NEAR_SUPPORT,
            ScanType.BOUNCE_FROM_SUPPORT,
            ScanType.COMBINED_BULLISH
        }
        return [r for r in results if r.scan_type in bullish_types]
    
    def get_bearish_setups(self, symbols: list[str]) -> list[ScanResult]:
        """Get only bearish setups (exit signals) from watchlist."""
        results = self.scan_watchlist(symbols)
        bearish_types = {
            ScanType.RSI_OVERBOUGHT,
            ScanType.MACD_BEARISH_CROSS,
            ScanType.NEAR_RESISTANCE,
            ScanType.REJECTION_FROM_RESISTANCE,
            ScanType.COMBINED_BEARISH
        }
        return [r for r in results if r.scan_type in bearish_types]


# Singleton instance
_scanner: Optional[SwingScanner] = None


def get_swing_scanner() -> SwingScanner:
    """Get or create the swing scanner singleton."""
    global _scanner
    if _scanner is None:
        _scanner = SwingScanner()
    return _scanner
