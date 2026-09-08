"""
Alert Service - Multi-channel notifications for trading signals.

Supports:
- Telegram bot messages
- Desktop notifications (browser)
- Sound alerts
- In-app notifications
"""

import os
import logging
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Callable
from threading import Thread
from dataclasses import dataclass, field
from enum import Enum
import json

logger = logging.getLogger(__name__)


class AlertPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(str, Enum):
    SIGNAL = "signal"
    PRICE_ALERT = "price_alert"
    ORDER_FILLED = "order_filled"
    STOP_LOSS_HIT = "stop_loss_hit"
    TARGET_HIT = "target_hit"
    RISK_WARNING = "risk_warning"
    SYSTEM = "system"


@dataclass
class Alert:
    """An alert notification."""
    alert_type: AlertType
    title: str
    message: str
    priority: AlertPriority = AlertPriority.MEDIUM
    symbol: Optional[str] = None
    price: Optional[float] = None
    data: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_telegram_message(self) -> str:
        """Format alert for Telegram."""
        emoji_map = {
            AlertType.SIGNAL: "📊",
            AlertType.PRICE_ALERT: "🔔",
            AlertType.ORDER_FILLED: "✅",
            AlertType.STOP_LOSS_HIT: "🔴",
            AlertType.TARGET_HIT: "🟢",
            AlertType.RISK_WARNING: "⚠️",
            AlertType.SYSTEM: "ℹ️",
        }
        
        priority_emoji = {
            AlertPriority.LOW: "",
            AlertPriority.MEDIUM: "",
            AlertPriority.HIGH: "❗",
            AlertPriority.CRITICAL: "🚨",
        }
        
        emoji = emoji_map.get(self.alert_type, "📢")
        priority = priority_emoji.get(self.priority, "")
        
        msg = f"{emoji} {priority} *{self.title}*\n\n"
        msg += f"{self.message}\n"
        
        if self.symbol:
            msg += f"\n📈 Symbol: `{self.symbol}`"
        if self.price:
            msg += f"\n💰 Price: Rs.{self.price:.2f}"
        
        msg += f"\n\n⏰ {self.timestamp.strftime('%H:%M:%S')}"
        
        return msg


