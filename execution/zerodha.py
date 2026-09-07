"""Zerodha live execution module."""

import logging
from typing import Dict, List, Optional

from core.config import get_config, TradingMode
from core.models import Order, OrderSide, OrderStatus, OrderType, ProductType
from data.kite_client import get_kite_client

logger = logging.getLogger(__name__)


class ZerodhaExecutor:
    """
    Live order execution through Zerodha Kite Connect.
    """
    
    def __init__(self):
        self.config = get_config()
        self._kite = None
    
    @property
    def kite(self):
        """Lazy load Kite client."""
        if self._kite is None:
            self._kite = get_kite_client()
        return self._kite
    
    def is_ready(self) -> bool:
        """Check if executor is ready (authenticated)."""
        return self.kite.kite is not None and self.kite._access_token is not None
    
    def execute(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        order_type: OrderType = OrderType.MARKET,
        price: float = 0,
        trigger_price: float = 0,
        tag: str = ""
    ) -> Optional[str]:
        """
        Execute a trade on Zerodha.
        
        Args:
            symbol: Trading symbol.
            side: BUY or SELL.
            quantity: Order quantity.
            order_type: Order type.
            price: Limit price (for LIMIT orders).
            trigger_price: Trigger price (for SL orders).
            tag: Order tag.
        
        Returns:
            Order ID if successful.
        """
        if self.config.mode != TradingMode.LIVE:
            logger.warning("Attempted live execution in non-LIVE mode")
            return None
        
        if not self.is_ready():
            logger.error("Zerodha executor not ready - not authenticated")
            return None
        
        order_id = self.kite.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            product=ProductType.MIS,
            price=price,
            trigger_price=trigger_price,
            tag=tag
        )
        
        if order_id:
            logger.info(
                f"[LIVE] Order placed: {order_id} | {side.value} {quantity} "
                f"{symbol} @ {price if price > 0 else 'MARKET'}"
            )
        
        return order_id
    
    def modify_order(
        self,
        order_id: str,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None
    ) -> bool:
        """Modify an existing order."""
        if not self.is_ready():
            return False
        
        return self.kite.modify_order(
            order_id=order_id,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price
        )
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        if not self.is_ready():
            return False
        
        return self.kite.cancel_order(order_id)
    
    def get_orders(self) -> List[Order]:
        """Get all orders for the day."""
        if not self.is_ready():
            return []
        
        return self.kite.get_orders()
    
    def get_positions(self) -> Dict:
        """Get current positions."""
        if not self.is_ready():
            return {"net": [], "day": []}
        
        return self.kite.get_positions()
    
    def get_margins(self) -> Dict:
        """Get account margins."""
        if not self.is_ready():
            return {}
        
        return self.kite.get_margins()
    
    def square_off_all(self) -> List[str]:
        """
        Square off all intraday positions.
        
        Returns:
            List of order IDs for square-off orders.
        """
        if not self.is_ready():
            return []
        
        order_ids = []
        positions = self.get_positions()
        
        for pos in positions.get("day", []):
            if pos["quantity"] == 0:
                continue
            
            symbol = pos["tradingsymbol"]
            qty = abs(pos["quantity"])
            side = OrderSide.SELL if pos["quantity"] > 0 else OrderSide.BUY
            
            order_id = self.execute(
                symbol=symbol,
                side=side,
                quantity=qty,
                order_type=OrderType.MARKET,
                tag="SQUARE_OFF"
            )
            
            if order_id:
                order_ids.append(order_id)
                logger.info(f"[LIVE] Square-off: {symbol} qty={qty}")
        
        return order_ids


# Singleton instance
_zerodha_executor: Optional[ZerodhaExecutor] = None


def get_zerodha_executor() -> ZerodhaExecutor:
    """Get singleton Zerodha executor."""
    global _zerodha_executor
    if _zerodha_executor is None:
        _zerodha_executor = ZerodhaExecutor()
    return _zerodha_executor
