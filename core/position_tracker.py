"""Position and order tracking system."""

import logging
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional

from core.config import get_config, TradingMode
from core.models import (
    BreakoutSignal, Order, OrderSide, OrderStatus, OrderType,
    Position, ProductType, SignalType, TradeResult
)
from data.kite_client import get_kite_client

logger = logging.getLogger(__name__)


class OrderManager:
    """Manages order placement, tracking, and modifications."""
    
    def __init__(self):
        self.config = get_config()
        self._pending_orders: Dict[str, Order] = {}
        self._completed_orders: Dict[str, Order] = {}
        self._order_callbacks: List[Callable[[Order], None]] = []
    
    def place_entry_order(
        self,
        signal: BreakoutSignal,
        quantity: int,
        order_type: OrderType = OrderType.MARKET
    ) -> Optional[str]:
        """
        Place entry order for a signal.
        
        Args:
            signal: Breakout signal.
            quantity: Order quantity.
            order_type: Order type (MARKET or LIMIT).
        
        Returns:
            Order ID if successful.
        """
        side = OrderSide.BUY if signal.signal_type in [
            SignalType.BREAKOUT_LONG, SignalType.ORB_LONG
        ] else OrderSide.SELL
        
        if self.config.mode == TradingMode.PAPER:
            order_id = self._place_paper_order(
                symbol=signal.symbol,
                side=side,
                quantity=quantity,
                price=signal.entry_price,
                order_type=order_type
            )
        else:
            kite = get_kite_client()
            order_id = kite.place_order(
                symbol=signal.symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                product=ProductType.MIS,
                price=signal.entry_price if order_type == OrderType.LIMIT else 0,
                tag=f"ENTRY_{signal.signal_type.value}"
            )
        
        if order_id:
            logger.info(
                f"Entry order placed: {order_id} | {side.value} {quantity} "
                f"{signal.symbol} @ {signal.entry_price}"
            )
        
        return order_id
    
    def place_sl_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        trigger_price: float,
        order_id_tag: str = ""
    ) -> Optional[str]:
        """Place stop loss order."""
        # For SL, we need opposite side
        sl_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        
        if self.config.mode == TradingMode.PAPER:
            order_id = self._place_paper_order(
                symbol=symbol,
                side=sl_side,
                quantity=quantity,
                price=trigger_price,
                order_type=OrderType.SL_M,
                trigger_price=trigger_price
            )
        else:
            kite = get_kite_client()
            order_id = kite.place_order(
                symbol=symbol,
                side=sl_side,
                quantity=quantity,
                order_type=OrderType.SL_M,
                product=ProductType.MIS,
                trigger_price=trigger_price,
                tag=f"SL_{order_id_tag}"
            )
        
        if order_id:
            logger.info(f"SL order placed: {order_id} | {symbol} @ {trigger_price}")
        
        return order_id
    
    def place_target_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        order_id_tag: str = ""
    ) -> Optional[str]:
        """Place target/profit booking order."""
        # For target, we need opposite side
        target_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        
        if self.config.mode == TradingMode.PAPER:
            order_id = self._place_paper_order(
                symbol=symbol,
                side=target_side,
                quantity=quantity,
                price=price,
                order_type=OrderType.LIMIT
            )
        else:
            kite = get_kite_client()
            order_id = kite.place_order(
                symbol=symbol,
                side=target_side,
                quantity=quantity,
                order_type=OrderType.LIMIT,
                product=ProductType.MIS,
                price=price,
                tag=f"TARGET_{order_id_tag}"
            )
        
        if order_id:
            logger.info(f"Target order placed: {order_id} | {symbol} @ {price}")
        
        return order_id
    
    def modify_sl_order(
        self,
        order_id: str,
        new_trigger_price: float
    ) -> bool:
        """Modify stop loss order trigger price."""
        if self.config.mode == TradingMode.PAPER:
            if order_id in self._pending_orders:
                self._pending_orders[order_id].trigger_price = new_trigger_price
                self._pending_orders[order_id].price = new_trigger_price
                logger.info(f"Paper SL modified: {order_id} -> {new_trigger_price}")
                return True
            return False
        else:
            kite = get_kite_client()
            return kite.modify_order(
                order_id=order_id,
                trigger_price=new_trigger_price
            )
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        if self.config.mode == TradingMode.PAPER:
            if order_id in self._pending_orders:
                order = self._pending_orders.pop(order_id)
                order.status = OrderStatus.CANCELLED
                self._completed_orders[order_id] = order
                logger.info(f"Paper order cancelled: {order_id}")
                return True
            return False
        else:
            kite = get_kite_client()
            return kite.cancel_order(order_id)
    
    def place_square_off_order(
        self,
        position: Position
    ) -> Optional[str]:
        """Place market order to square off a position."""
        side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
        
        if self.config.mode == TradingMode.PAPER:
            order_id = self._place_paper_order(
                symbol=position.symbol,
                side=side,
                quantity=position.quantity,
                price=position.current_price,
                order_type=OrderType.MARKET
            )
        else:
            kite = get_kite_client()
            order_id = kite.place_order(
                symbol=position.symbol,
                side=side,
                quantity=position.quantity,
                order_type=OrderType.MARKET,
                product=ProductType.MIS,
                tag="SQUARE_OFF"
            )
        
        if order_id:
            logger.info(
                f"Square-off order placed: {order_id} | {position.symbol} "
                f"qty={position.quantity}"
            )
        
        return order_id
    
    def _place_paper_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        order_type: OrderType,
        trigger_price: float = 0.0
    ) -> str:
        """Place a simulated paper order."""
        order_id = f"PAPER_{uuid.uuid4().hex[:8].upper()}"
        
        order = Order(
            order_id=order_id,
            symbol=symbol,
            instrument_token=0,  # Paper trading
            side=side,
            quantity=quantity,
            order_type=order_type,
            product=ProductType.MIS,
            price=price,
            trigger_price=trigger_price,
            status=OrderStatus.COMPLETE if order_type == OrderType.MARKET else OrderStatus.OPEN,
            filled_quantity=quantity if order_type == OrderType.MARKET else 0,
            average_price=price if order_type == OrderType.MARKET else 0,
            placed_at=datetime.now(),
            completed_at=datetime.now() if order_type == OrderType.MARKET else None
        )
        
        if order_type == OrderType.MARKET:
            self._completed_orders[order_id] = order
        else:
            self._pending_orders[order_id] = order
        
        return order_id
    
    def check_paper_orders(self, current_prices: Dict[str, float]):
        """
        Check and execute paper orders based on current prices.
        Call this regularly with latest prices.
        """
        orders_to_execute = []
        
        for order_id, order in self._pending_orders.items():
            current_price = current_prices.get(order.symbol)
            if current_price is None:
                continue
            
            should_execute = False
            
            if order.order_type == OrderType.LIMIT:
                # Limit buy fills at or below limit price
                # Limit sell fills at or above limit price
                if order.side == OrderSide.BUY and current_price <= order.price:
                    should_execute = True
                elif order.side == OrderSide.SELL and current_price >= order.price:
                    should_execute = True
            
            elif order.order_type in [OrderType.SL, OrderType.SL_M]:
                # SL buy triggers when price goes above trigger
                # SL sell triggers when price goes below trigger
                if order.side == OrderSide.BUY and current_price >= order.trigger_price:
                    should_execute = True
                elif order.side == OrderSide.SELL and current_price <= order.trigger_price:
                    should_execute = True
            
            if should_execute:
                orders_to_execute.append((order_id, current_price))
        
        # Execute orders
        for order_id, exec_price in orders_to_execute:
            order = self._pending_orders.pop(order_id)
            order.status = OrderStatus.COMPLETE
            order.filled_quantity = order.quantity
            order.average_price = exec_price
            order.completed_at = datetime.now()
            self._completed_orders[order_id] = order
            
            logger.info(
                f"Paper order executed: {order_id} | {order.side.value} "
                f"{order.quantity} {order.symbol} @ {exec_price}"
            )
            
            # Notify callbacks
            for callback in self._order_callbacks:
                try:
                    callback(order)
                except Exception as e:
                    logger.error(f"Order callback error: {e}")
    
    def register_order_callback(self, callback: Callable[[Order], None]):
        """Register callback for order execution events."""
        self._order_callbacks.append(callback)
    
    def get_pending_orders(self) -> List[Order]:
        """Get all pending orders."""
        return list(self._pending_orders.values())
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        return self._pending_orders.get(order_id) or self._completed_orders.get(order_id)