class TelegramBot:
    """Telegram bot for sending alerts."""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self._is_configured = bool(bot_token and chat_id)
    
    @property
    def is_configured(self) -> bool:
        return self._is_configured
    
    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a message via Telegram."""
        if not self._is_configured:
            logger.warning("Telegram bot not configured")
            return False
        
        try:
            import requests
            
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.debug("Telegram message sent")
                return True
            else:
                logger.error(f"Telegram error: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    def send_alert(self, alert: Alert) -> bool:
        """Send an alert via Telegram."""
        return self.send_message(alert.to_telegram_message())


class AlertService:
    """
    Central alert service managing multiple notification channels.
    """
    
    def __init__(self):
        # Telegram
        self.telegram = TelegramBot(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.getenv("TELEGRAM_CHAT_ID", "")
        )
        
        # Alert history
        self._alerts: List[Alert] = []
        self._max_history = 100
        
        # Callbacks for UI notifications
        self._ui_callbacks: List[Callable[[Alert], None]] = []
        
        # Alert settings
        self.telegram_enabled = True
        self.desktop_enabled = True
        self.sound_enabled = True
        
        # Minimum priority for each channel
        self.telegram_min_priority = AlertPriority.MEDIUM
        self.desktop_min_priority = AlertPriority.LOW
    
    def configure_telegram(self, bot_token: str, chat_id: str):
        """Configure Telegram bot."""
        self.telegram = TelegramBot(bot_token, chat_id)
        logger.info("Telegram bot configured")
    
    def send_alert(self, alert: Alert):
        """
        Send an alert through all enabled channels.
        
        Args:
            alert: The alert to send.
        """
        # Store in history
        self._alerts.append(alert)
        if len(self._alerts) > self._max_history:
            self._alerts = self._alerts[-self._max_history:]
        
        # Send to Telegram
        if self.telegram_enabled and self.telegram.is_configured:
            if self._priority_value(alert.priority) >= self._priority_value(self.telegram_min_priority):
                Thread(target=self.telegram.send_alert, args=(alert,), daemon=True).start()
        
        # Notify UI callbacks
        for callback in self._ui_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"UI callback error: {e}")
        
        logger.info(f"Alert sent: {alert.title}")
    
    def _priority_value(self, priority: AlertPriority) -> int:
        """Get numeric value for priority comparison."""
        values = {
            AlertPriority.LOW: 1,
            AlertPriority.MEDIUM: 2,
            AlertPriority.HIGH: 3,
            AlertPriority.CRITICAL: 4
        }
        return values.get(priority, 0)
    
    def register_ui_callback(self, callback: Callable[[Alert], None]):
        """Register callback for UI notifications."""
        self._ui_callbacks.append(callback)
    
    def get_recent_alerts(self, count: int = 10) -> List[Alert]:
        """Get recent alerts."""
        return self._alerts[-count:]
    
    # ==================== Convenience Methods ====================
    
    def signal_alert(
        self,
        symbol: str,
        signal_type: str,
        entry: float,
        sl: float,
        target: float,
        score: float = 0,
        reason: str = ""
    ):
        """Send a trading signal alert."""
        risk = abs(entry - sl)
        reward = abs(target - entry)
        rr = reward / risk if risk > 0 else 0
        
        message = f"*{signal_type}* signal detected!\n\n"
        message += f"Entry: Rs.{entry:.2f}\n"
        message += f"Stop Loss: Rs.{sl:.2f}\n"
        message += f"Target: Rs.{target:.2f}\n"
        message += f"R:R = 1:{rr:.1f}\n"
        
        if score > 0:
            message += f"Score: {score:.0f}/100\n"
        if reason:
            message += f"\n_{reason}_"
        
        priority = AlertPriority.HIGH if score >= 75 else AlertPriority.MEDIUM
        
        alert = Alert(
            alert_type=AlertType.SIGNAL,
            title=f"{symbol} - {signal_type}",
            message=message,
            priority=priority,
            symbol=symbol,
            price=entry,
            data={
                "signal_type": signal_type,
                "entry": entry,
                "sl": sl,
                "target": target,
                "score": score
            }
        )
        
        self.send_alert(alert)
    
    def price_alert(self, symbol: str, price: float, message: str = ""):
        """Send a price alert."""
        alert = Alert(
            alert_type=AlertType.PRICE_ALERT,
            title=f"{symbol} Price Alert",
            message=message or f"{symbol} reached Rs.{price:.2f}",
            priority=AlertPriority.MEDIUM,
            symbol=symbol,
            price=price
        )
        
        self.send_alert(alert)
    
    def order_filled_alert(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        order_id: str = ""
    ):
        """Send order filled notification."""
        alert = Alert(
            alert_type=AlertType.ORDER_FILLED,
            title=f"Order Filled - {symbol}",
            message=f"{side} {quantity} shares at Rs.{price:.2f}",
            priority=AlertPriority.HIGH,
            symbol=symbol,
            price=price,
            data={"order_id": order_id, "side": side, "quantity": quantity}
        )
        
        self.send_alert(alert)
    
    def stop_loss_alert(self, symbol: str, price: float, pnl: float):
        """Send stop loss hit alert."""
        alert = Alert(
            alert_type=AlertType.STOP_LOSS_HIT,
            title=f"Stop Loss Hit - {symbol}",
            message=f"Position closed at Rs.{price:.2f}\nP&L: Rs.{pnl:.2f}",
            priority=AlertPriority.HIGH,
            symbol=symbol,
            price=price,
            data={"pnl": pnl}
        )
        
        self.send_alert(alert)
    
    def target_hit_alert(self, symbol: str, price: float, pnl: float):
        """Send target hit alert."""
        alert = Alert(
            alert_type=AlertType.TARGET_HIT,
            title=f"Target Hit - {symbol}",
            message=f"Position closed at Rs.{price:.2f}\nP&L: Rs.{pnl:.2f}",
            priority=AlertPriority.HIGH,
            symbol=symbol,
            price=price,
            data={"pnl": pnl}
        )
        
        self.send_alert(alert)
    
    def risk_warning(self, message: str, priority: AlertPriority = AlertPriority.HIGH):
        """Send risk management warning."""
        alert = Alert(
            alert_type=AlertType.RISK_WARNING,
            title="Risk Warning",
            message=message,
            priority=priority
        )
        
        self.send_alert(alert)


# Singleton
_alert_service: Optional[AlertService] = None


def get_alert_service() -> AlertService:
    """Get the alert service singleton."""
    global _alert_service
    if _alert_service is None:
        _alert_service = AlertService()
    return _alert_service
