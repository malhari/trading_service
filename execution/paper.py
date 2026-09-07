"""Paper trading execution module for testing strategies."""

import logging
from datetime import datetime
from typing import Dict, List, Optional
import random

from core.models import Order, OrderSide, OrderStatus, OrderType, ProductType

logger = logging.getLogger(__name__)


class PaperExecutor:
    """
    Paper trading executor that simulates order execution.
    Useful for testing strategies without real money.
    """
    
    def __init__(self, slippage_percent: float = 0.05):
        """
        Initialize paper executor.
        
        Args:
            slippage_percent: Simulated slippage percentage.
        """
        self.slippage_percent = slippage_percent
        self._orders: Dict[str, Order] = {}
        self._positions: Dict[str, dict] = {}
        self._trade_count = 0
    
    def execute(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        order_type: OrderType = OrderType.MARKET
    ) -> Optional[str]:
        """
        Execute a paper trade.
        
        Args:
            symbol: Trading symbol.
            side: BUY or SELL.
            quantity: Order quantity.
            price: Order price.
            order_type: Order type.
        
        Returns:
            Order ID if successful.
        """
        self._trade_count += 1
        order_id = f"PAPER_{self._trade_count:06d}"
        
        # Apply slippage for market orders
        exec_price = price
        if order_type == OrderType.MARKET:
            slippage = price * (self.slippage_percent / 100)
            if side == OrderSide.BUY:
                exec_price = price + slippage  # Pay more when buying
            else:
                exec_price = price - slippage  # Get less when selling
        
        order = Order(
            order_id=order_id,
            symbol=symbol,
            instrument_token=0,
            side=side,
            quantity=quantity,
            order_type=order_type,
            product=ProductType.MIS,
            price=price,
            status=OrderStatus.COMPLETE,
            filled_quantity=quantity,
            average_price=exec_price,
            placed_at=datetime.now(),
            completed_at=datetime.now()
        )
        
        self._orders[order_id] = order
        
        # Update position
        self._update_position(symbol, side, quantity, exec_price)
        
        logger.info(
            f"[PAPER] Order executed: {order_id} | {side.value} {quantity} "
            f"{symbol} @ {exec_price:.2f}"
        )
        
        return order_id
    
    def _update_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float
    ):
        """Update paper position after a trade."""
        if symbol not in self._positions:
            self._positions[symbol] = {
                "quantity": 0,
                "average_price": 0,
                "pnl": 0
            }
        
        pos = self._positions[symbol]
        
        if side == OrderSide.BUY:
            # Adding to long position
            total_value = (pos["quantity"] * pos["average_price"]) + (quantity * price)
            pos["quantity"] += quantity
            if pos["quantity"] > 0:
                pos["average_price"] = total_value / pos["quantity"]
        else:
            # Reducing position or going short
            if pos["quantity"] > 0:
                # Closing long
                pnl = (price - pos["average_price"]) * min(quantity, pos["quantity"])
                pos["pnl"] += pnl
            pos["quantity"] -= quantity
            if pos["quantity"] < 0:
                pos["average_price"] = price
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        return self._orders.get(order_id)
    
    def get_positions(self) -> Dict[str, dict]:
        """Get all paper positions."""
        return self._positions.copy()
    
    def get_total_pnl(self) -> float:
        """Get total realized P&L."""
        return sum(p["pnl"] for p in self._positions.values())
    
    def reset(self):
        """Reset paper trading state."""
        self._orders.clear()
        self._positions.clear()
        self._trade_count = 0
        logger.info("[PAPER] Trading state reset")


# Singleton instance
_paper_executor: Optional[PaperExecutor] = None


def get_paper_executor() -> PaperExecutor:
    """Get singleton paper executor."""
    global _paper_executor
    if _paper_executor is None:
        _paper_executor = PaperExecutor()
    return _paper_executor