class PositionTracker:
    """Tracks and manages active trading positions."""
    
    def __init__(self, order_manager: OrderManager):
        self.order_manager = order_manager
        self._positions: Dict[str, Position] = {}
        self._trade_history: List[TradeResult] = []
        self._position_callbacks: List[Callable[[Position, str], None]] = []
        
        # Database integration
        from data.database import get_database
        self._db = get_database()
        
        # Load persisted positions
        self._load_positions()
        
        # Register for order callbacks
        order_manager.register_order_callback(self._on_order_executed)
    
    def _load_positions(self):
        """Load positions from database on startup."""
        try:
            from data.database import PositionRecord
            db_positions = self._db.get_positions(trading_style="intraday")
            
            for db_pos in db_positions:
                position = Position(
                    symbol=db_pos.symbol,
                    instrument_token=0,
                    side=OrderSide.BUY if db_pos.side == "BUY" else OrderSide.SELL,
                    quantity=db_pos.quantity,
                    entry_price=db_pos.entry_price,
                    current_price=db_pos.current_price,
                    stop_loss=db_pos.stop_loss,
                    target=db_pos.target,
                    product=ProductType.MIS,
                    entry_time=datetime.fromisoformat(db_pos.entry_time),
                    entry_order_id=db_pos.entry_order_id,
                    sl_order_id=db_pos.sl_order_id
                )
                self._positions[db_pos.symbol] = position
            
            if db_positions:
                logger.info(f"Loaded {len(db_positions)} intraday positions from database")
        except Exception as e:
            logger.warning(f"Could not load positions from database: {e}")
    
    def _save_position_to_db(self, position: Position):
        """Save a position to database."""
        try:
            from data.database import PositionRecord
            record = PositionRecord(
                symbol=position.symbol,
                side=position.side.value,
                quantity=position.quantity,
                entry_price=position.entry_price,
                current_price=position.current_price,
                stop_loss=position.stop_loss,
                target=position.target,
                entry_time=position.entry_time.isoformat(),
                trading_style="intraday",
                signal_type="",
                entry_order_id=position.entry_order_id or "",
                sl_order_id=position.sl_order_id or ""
            )
            self._db.save_position(record)
        except Exception as e:
            logger.error(f"Failed to save position to database: {e}")
    
    def open_position(
        self,
        signal: BreakoutSignal,
        quantity: int,
        entry_order_id: str,
        entry_price: float
    ) -> Position:
        """
        Open a new position after entry order fills.
        
        Args:
            signal: The breakout signal.
            quantity: Position quantity.
            entry_order_id: Entry order ID.
            entry_price: Actual entry price (from fill).
        
        Returns:
            The new Position object.
        """
        side = OrderSide.BUY if signal.signal_type in [
            SignalType.BREAKOUT_LONG, SignalType.ORB_LONG
        ] else OrderSide.SELL
        
        position = Position(
            symbol=signal.symbol,
            instrument_token=0,  # Set from order if available
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=signal.stop_loss,
            target=signal.target,
            product=ProductType.MIS,
            entry_time=datetime.now(),
            entry_order_id=entry_order_id
        )
        
        self._positions[signal.symbol] = position
        
        # Place SL and target orders
        sl_order_id = self.order_manager.place_sl_order(
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            trigger_price=signal.stop_loss,
            order_id_tag=entry_order_id
        )
        
        target_order_id = self.order_manager.place_target_order(
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            price=signal.target,
            order_id_tag=entry_order_id
        )
        
        position.sl_order_id = sl_order_id
        position.target_order_id = target_order_id
        
        # Save to database
        self._save_position_to_db(position)
        
        logger.info(
            f"Position opened: {signal.symbol} | {side.value} {quantity} @ "
            f"{entry_price} | SL: {signal.stop_loss} | Target: {signal.target}"
        )
        
        self._notify_callbacks(position, "opened")
        
        return position
    
    def update_price(self, symbol: str, current_price: float):
        """Update current price for a position."""
        if symbol in self._positions:
            self._positions[symbol].current_price = current_price
    
    def update_prices(self, prices: Dict[str, float]):
        """Update prices for all positions."""
        for symbol, price in prices.items():
            self.update_price(symbol, price)
        
        # Check paper orders
        if get_config().mode == TradingMode.PAPER:
            self.order_manager.check_paper_orders(prices)
    
    def move_sl_to_breakeven(self, symbol: str) -> bool:
        """Move stop loss to breakeven for a position."""
        position = self._positions.get(symbol)
        if not position or position.is_sl_at_breakeven:
            return False
        
        new_sl = position.entry_price
        
        if position.sl_order_id:
            success = self.order_manager.modify_sl_order(
                position.sl_order_id,
                new_sl
            )
            
            if success:
                position.stop_loss = new_sl
                position.is_sl_at_breakeven = True
                logger.info(f"SL moved to breakeven for {symbol} @ {new_sl}")
                self._notify_callbacks(position, "sl_moved")
                return True
        
        return False
    
    def close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str
    ) -> Optional[TradeResult]:
        """
        Close a position and record the trade.
        
        Args:
            symbol: Position symbol.
            exit_price: Exit price.
            exit_reason: Reason for exit (target, stop_loss, square_off, manual).
        
        Returns:
            TradeResult if position existed.
        """
        position = self._positions.pop(symbol, None)
        if not position:
            return None
        
        # Cancel any remaining orders
        if position.sl_order_id:
            self.order_manager.cancel_order(position.sl_order_id)
        if position.target_order_id:
            self.order_manager.cancel_order(position.target_order_id)
        
        # Calculate P&L
        if position.side == OrderSide.BUY:
            pnl = (exit_price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - exit_price) * position.quantity
        
        result = TradeResult(
            trade_id=f"TRADE_{uuid.uuid4().hex[:8].upper()}",
            symbol=symbol,
            side=position.side,
            quantity=position.quantity,
            entry_price=position.entry_price,
            exit_price=exit_price,
            entry_time=position.entry_time,
            exit_time=datetime.now(),
            pnl=pnl,
            exit_reason=exit_reason,
            signal_type=SignalType.BREAKOUT_LONG  # Could be stored in position
        )
        
        self._trade_history.append(result)
        
        # Save trade to database and remove position
        try:
            from data.database import TradeRecord
            trade_record = TradeRecord(
                symbol=symbol,
                side=position.side.value,
                quantity=position.quantity,
                entry_price=position.entry_price,
                exit_price=exit_price,
                entry_time=position.entry_time.isoformat(),
                exit_time=datetime.now().isoformat(),
                pnl=pnl,
                pnl_percent=(pnl / (position.entry_price * position.quantity)) * 100,
                signal_type=result.signal_type.value if result.signal_type else "",
                trading_style="intraday",
                exit_reason=exit_reason,
                holding_duration=str(datetime.now() - position.entry_time)
            )
            self._db.save_trade(trade_record)
            self._db.delete_position(symbol)
        except Exception as e:
            logger.error(f"Failed to save trade to database: {e}")
        
        logger.info(
            f"Position closed: {symbol} | Exit: {exit_reason} @ {exit_price} | "
            f"P&L: {pnl:.2f}"
        )
        
        self._notify_callbacks(position, "closed")
        
        return result
    
    def square_off_all(self, prices: Dict[str, float]) -> List[TradeResult]:
        """Square off all positions at current prices."""
        results = []
        
        symbols = list(self._positions.keys())
        for symbol in symbols:
            price = prices.get(symbol)
            if price:
                # Place square-off order
                position = self._positions[symbol]
                self.order_manager.place_square_off_order(position)
                
                result = self.close_position(symbol, price, "square_off")
                if result:
                    results.append(result)
        
        logger.info(f"Squared off {len(results)} positions")
        return results
    
    def _on_order_executed(self, order: Order):
        """Handle order execution callback."""
        # Check if this is a SL or target order for any position
        for symbol, position in list(self._positions.items()):
            if order.order_id == position.sl_order_id:
                self.close_position(symbol, order.average_price, "stop_loss")
            elif order.order_id == position.target_order_id:
                self.close_position(symbol, order.average_price, "target")
    
    def _notify_callbacks(self, position: Position, event: str):
        """Notify registered callbacks."""
        for callback in self._position_callbacks:
            try:
                callback(position, event)
            except Exception as e:
                logger.error(f"Position callback error: {e}")
    
    def register_callback(self, callback: Callable[[Position, str], None]):
        """Register callback for position events."""
        self._position_callbacks.append(callback)
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position by symbol."""
        return self._positions.get(symbol)
    
    def get_all_positions(self) -> List[Position]:
        """Get all active positions."""
        return list(self._positions.values())
    
    def get_trade_history(self) -> List[TradeResult]:
        """Get trade history."""
        return self._trade_history.copy()
    
    def get_total_pnl(self) -> float:
        """Get total P&L from all closed trades."""
        return sum(t.pnl for t in self._trade_history)
    
    def get_unrealized_pnl(self) -> float:
        """Get unrealized P&L from open positions."""
        return sum(p.pnl for p in self._positions.values())


# Singleton instances
_order_manager: Optional[OrderManager] = None
_position_tracker: Optional[PositionTracker] = None


def get_order_manager() -> OrderManager:
    """Get singleton order manager."""
    global _order_manager
    if _order_manager is None:
        _order_manager = OrderManager()
    return _order_manager


def get_position_tracker() -> PositionTracker:
    """Get singleton position tracker."""
    global _position_tracker
    if _position_tracker is None:
        _position_tracker = PositionTracker(get_order_manager())
    return _position_tracker
