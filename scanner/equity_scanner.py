"""Equity scanner for identifying trading candidates."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from core.config import get_config
from core.models import OHLC, Tick
from data.kite_client import get_kite_client

logger = logging.getLogger(__name__)


class EquityScanner:
    """Scans watchlist for trading opportunities."""
    
    def __init__(self):
        self.config = get_config()
        self._historical_data: Dict[str, pd.DataFrame] = {}
        self._intraday_data: Dict[str, pd.DataFrame] = {}
        self._latest_ticks: Dict[str, Tick] = {}
    
    def load_historical_data(self, symbols: Optional[List[str]] = None):
        """
        Load historical data for symbols.
        
        Args:
            symbols: List of symbols to load. Defaults to watchlist.
        """
        symbols = symbols or self.config.watchlist.symbols
        kite = get_kite_client()
        
        lookback = self.config.strategy.sr_lookback_days
        
        for symbol in symbols:
            try:
                df = kite.get_historical_data(
                    symbol=symbol,
                    interval="day",
                    days=lookback + 5  # Extra buffer
                )
                
                if not df.empty:
                    self._historical_data[symbol] = df
                    logger.info(f"Loaded {len(df)} days of data for {symbol}")
                else:
                    logger.warning(f"No historical data for {symbol}")
                    
            except Exception as e:
                logger.error(f"Failed to load data for {symbol}: {e}")
    
    def load_intraday_data(self, symbols: Optional[List[str]] = None):
        """Load today's intraday data for symbols."""
        symbols = symbols or self.config.watchlist.symbols
        kite = get_kite_client()
        
        for symbol in symbols:
            try:
                df = kite.get_intraday_data(
                    symbol=symbol,
                    interval="5minute"
                )
                
                if not df.empty:
                    self._intraday_data[symbol] = df
                    logger.debug(f"Loaded {len(df)} intraday candles for {symbol}")
                    
            except Exception as e:
                logger.error(f"Failed to load intraday data for {symbol}: {e}")
    
    def update_tick(self, tick: Tick):
        """Update latest tick for a symbol."""
        self._latest_ticks[tick.symbol] = tick
    
    def get_historical_data(self, symbol: str) -> pd.DataFrame:
        """Get historical data for a symbol."""
        return self._historical_data.get(symbol, pd.DataFrame())
    
    def get_intraday_data(self, symbol: str) -> pd.DataFrame:
        """Get intraday data for a symbol."""
        return self._intraday_data.get(symbol, pd.DataFrame())
    
    def get_latest_tick(self, symbol: str) -> Optional[Tick]:
        """Get latest tick for a symbol."""
        return self._latest_ticks.get(symbol)
    
    def get_current_candle(self, symbol: str) -> Optional[OHLC]:
        """
        Get the current/latest intraday candle for a symbol.
        
        Args:
            symbol: Trading symbol.
        
        Returns:
            OHLC candle or None.
        """
        df = self._intraday_data.get(symbol)
        
        if df is None or df.empty:
            return None
        
        row = df.iloc[-1]
        
        return OHLC(
            symbol=symbol,
            timestamp=row["timestamp"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"]
        )
    
    def get_all_current_candles(self) -> Dict[str, OHLC]:
        """Get current candles for all symbols."""
        candles = {}
        
        for symbol in self._intraday_data.keys():
            candle = self.get_current_candle(symbol)
            if candle:
                candles[symbol] = candle
        
        return candles
    
    def get_current_prices(self) -> Dict[str, float]:
        """Get current prices for all tracked symbols."""
        prices = {}
        
        for symbol, tick in self._latest_ticks.items():
            prices[symbol] = tick.last_price
        
        # Fallback to intraday close if no tick
        for symbol, df in self._intraday_data.items():
            if symbol not in prices and not df.empty:
                prices[symbol] = df.iloc[-1]["close"]
        
        return prices
    
    def get_volumes(self) -> Dict[str, int]:
        """Get current volumes for all symbols."""
        volumes = {}
        
        for symbol, tick in self._latest_ticks.items():
            volumes[symbol] = tick.volume
        
        for symbol, df in self._intraday_data.items():
            if symbol not in volumes and not df.empty:
                volumes[symbol] = df.iloc[-1]["volume"]
        
        return volumes
    
    def scan_for_volume_spikes(
        self,
        threshold_multiplier: float = 2.0
    ) -> List[str]:
        """
        Scan for symbols with unusual volume.
        
        Args:
            threshold_multiplier: Volume vs average threshold.
        
        Returns:
            List of symbols with volume spikes.
        """
        spikes = []
        
        for symbol in self.config.watchlist.symbols:
            daily_df = self._historical_data.get(symbol)
            
            if daily_df is None or daily_df.empty:
                continue
            
            # Calculate average volume
            avg_volume = daily_df["volume"].tail(20).mean()
            
            # Get today's volume
            tick = self._latest_ticks.get(symbol)
            if tick and tick.volume > avg_volume * threshold_multiplier:
                spikes.append(symbol)
        
        return spikes
    
    def get_gap_stocks(self, min_gap_percent: float = 1.0) -> Dict[str, float]:
        """
        Find stocks that gapped up or down at open.
        
        Args:
            min_gap_percent: Minimum gap percentage.
        
        Returns:
            Dict of symbol -> gap percent.
        """
        gaps = {}
        
        for symbol in self.config.watchlist.symbols:
            daily_df = self._historical_data.get(symbol)
            
            if daily_df is None or len(daily_df) < 2:
                continue
            
            prev_close = daily_df.iloc[-2]["close"]
            today_open = daily_df.iloc[-1]["open"]
            
            gap_percent = ((today_open - prev_close) / prev_close) * 100
            
            if abs(gap_percent) >= min_gap_percent:
                gaps[symbol] = gap_percent
        
        return gaps


def scan_equities(data: dict, cfg: dict) -> List[str]:
    """
    Legacy scan function for compatibility.
    
    Args:
        data: Market data.
        cfg: Configuration.
    
    Returns:
        List of symbols to trade.
    """
    scanner = EquityScanner()
    return scanner.scan_for_volume_spikes()


# Singleton instance
_scanner: Optional[EquityScanner] = None


def get_scanner() -> EquityScanner:
    """Get singleton scanner instance."""
    global _scanner
    if _scanner is None:
        _scanner = EquityScanner()
    return _scanner
