"""
Order Execution Service - Semi-automatic trade execution.

Features:
- One-click order placement
- Bracket orders (entry + SL + target)
- Order tracking and management
- Position synchronization with Zerodha
"""

import os
import logging
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from enum import Enum

from data.kite_client import get_kite_client, KiteClient
from core.models import OrderSide, OrderType, ProductType
from core.config import get_config
from services.alert_service import get_alert_service

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


@dataclass
class BracketOrder:
    """A bracket order with entry, SL, and target."""
    symbol: str
    side: OrderSide
    quantity: int
    entry_price: float
    stop_loss: float
    target: float
    product: ProductType = ProductType.MIS
    
    # Order IDs after placement
    entry_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    target_order_id: Optional[str] = None
    
    # Status
    status: str = "pending"  # pending, entry_placed, active, sl_hit, target_hit, cancelled
    entry_filled_price: float = 0.0
    exit_price: float = 0.0
    pnl: float = 0.0
    
    created_at: datetime = field(default_factory=datetime.now)


class OrderService:
    """
    Manages order execution with support for bracket orders.
    """
    
    def __init__(self):
        self.config = get_config()
        self.kite = get_kite_client()
        self.alerts = get_alert_service()
        
        # Execution mode
        self.mode = ExecutionMode.PAPER
        if os.getenv("TRADING_MODE", "paper").lower() == "live":
            self.mode = ExecutionMode.LIVE
        
        # Active orders
        self._bracket_orders: Dict[str, BracketOrder] = {}
        
        # Paper trading state
        self._paper_positions: Dict[str, Dict] = {}
        self._paper_order_counter = 0
    
    def set_mode(self, mode: ExecutionMode):
        """Set execution mode."""
        self.mode = mode
        logger.info(f"Order execution mode set to: {mode.value}")
    
    @property
    def is_live(self) -> bool:
        return self.mode == ExecutionMode.LIVE
    
    # ==================== One-Click Execution ====================
    
    def execute_signal(
        self,
        symbol: str,
        side: str,  # "BUY" or "SELL"
        entry_price: float,
        stop_loss: float,
        target: float,
        quantity: int = 0,
        risk_amount: float = 0,
        product: str = "MIS"
    ) -> Optional[BracketOrder]:
        """
        Execute a trading signal with bracket order.
        
        Args:
            symbol: Trading symbol.
            side: "BUY" or "SELL".
            entry_price: Entry price.
            stop_loss: Stop loss price.
            target: Target price.
            quantity: Number of shares (if 0, calculated from risk).
            risk_amount: Risk amount in Rs (used if quantity is 0).
            product: "MIS" for intraday, "CNC" for delivery.
        
        Returns:
            BracketOrder if successful.
        """
        order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        product_type = ProductType.MIS if product.upper() == "MIS" else ProductType.CNC
        
        # Calculate quantity from risk if not provided
        if quantity == 0 and risk_amount > 0:
            risk_per_share = abs(entry_price - stop_loss)
            if risk_per_share > 0:
                quantity = int(risk_amount / risk_per_share)
        
        if quantity <= 0:
            logger.error("Invalid quantity")
            return None
        
        # Create bracket order
        bracket = BracketOrder(
            symbol=symbol,
            side=order_side,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            product=product_type
        )
        
        # Execute based on mode
        if self.is_live:
            success = self._execute_live_bracket(bracket)
        else:
            success = self._execute_paper_bracket(bracket)
        
        if success:
            self._bracket_orders[f"{symbol}_{bracket.created_at.timestamp()}"] = bracket
            
            # Send alert
            self.alerts.order_filled_alert(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=entry_price,
                order_id=bracket.entry_order_id or "PAPER"
            )
            
            return bracket
        
        return None
    
    def _execute_live_bracket(self, bracket: BracketOrder) -> bool:
        """Execute bracket order on Zerodha."""
        try:
            # Place entry order
            entry_order_id = self.kite.place_order(
                symbol=bracket.symbol,
                side=bracket.side,
                quantity=bracket.quantity,
                order_type=OrderType.LIMIT,
                product=bracket.product,
                price=bracket.entry_price,
                tag="ENTRY"
            )
            
            if not entry_order_id:
                logger.error("Failed to place entry order")
                return False
            
            bracket.entry_order_id = entry_order_id
            bracket.status = "entry_placed"
            
            logger.info(f"Entry order placed: {entry_order_id}")
            
            # Note: SL and target orders should be placed after entry is filled
            # This would typically be handled by a position monitor
            
            return True
            
        except Exception as e:
            logger.error(f"Live bracket execution failed: {e}")
            return False
    
    def _execute_paper_bracket(self, bracket: BracketOrder) -> bool:
        """Execute bracket order in paper trading mode."""
        try:
            self._paper_order_counter += 1
            order_id = f"PAPER_{self._paper_order_counter}"
            
            bracket.entry_order_id = order_id
            bracket.entry_filled_price = bracket.entry_price
            bracket.status = "active"
            
            # Store paper position
            self._paper_positions[bracket.symbol] = {
                "symbol": bracket.symbol,
                "side": bracket.side.value,
                "quantity": bracket.quantity,
                "entry_price": bracket.entry_price,
                "stop_loss": bracket.stop_loss,
                "target": bracket.target,
                "current_price": bracket.entry_price,
                "pnl": 0.0,
                "status": "open"
            }
            
            logger.info(f"Paper order executed: {order_id}")
            return True
            
        except Exception as e:
            logger.error(f"Paper bracket execution failed: {e}")
            return False
    
    # ==================== Position Management ====================
    
    def get_positions(self) -> List[Dict]:
        """Get all positions (live or paper)."""
        if self.is_live:
            return self._get_live_positions()
        else:
            return list(self._paper_positions.values())
    
    def _get_live_positions(self) -> List[Dict]:
        """Get positions from Zerodha."""
        try:
            positions = self.kite.get_positions()
            
            result = []
            for pos in positions.get("day", []):
                if pos["quantity"] != 0:
                    result.append({
                        "symbol": pos["tradingsymbol"],
                        "side": "BUY" if pos["quantity"] > 0 else "SELL",
                        "quantity": abs(pos["quantity"]),
                        "entry_price": pos["average_price"],
                        "current_price": pos["last_price"],
                        "pnl": pos["pnl"],
                        "pnl_percent": (pos["pnl"] / (pos["average_price"] * abs(pos["quantity"])) * 100) if pos["average_price"] > 0 else 0,
                        "status": "open"
                    })
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get live positions: {e}")
            return []
    
    def update_paper_position(self, symbol: str, current_price: float):
        """Update paper position with current price."""
        if symbol not in self._paper_positions:
            return
        
        pos = self._paper_positions[symbol]
        pos["current_price"] = current_price
        
        # Calculate P&L
        if pos["side"] == "BUY":
            pos["pnl"] = (current_price - pos["entry_price"]) * pos["quantity"]
        else:
            pos["pnl"] = (pos["entry_price"] - current_price) * pos["quantity"]
        
        # Check SL/Target
        if pos["side"] == "BUY":
            if current_price <= pos["stop_loss"]:
                self._close_paper_position(symbol, current_price, "SL hit")
            elif current_price >= pos["target"]:
                self._close_paper_position(symbol, current_price, "Target hit")
        else:
            if current_price >= pos["stop_loss"]:
                self._close_paper_position(symbol, current_price, "SL hit")
            elif current_price <= pos["target"]:
                self._close_paper_position(symbol, current_price, "Target hit")
    
    def _close_paper_position(self, symbol: str, exit_price: float, reason: str):
        """Close a paper trading position."""
        if symbol not in self._paper_positions:
            return
        
        pos = self._paper_positions[symbol]
        
        # Calculate final P&L
        if pos["side"] == "BUY":
            pnl = (exit_price - pos["entry_price"]) * pos["quantity"]
        else:
            pnl = (pos["entry_price"] - exit_price) * pos["quantity"]
        
        pos["status"] = "closed"
        pos["pnl"] = pnl
        pos["exit_price"] = exit_price
        pos["exit_reason"] = reason
        
        # Send alert
        if "SL" in reason:
            self.alerts.stop_loss_alert(symbol, exit_price, pnl)
        else:
            self.alerts.target_hit_alert(symbol, exit_price, pnl)
        
        logger.info(f"Paper position closed: {symbol} @ {exit_price} ({reason}), P&L: {pnl}")
    
    def close_position(self, symbol: str, price: float = 0) -> bool:
        """Close a position manually."""
        if self.is_live:
            return self._close_live_position(symbol)
        else:
            if price > 0:
                self._close_paper_position(symbol, price, "Manual close")
            return True
    
    def _close_live_position(self, symbol: str) -> bool:
        """Close live position on Zerodha."""
        try:
            positions = self.kite.get_positions()
            
            for pos in positions.get("day", []):
                if pos["tradingsymbol"] == symbol and pos["quantity"] != 0:
                    # Place opposite order to close
                    side = OrderSide.SELL if pos["quantity"] > 0 else OrderSide.BUY
                    
                    order_id = self.kite.place_order(
                        symbol=symbol,
                        side=side,
                        quantity=abs(pos["quantity"]),
                        order_type=OrderType.MARKET,
                        product=ProductType(pos["product"]),
                        tag="EXIT"
                    )
                    
                    if order_id:
                        logger.info(f"Position closed: {symbol}, order: {order_id}")
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to close live position: {e}")
            return False
    
    # ==================== Order Tracking ====================
    
    def get_orders_today(self) -> List[Dict]:
        """Get all orders for today."""
        if self.is_live:
            orders = self.kite.get_orders()
            return [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "quantity": o.quantity,
                    "price": o.price,
                    "status": o.status.value,
                    "filled_qty": o.filled_quantity,
                    "avg_price": o.average_price
                }
                for o in orders
            ]
        else:
            # Return paper orders
            return [
                {
                    "order_id": b.entry_order_id,
                    "symbol": b.symbol,
                    "side": b.side.value,
                    "quantity": b.quantity,
                    "price": b.entry_price,
                    "status": b.status,
                    "filled_qty": b.quantity if b.status == "active" else 0,
                    "avg_price": b.entry_filled_price
                }
                for b in self._bracket_orders.values()
            ]
    
    def get_margins(self) -> Dict:
        """Get account margins."""
        if self.is_live:
            return self.kite.get_margins()
        else:
            # Paper trading margins
            return {
                "equity": {
                    "available": {
                        "cash": 100000.0  # Default paper trading capital
                    },
                    "used": {
                        "exposure": sum(
                            p["entry_price"] * p["quantity"]
                            for p in self._paper_positions.values()
                            if p["status"] == "open"
                        )
                    }
                }
            }


# Singleton
_order_service: Optional[OrderService] = None


def get_order_service() -> OrderService:
    """Get the order service singleton."""
    global _order_service
    if _order_service is None:
        _order_service = OrderService()
    return _order_service
