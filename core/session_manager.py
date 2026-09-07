"""Intraday session manager with market hours and auto square-off."""

import logging
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Callable, List, Optional
from threading import Thread, Event
import time as time_module

from core.config import get_config

logger = logging.getLogger(__name__)


class MarketPhase(str, Enum):
    """Market trading phases."""
    PRE_MARKET = "PRE_MARKET"
    OPENING_RANGE = "OPENING_RANGE"
    REGULAR_TRADING = "REGULAR_TRADING"
    NO_NEW_ENTRIES = "NO_NEW_ENTRIES"
    SQUARE_OFF = "SQUARE_OFF"
    MARKET_CLOSED = "MARKET_CLOSED"


class SessionManager:
    """Manages intraday trading session timing and phases."""
    
    def __init__(self):
        self.config = get_config()
        self._stop_event = Event()
        self._phase_callbacks: List[Callable[[MarketPhase], None]] = []
        self._square_off_callback: Optional[Callable[[], None]] = None
        self._current_phase = MarketPhase.MARKET_CLOSED
        self._monitor_thread: Optional[Thread] = None
        
        # Parse times from config
        self._parse_times()
    
    def _parse_times(self):
        """Parse time strings from config."""
        intraday = self.config.intraday
        
        self.pre_market_time = self._parse_time(intraday.pre_market_start)
        self.market_open_time = self._parse_time(intraday.start_time)
        self.orb_end_time = self._add_minutes(
            self.market_open_time, 
            intraday.opening_range_minutes
        )
        self.last_entry_time = self._parse_time(intraday.last_entry_time)
        self.square_off_time = self._parse_time(intraday.square_off_time)
        self.market_close_time = time(15, 30)
    
    def _parse_time(self, time_str: str) -> time:
        """Parse time string (HH:MM) to time object."""
        parts = time_str.split(":")
        return time(int(parts[0]), int(parts[1]))
    
    def _add_minutes(self, t: time, minutes: int) -> time:
        """Add minutes to a time object."""
        dt = datetime.combine(datetime.today(), t)
        dt += timedelta(minutes=minutes)
        return dt.time()
    
    def get_current_phase(self) -> MarketPhase:
        """Get the current market phase based on time."""
        now = datetime.now().time()
        
        if now < self.pre_market_time:
            return MarketPhase.MARKET_CLOSED
        elif now < self.market_open_time:
            return MarketPhase.PRE_MARKET
        elif now < self.orb_end_time:
            return MarketPhase.OPENING_RANGE
        elif now < self.last_entry_time:
            return MarketPhase.REGULAR_TRADING
        elif now < self.square_off_time:
            return MarketPhase.NO_NEW_ENTRIES
        elif now < self.market_close_time:
            return MarketPhase.SQUARE_OFF
        else:
            return MarketPhase.MARKET_CLOSED
    
    def is_trading_allowed(self) -> bool:
        """Check if new trades are allowed."""
        phase = self.get_current_phase()
        return phase in [MarketPhase.OPENING_RANGE, MarketPhase.REGULAR_TRADING]
    
    def is_market_open(self) -> bool:
        """Check if market is open."""
        phase = self.get_current_phase()
        return phase not in [MarketPhase.MARKET_CLOSED, MarketPhase.PRE_MARKET]
    
    def is_orb_period(self) -> bool:
        """Check if we're in opening range breakout period."""
        return self.get_current_phase() == MarketPhase.OPENING_RANGE
    
    def should_square_off(self) -> bool:
        """Check if square-off should be triggered."""
        return self.get_current_phase() == MarketPhase.SQUARE_OFF
    
    def get_time_to_phase(self, phase: MarketPhase) -> Optional[timedelta]:
        """Get time remaining until a specific phase."""
        now = datetime.now()
        today = now.date()
        
        phase_times = {
            MarketPhase.PRE_MARKET: self.pre_market_time,
            MarketPhase.OPENING_RANGE: self.market_open_time,
            MarketPhase.REGULAR_TRADING: self.orb_end_time,
            MarketPhase.NO_NEW_ENTRIES: self.last_entry_time,
            MarketPhase.SQUARE_OFF: self.square_off_time,
            MarketPhase.MARKET_CLOSED: self.market_close_time,
        }
        
        target_time = phase_times.get(phase)
        if target_time is None:
            return None
        
        target_dt = datetime.combine(today, target_time)
        
        if target_dt <= now:
            return timedelta(0)
        
        return target_dt - now
    
    def get_time_to_square_off(self) -> timedelta:
        """Get time remaining until square-off."""
        return self.get_time_to_phase(MarketPhase.SQUARE_OFF) or timedelta(0)
    
    def register_phase_callback(self, callback: Callable[[MarketPhase], None]):
        """Register callback for phase changes."""
        self._phase_callbacks.append(callback)
    
    def register_square_off_callback(self, callback: Callable[[], None]):
        """Register callback for square-off trigger."""
        self._square_off_callback = callback
    
    def start_monitoring(self, check_interval_seconds: int = 30):
        """Start background thread to monitor phases."""
        self._stop_event.clear()
        
        def monitor_loop():
            last_phase = None
            
            while not self._stop_event.is_set():
                current_phase = self.get_current_phase()
                
                # Notify on phase change
                if current_phase != last_phase:
                    logger.info(f"Market phase changed: {last_phase} -> {current_phase}")
                    
                    for callback in self._phase_callbacks:
                        try:
                            callback(current_phase)
                        except Exception as e:
                            logger.error(f"Phase callback error: {e}")
                    
                    # Trigger square-off
                    if current_phase == MarketPhase.SQUARE_OFF:
                        if self._square_off_callback:
                            logger.info("Triggering square-off!")
                            try:
                                self._square_off_callback()
                            except Exception as e:
                                logger.error(f"Square-off callback error: {e}")
                    
                    last_phase = current_phase
                
                self._current_phase = current_phase
                time_module.sleep(check_interval_seconds)
        
        self._monitor_thread = Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Session monitoring started")
    
    def stop_monitoring(self):
        """Stop the monitoring thread."""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("Session monitoring stopped")
    
    def is_trading_day(self) -> bool:
        """Check if today is a trading day (simple weekday check)."""
        # Note: This doesn't account for market holidays
        # You may want to integrate with NSE holiday calendar
        return datetime.now().weekday() < 5  # Monday = 0, Friday = 4
    
    def get_session_info(self) -> dict:
        """Get current session information."""
        now = datetime.now()
        phase = self.get_current_phase()
        
        return {
            "current_time": now.strftime("%H:%M:%S"),
            "phase": phase.value,
            "is_trading_allowed": self.is_trading_allowed(),
            "is_market_open": self.is_market_open(),
            "is_orb_period": self.is_orb_period(),
            "time_to_last_entry": str(self.get_time_to_phase(MarketPhase.NO_NEW_ENTRIES)),
            "time_to_square_off": str(self.get_time_to_square_off()),
            "market_open": self.market_open_time.strftime("%H:%M"),
            "last_entry": self.last_entry_time.strftime("%H:%M"),
            "square_off": self.square_off_time.strftime("%H:%M"),
        }
    
    def wait_for_market_open(self, callback: Optional[Callable[[], None]] = None):
        """Wait for market to open (blocking)."""
        logger.info("Waiting for market to open...")
        
        while not self.is_market_open():
            if self._stop_event.is_set():
                return
            time_module.sleep(10)
        
        logger.info("Market is now open!")
        if callback:
            callback()


