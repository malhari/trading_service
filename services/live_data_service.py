"""
Live Data Service - Manages real-time market data from Zerodha.

Handles:
- Kite authentication flow
- WebSocket connection for live ticks
- Real-time quote fetching
- Data caching for quick access
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable
from threading import Thread, Lock
import time

from data.kite_client import get_kite_client, KiteClient
from core.config import get_config
from core.models import Tick

logger = logging.getLogger(__name__)


class LiveDataService:
    """
    Manages live market data with caching and callbacks.
    """
    
    def __init__(self):
        self.config = get_config()
        self.kite = get_kite_client()
        self._is_initialized = False
        self._token_file = Path("data/.kite_token.json")
        
        # Real-time data cache
        self._quotes: Dict[str, Dict] = {}
        self._ticks: Dict[str, Tick] = {}
        self._quotes_lock = Lock()
        
        # Callbacks
        self._tick_callbacks: List[Callable[[str, Tick], None]] = []
        self._price_alert_callbacks: List[Callable[[str, float, str], None]] = []
        
        # Price alerts: symbol -> list of (price, direction, callback_id)
        self._price_alerts: Dict[str, List[tuple]] = {}
        
        # Auto-refresh thread
        self._refresh_thread: Optional[Thread] = None
        self._running = False
    
    def initialize(self) -> bool:
        """
        Initialize the live data service.
        
        Returns:
            True if successful, False if authentication needed.
        """
        # Try to load saved token
        access_token = self._load_saved_token()
        
        if access_token:
            if self.kite.initialize(access_token):
                self._is_initialized = True
                logger.info("Live data service initialized with saved token")
                return True
        
        # Need manual authentication
        logger.warning("Authentication required. Call get_login_url() and complete_login()")
        return False
    
    def get_login_url(self) -> str:
        """Get Kite login URL for authentication."""
        api_key = self.config.broker.api_key
        if not api_key:
            return "ERROR: KITE_API_KEY not configured in .env"
        
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=api_key)
        return kite.login_url()
    
    def complete_login(self, request_token: str) -> bool:
        """
        Complete login with request token from redirect URL.
        
        Args:
            request_token: Token from ?request_token=xxx in redirect URL
        
        Returns:
            True if successful.
        """
        if not self.kite.kite:
            api_key = self.config.broker.api_key
            from kiteconnect import KiteConnect
            self.kite.kite = KiteConnect(api_key=api_key)
        
        access_token = self.kite.generate_session(request_token)
        
        if access_token:
            self._save_token(access_token)
            self._is_initialized = True
            logger.info("Login completed successfully")
            return True
        
        return False
    
    def _save_token(self, access_token: str):
        """Save access token to file."""
        self._token_file.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "access_token": access_token,
            "saved_at": datetime.now().isoformat(),
            "valid_until": (datetime.now() + timedelta(hours=8)).isoformat()
        }
        
        with open(self._token_file, "w") as f:
            json.dump(data, f)
        
        logger.info("Access token saved")
    
    def _load_saved_token(self) -> Optional[str]:
        """Load saved access token if still valid."""
        if not self._token_file.exists():
            return None
        
        try:
            with open(self._token_file, "r") as f:
                data = json.load(f)
            
            valid_until = datetime.fromisoformat(data["valid_until"])
            
            if datetime.now() < valid_until:
                return data["access_token"]
            else:
                logger.info("Saved token expired")
                return None
                
        except Exception as e:
            logger.error(f"Failed to load saved token: {e}")
            return None
    
    @property
    def is_ready(self) -> bool:
        """Check if service is ready for use."""
        return self._is_initialized
    
    # ==================== Real-time Data ====================
    
    def start_live_feed(self, symbols: List[str]):
        """
        Start live data feed for symbols.
        
        Args:
            symbols: List of trading symbols.
        """
        if not self._is_initialized:
            logger.error("Service not initialized")
            return
        
        # Register internal tick handler
        self.kite.register_tick_callback(self._on_tick)
        
        # Start WebSocket
        self.kite.start_ticker(symbols)
        
        # Start quote refresh thread
        self._running = True
        self._refresh_thread = Thread(target=self._refresh_loop, args=(symbols,), daemon=True)
        self._refresh_thread.start()
        
        logger.info(f"Live feed started for {len(symbols)} symbols")
    
    def stop_live_feed(self):
        """Stop live data feed."""
        self._running = False
        self.kite.stop_ticker()
        logger.info("Live feed stopped")
    
    def _on_tick(self, tick: Tick):
        """Handle incoming tick data."""
        with self._quotes_lock:
            self._ticks[tick.symbol] = tick
            self._quotes[tick.symbol] = {
                "last_price": tick.last_price,
                "open": tick.open,
                "high": tick.high,
                "low": tick.low,
                "close": tick.close,
                "volume": tick.volume,
                "change": tick.change,
                "timestamp": tick.timestamp
            }
        
        # Notify callbacks
        for callback in self._tick_callbacks:
            try:
                callback(tick.symbol, tick)
            except Exception as e:
                logger.error(f"Tick callback error: {e}")
        
        # Check price alerts
        self._check_price_alerts(tick.symbol, tick.last_price)
    
    def _refresh_loop(self, symbols: List[str]):
        """Background loop to refresh quotes periodically."""
        while self._running:
            try:
                # Refresh quotes every 5 seconds as backup
                quotes = self.kite.get_quote(symbols)
                
                with self._quotes_lock:
                    for symbol, data in quotes.items():
                        if symbol not in self._quotes or \
                           self._quotes[symbol].get("last_price") != data["last_price"]:
                            self._quotes[symbol] = data
                
            except Exception as e:
                logger.error(f"Quote refresh error: {e}")
            
            time.sleep(5)
    
    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get cached quote for symbol."""
        with self._quotes_lock:
            return self._quotes.get(symbol)
    
    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Get cached quotes for multiple symbols."""
        with self._quotes_lock:
            return {s: self._quotes[s] for s in symbols if s in self._quotes}
    
    def get_live_price(self, symbol: str) -> float:
        """Get current price for symbol."""
        quote = self.get_quote(symbol)
        return quote["last_price"] if quote else 0.0
    
    # ==================== Callbacks ====================
    
    def register_tick_callback(self, callback: Callable[[str, Tick], None]):
        """Register callback for tick updates."""
        self._tick_callbacks.append(callback)
    
    def add_price_alert(
        self,
        symbol: str,
        price: float,
        direction: str = "crosses",  # "above", "below", "crosses"
        alert_id: str = ""
    ):
        """
        Add a price alert.
        
        Args:
            symbol: Trading symbol.
            price: Alert price level.
            direction: "above", "below", or "crosses".
            alert_id: Optional ID for the alert.
        """
        if symbol not in self._price_alerts:
            self._price_alerts[symbol] = []
        
        self._price_alerts[symbol].append((price, direction, alert_id or f"{symbol}_{price}"))
        logger.info(f"Price alert added: {symbol} {direction} {price}")
    
    def remove_price_alert(self, symbol: str, alert_id: str):
        """Remove a price alert."""
        if symbol in self._price_alerts:
            self._price_alerts[symbol] = [
                a for a in self._price_alerts[symbol] if a[2] != alert_id
            ]
    
    def register_price_alert_callback(self, callback: Callable[[str, float, str], None]):
        """Register callback for price alerts. Args: (symbol, price, alert_id)"""
        self._price_alert_callbacks.append(callback)
    
    def _check_price_alerts(self, symbol: str, current_price: float):
        """Check if any price alerts are triggered."""
        if symbol not in self._price_alerts:
            return
        
        triggered = []
        
        for price, direction, alert_id in self._price_alerts[symbol]:
            should_trigger = False
            
            # Get previous price
            prev_tick = self._ticks.get(symbol)
            prev_price = prev_tick.last_price if prev_tick else current_price
            
            if direction == "above" and current_price >= price:
                should_trigger = True
            elif direction == "below" and current_price <= price:
                should_trigger = True
            elif direction == "crosses":
                # Crossed from below or above
                if (prev_price < price <= current_price) or (prev_price > price >= current_price):
                    should_trigger = True
            
            if should_trigger:
                triggered.append((price, direction, alert_id))
                
                # Notify callbacks
                for callback in self._price_alert_callbacks:
                    try:
                        callback(symbol, current_price, alert_id)
                    except Exception as e:
                        logger.error(f"Price alert callback error: {e}")
        
        # Remove triggered alerts
        for alert in triggered:
            self._price_alerts[symbol].remove(alert)
    
    # ==================== Historical Data ====================
    
    def get_historical_data(
        self,
        symbol: str,
        interval: str = "day",
        days: int = 365
    ):
        """Get historical OHLC data."""
        if not self._is_initialized:
            logger.warning("Service not initialized, returning empty data")
            return None
        
        return self.kite.get_historical_data(symbol, interval=interval, days=days)
    
    def get_intraday_data(self, symbol: str, interval: str = "5minute"):
        """Get today's intraday data."""
        if not self._is_initialized:
            return None
        
        return self.kite.get_intraday_data(symbol, interval=interval)


# Singleton
_live_data_service: Optional[LiveDataService] = None


def get_live_data_service() -> LiveDataService:
    """Get the live data service singleton."""
    global _live_data_service
    if _live_data_service is None:
        _live_data_service = LiveDataService()
    return _live_data_service
