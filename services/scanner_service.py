"""
Scanner Service - Real-time signal scanning with alerts.

Runs in background and scans watchlist for trading setups,
sending alerts when high-quality signals are found.
"""

import logging
from datetime import datetime, time
from typing import Optional, List, Dict, Callable
from threading import Thread, Event
import time as time_module

from services.live_data_service import get_live_data_service
from services.alert_service import get_alert_service
from scanner.swing_scanner import SwingScanner, ScanResult
from strategies.swing_levels import SwingLevelCalculator
from core.config import get_config

logger = logging.getLogger(__name__)


class ScannerService:
    """
    Background service for real-time signal scanning.
    """
    
    def __init__(self):
        self.config = get_config()
        self.live_data = get_live_data_service()
        self.alerts = get_alert_service()
        self.swing_scanner = SwingScanner()
        
        # Scan settings
        self.scan_interval_seconds = 60  # Scan every minute
        self.min_score_for_alert = 70  # Minimum score to trigger alert
        
        # Watchlist
        self._watchlist: List[str] = []
        
        # State
        self._running = False
        self._stop_event = Event()
        self._scan_thread: Optional[Thread] = None
        
        # Callbacks for new signals
        self._signal_callbacks: List[Callable[[ScanResult], None]] = []
        
        # Track already alerted signals to avoid duplicates
        self._alerted_signals: Dict[str, datetime] = {}
        self._alert_cooldown_minutes = 30
        
        # Last scan results
        self.last_scan_results: List[ScanResult] = []
        self.last_scan_time: Optional[datetime] = None
    
    def set_watchlist(self, symbols: List[str]):
        """Set the watchlist to scan."""
        self._watchlist = symbols
        logger.info(f"Scanner watchlist set: {len(symbols)} symbols")
    
    def start(self, watchlist: Optional[List[str]] = None):
        """Start the scanner service."""
        if watchlist:
            self._watchlist = watchlist
        
        if not self._watchlist:
            # Use default watchlist
            self._watchlist = self.config.swing_watchlist.symbols or [
                "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
                "BHARTIARTL", "SBIN", "WIPRO", "TATASTEEL", "AXISBANK"
            ]
        
        self._running = True
        self._stop_event.clear()
        
        self._scan_thread = Thread(target=self._scan_loop, daemon=True)
        self._scan_thread.start()
        
        logger.info("Scanner service started")
    
    def stop(self):
        """Stop the scanner service."""
        self._running = False
        self._stop_event.set()
        
        if self._scan_thread:
            self._scan_thread.join(timeout=5)
        
        logger.info("Scanner service stopped")
    
    def _scan_loop(self):
        """Main scanning loop."""
        while self._running:
            try:
                # Check market hours (9:15 AM - 3:30 PM IST)
                now = datetime.now()
                market_open = time(9, 15)
                market_close = time(15, 30)
                
                if market_open <= now.time() <= market_close:
                    self._run_scan()
                else:
                    logger.debug("Outside market hours, skipping scan")
                
            except Exception as e:
                logger.error(f"Scan error: {e}")
            
            # Wait for next scan
            self._stop_event.wait(timeout=self.scan_interval_seconds)
    
    def _run_scan(self):
        """Run a single scan cycle."""
        logger.debug(f"Running scan on {len(self._watchlist)} symbols")
        
        results = []
        
        for symbol in self._watchlist:
            try:
                result = self._scan_symbol(symbol)
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
        
        # Sort by score
        results.sort(key=lambda x: x.score, reverse=True)
        
        self.last_scan_results = results
        self.last_scan_time = datetime.now()
        
        # Process high-score signals
        for result in results:
            if result.score >= self.min_score_for_alert:
                self._process_signal(result)
        
        logger.debug(f"Scan complete: {len(results)} signals found")
    
    def _scan_symbol(self, symbol: str) -> Optional[ScanResult]:
        """Scan a single symbol."""
        # Try to get live data first
        if self.live_data.is_ready:
            df = self.live_data.get_historical_data(symbol, interval="day", days=100)
        else:
            # Fallback to scanner's data source
            from scanner.equity_scanner import get_scanner
            scanner = get_scanner()
            df = scanner.get_historical_data(symbol, days=100)
        
        if df is None or df.empty or len(df) < 60:
            return None
        
        return self.swing_scanner.scan_symbol(symbol, df)
    
    def _process_signal(self, result: ScanResult):
        """Process a high-score signal."""
        # Check cooldown
        signal_key = f"{result.symbol}_{result.scan_type.value}"
        
        if signal_key in self._alerted_signals:
            last_alert = self._alerted_signals[signal_key]
            minutes_since = (datetime.now() - last_alert).total_seconds() / 60
            
            if minutes_since < self._alert_cooldown_minutes:
                return  # Skip, recently alerted
        
        # Send alert
        self._send_signal_alert(result)
        
        # Update cooldown tracker
        self._alerted_signals[signal_key] = datetime.now()
        
        # Notify callbacks
        for callback in self._signal_callbacks:
            try:
                callback(result)
            except Exception as e:
                logger.error(f"Signal callback error: {e}")
    
    def _send_signal_alert(self, result: ScanResult):
        """Send alert for a signal."""
        # Calculate suggested entry, SL, target
        entry = result.price
        
        if "bullish" in result.scan_type.value or "support" in result.scan_type.value or "oversold" in result.scan_type.value:
            # Long setup
            sl = result.nearest_support or entry * 0.98
            target = result.nearest_resistance or entry * 1.04
        else:
            # Short/exit setup
            sl = result.nearest_resistance or entry * 1.02
            target = result.nearest_support or entry * 0.96
        
        self.alerts.signal_alert(
            symbol=result.symbol,
            signal_type=result.scan_type.value.replace("_", " ").title(),
            entry=entry,
            sl=sl,
            target=target,
            score=result.score,
            reason=result.recommendation
        )
    
    def register_signal_callback(self, callback: Callable[[ScanResult], None]):
        """Register callback for new signals."""
        self._signal_callbacks.append(callback)
    
    def scan_now(self) -> List[ScanResult]:
        """Run an immediate scan and return results."""
        self._run_scan()
        return self.last_scan_results
    
    def get_results(self, min_score: float = 0) -> List[ScanResult]:
        """Get last scan results filtered by minimum score."""
        return [r for r in self.last_scan_results if r.score >= min_score]


# Singleton
_scanner_service: Optional[ScannerService] = None


def get_scanner_service() -> ScannerService:
    """Get the scanner service singleton."""
    global _scanner_service
    if _scanner_service is None:
        _scanner_service = ScannerService()
    return _scanner_service