class TradingHolidays:
    """
    NSE trading holidays management.
    Note: This is a basic implementation. For production, 
    fetch from NSE website or maintain a calendar.
    """
    
    # Sample 2024 NSE holidays - update annually
    NSE_HOLIDAYS_2024 = [
        "2024-01-26",  # Republic Day
        "2024-03-08",  # Mahashivratri
        "2024-03-25",  # Holi
        "2024-03-29",  # Good Friday
        "2024-04-11",  # Id-Ul-Fitr
        "2024-04-14",  # Dr. Ambedkar Jayanti
        "2024-04-17",  # Ram Navami
        "2024-04-21",  # Mahavir Jayanti
        "2024-05-01",  # Maharashtra Day
        "2024-05-23",  # Buddha Purnima
        "2024-06-17",  # Bakri Id
        "2024-07-17",  # Muharram
        "2024-08-15",  # Independence Day
        "2024-10-02",  # Mahatma Gandhi Jayanti
        "2024-11-01",  # Diwali Laxmi Pujan
        "2024-11-15",  # Guru Nanak Jayanti
        "2024-12-25",  # Christmas
    ]
    
    @classmethod
    def is_holiday(cls, date: Optional[datetime] = None) -> bool:
        """Check if given date is a trading holiday."""
        if date is None:
            date = datetime.now()
        
        date_str = date.strftime("%Y-%m-%d")
        return date_str in cls.NSE_HOLIDAYS_2024
    
    @classmethod
    def get_next_trading_day(cls, from_date: Optional[datetime] = None) -> datetime:
        """Get the next trading day."""
        if from_date is None:
            from_date = datetime.now()
        
        next_day = from_date + timedelta(days=1)
        
        while next_day.weekday() >= 5 or cls.is_holiday(next_day):
            next_day += timedelta(days=1)
        
        return next_day


# Singleton instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get the singleton session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
