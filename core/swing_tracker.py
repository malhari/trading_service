"""Multi-day position tracker for swing trading with CNC support."""

import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.config import get_config, TradingMode
from core.models import Order, OrderSide, OrderStatus, OrderType, ProductType
from data.kite_client import get_kite_client
from risk.swing_risk import SwingPosition, SwingRiskGuard, get_swing_risk_guard
from strategies.swing_breakout import SwingSignal

logger = logging.getLogger(__name__)


class SwingOrderManager:
    """Order management for swing trades with CNC product type."""
    
    def __init__(self):
        self.config = get_config()
        self._pending_orders: Dict[str, Order] = {}
        self._order_history: List[Order] = []
    
    def place_entry_order(
        self,
        signal: SwingSignal,
        quantity: int
    ) -> Optional[str]:
        """
        Place CNC entry order for swing trade.
        
        Args:
            signal: Swing signal.
            quantity: Order quantity.
        
        Returns:
            Order ID if successful.
        """
        side = OrderSide.BUY if "LONG" in signal.signal_type or "BUY" in signal.signal_type else OrderSide.SELL
        
        if self.config.mode == TradingMode.PAPER:
            order_id = self._paper_order(
                symbol=signal.symbol,
                side=side,
                quantity=quantity,
                price=signal.entry_price,
                order_type=OrderType.LIMIT
            )
        else:
            kite = get_kite_client()
            # Use CNC for delivery-based swing trades
            order_id = kite.place_order(
                symbol=signal.symbol,
                side=side,
                quantity=quantity,
                order_type=OrderType.LIMIT,
                product=ProductType.CNC,  # CNC for swing
                price=signal.entry_price,
                tag=f"SWING_{signal.signal_type}"
            )
        
        if order_id:
            logger.info(
                f"Swing entry order: {order_id} | {side.value} {quantity} "
                f"{signal.symbol} @ {signal.entry_price} (CNC)"
            )
        
        return order_id
    
    def place_gtt_orders(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        stop_loss: float,
        target: float
    ) -> Dict[str, str]:
        """
        Place GTT (Good Till Triggered) orders for SL and target.
        GTT orders persist across sessions - ideal for swing trading.
        
        Args:
            symbol: Trading symbol.
            side: Position side (to place opposite side orders).
            quantity: Order quantity.
            stop_loss: Stop loss price.
            target: Target price.
        
        Returns:
            Dict with 'sl_gtt_id' and 'target_gtt_id'.
        """
        exit_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        
        result = {"sl_gtt_id": None, "target_gtt_id": None}
        
        if self.config.mode == TradingMode.PAPER:
            result["sl_gtt_id"] = f"GTT_SL_{symbol}_{datetime.now().strftime('%H%M%S')}"
            result["target_gtt_id"] = f"GTT_TGT_{symbol}_{datetime.now().strftime('%H%M%S')}"
            logger.info(f"Paper GTT orders created for {symbol}")
            return result
        
        kite = get_kite_client()
        
        try:
            # GTT for stop loss
            if side == OrderSide.BUY:
                # SL trigger when price falls below stop_loss
                sl_trigger = {"trigger_values": [stop_loss], "last_price": stop_loss * 1.01}
            else:
                # SL trigger when price rises above stop_loss
                sl_trigger = {"trigger_values": [stop_loss], "last_price": stop_loss * 0.99}
            
            # Note: Kite GTT API requires specific format
            # This is a simplified version - production would use kite.place_gtt()
            logger.info(f"GTT SL order would be placed: {symbol} @ {stop_loss}")
            result["sl_gtt_id"] = f"GTT_SL_{symbol}"
            
            logger.info(f"GTT Target order would be placed: {symbol} @ {target}")
            result["target_gtt_id"] = f"GTT_TGT_{symbol}"
            
        except Exception as e:
            logger.error(f"Failed to place GTT orders: {e}")
        
        return result
    
    def modify_gtt_sl(
        self,
        gtt_id: str,
        new_trigger: float
    ) -> bool:
        """Modify GTT stop loss trigger."""
        if self.config.mode == TradingMode.PAPER:
            logger.info(f"Paper GTT SL modified: {gtt_id} -> {new_trigger}")
            return True
        
        # Production would use kite.modify_gtt()
        logger.info(f"GTT SL would be modified: {gtt_id} -> {new_trigger}")
        return True
    
    def cancel_gtt(self, gtt_id: str) -> bool:
        """Cancel a GTT order."""
        if self.config.mode == TradingMode.PAPER:
            logger.info(f"Paper GTT cancelled: {gtt_id}")
            return True
        
        # Production would use kite.delete_gtt()
        logger.info(f"GTT would be cancelled: {gtt_id}")
        return True
    
    def place_exit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: Optional[float] = None
    ) -> Optional[str]:
        """Place exit order (market or limit)."""
        exit_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        order_type = OrderType.LIMIT if price else OrderType.MARKET
        
        if self.config.mode == TradingMode.PAPER:
            order_id = self._paper_order(
                symbol=symbol,
                side=exit_side,
                quantity=quantity,
                price=price or 0,
                order_type=order_type
            )
        else:
            kite = get_kite_client()
            order_id = kite.place_order(
                symbol=symbol,
                side=exit_side,
                quantity=quantity,
                order_type=order_type,
                product=ProductType.CNC,
                price=price if price else 0,
                tag="SWING_EXIT"
            )
        
        if order_id:
            logger.info(f"Swing exit order: {order_id} | {exit_side.value} {quantity} {symbol}")
        
        return order_id
    
    def _paper_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        order_type: OrderType
    ) -> str:
        """Create paper order."""
        order_id = f"SWING_PAPER_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        order = Order(
            order_id=order_id,
            symbol=symbol,
            instrument_token=0,
            side=side,
            quantity=quantity,
            order_type=order_type,
            product=ProductType.CNC,
            price=price,
            status=OrderStatus.COMPLETE if order_type == OrderType.MARKET else OrderStatus.OPEN,
            filled_quantity=quantity if order_type == OrderType.MARKET else 0,
            average_price=price,
            placed_at=datetime.now()
        )
        
        self._order_history.append(order)
        return order_id


class SwingPositionTracker:
    """Tracks swing positions across multiple days."""
    
    def __init__(
        self,
        order_manager: SwingOrderManager,
        risk_guard: SwingRiskGuard,
        persistence_file: str = "swing_positions.json"
    ):
        self.order_manager = order_manager
        self.risk_guard = risk_guard
        self.persistence_file = Path(persistence_file)
        
        self._position_callbacks: List[Callable[[SwingPosition, str], None]] = []
        
        # Database integration
        from data.database import get_database
        self._db = get_database()
        
        # Load persisted positions (try database first, fallback to JSON)
        self._load_positions()
    
    def _load_positions(self):
        """Load positions from database (with JSON fallback)."""
        loaded_from_db = False
        
        # Try loading from database first
        try:
            db_positions = self._db.get_positions(trading_style="swing")
            
            for db_pos in db_positions:
                position = SwingPosition(
                    symbol=db_pos.symbol,
                    side=OrderSide(db_pos.side),
                    quantity=db_pos.quantity,
                    entry_price=db_pos.entry_price,
                    current_price=db_pos.current_price,
                    stop_loss=db_pos.stop_loss,
                    target_1=db_pos.target,
                    target_2=db_pos.target_2 or db_pos.target * 1.5,
                    target_3=db_pos.target_3 or db_pos.target * 2.5,
                    entry_date=date.fromisoformat(db_pos.entry_time.split('T')[0]),
                    entry_order_id=db_pos.entry_order_id,
                    sector=db_pos.sector or "unknown",
                    sl_order_id=db_pos.sl_order_id,
                    partial_exits=db_pos.partial_exits,
                    highest_price=db_pos.current_price,
                    lowest_price=db_pos.current_price,
                    is_trailing_sl_active=db_pos.is_trailing_active,
                    notes=""
                )
                self.risk_guard.add_position(position)
            
            if db_positions:
                logger.info(f"Loaded {len(db_positions)} swing positions from database")
                loaded_from_db = True
        except Exception as e:
            logger.warning(f"Could not load from database: {e}")
        
        # Fallback to JSON file if database was empty
        if not loaded_from_db and self.persistence_file.exists():
            try:
                with open(self.persistence_file, 'r') as f:
                    data = json.load(f)
                
                for pos_data in data.get("positions", []):
                    position = SwingPosition(
                        symbol=pos_data["symbol"],
                        side=OrderSide(pos_data["side"]),
                        quantity=pos_data["quantity"],
                        entry_price=pos_data["entry_price"],
                        current_price=pos_data["current_price"],
                        stop_loss=pos_data["stop_loss"],
                        target_1=pos_data["target_1"],
                        target_2=pos_data["target_2"],
                        target_3=pos_data["target_3"],
                        entry_date=date.fromisoformat(pos_data["entry_date"]),
                        entry_order_id=pos_data["entry_order_id"],
                        sector=pos_data.get("sector", "unknown"),
                        sl_order_id=pos_data.get("sl_order_id"),
                        partial_exits=pos_data.get("partial_exits", 0),
                        highest_price=pos_data.get("highest_price", pos_data["entry_price"]),
                        lowest_price=pos_data.get("lowest_price", pos_data["entry_price"]),
                        is_trailing_sl_active=pos_data.get("is_trailing_sl_active", False),
                        notes=pos_data.get("notes", "")
                    )
                    self.risk_guard.add_position(position)
                    
                    # Also save to database for future loads
                    self._save_position_to_db(position)
                
                logger.info(f"Loaded {len(data.get('positions', []))} swing positions from JSON (migrated to DB)")
                
            except Exception as e:
                logger.error(f"Failed to load positions from JSON: {e}")
    
    def _save_position_to_db(self, position: SwingPosition):
        """Save a swing position to database."""
        try:
            from data.database import PositionRecord
            record = PositionRecord(
                symbol=position.symbol,
                side=position.side.value,
                quantity=position.quantity,
                entry_price=position.entry_price,
                current_price=position.current_price,
                stop_loss=position.stop_loss,
                target=position.target_1,
                target_2=position.target_2,
                target_3=position.target_3,
                entry_time=position.entry_date.isoformat(),
                trading_style="swing",
                signal_type="",
                entry_order_id=position.entry_order_id or "",
                sl_order_id=position.sl_order_id or "",
                sector=position.sector,
                is_trailing_active=position.is_trailing_sl_active,
                partial_exits=position.partial_exits
            )
            self._db.save_position(record)
        except Exception as e:
            logger.error(f"Failed to save swing position to database: {e}")
    
    def _save_positions(self):
        """Save positions to persistence file and database."""
        try:
            positions = self.risk_guard.get_all_positions()
            
            # Save to JSON (backup)
            data = {
                "updated_at": datetime.now().isoformat(),
                "positions": [
                    {
                        "symbol": p.symbol,
                        "side": p.side.value,
                        "quantity": p.quantity,
                        "entry_price": p.entry_price,
                        "current_price": p.current_price,
                        "stop_loss": p.stop_loss,
                        "target_1": p.target_1,
                        "target_2": p.target_2,
                        "target_3": p.target_3,
                        "entry_date": p.entry_date.isoformat(),
                        "entry_order_id": p.entry_order_id,
                        "sector": p.sector,
                        "sl_order_id": p.sl_order_id,
                        "partial_exits": p.partial_exits,
                        "highest_price": p.highest_price,
                        "lowest_price": p.lowest_price,
                        "is_trailing_sl_active": p.is_trailing_sl_active,
                        "notes": p.notes
                    }
                    for p in positions
                ]
            }
            
            with open(self.persistence_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Save each position to database
            for p in positions:
                self._save_position_to_db(p)
            
            logger.debug(f"Saved {len(positions)} positions to JSON and database")
            
        except Exception as e:
            logger.error(f"Failed to save positions: {e}")
    
    def open_position(
        self,
        signal: SwingSignal,
        quantity: int,
        entry_order_id: str,
        entry_price: float
    ) -> SwingPosition:
        """
        Open a new swing position.
        
        Args:
            signal: Swing signal.
            quantity: Position quantity.
            entry_order_id: Entry order ID.
            entry_price: Actual entry price.
        
        Returns:
            New SwingPosition.
        """
        side = OrderSide.BUY if "LONG" in signal.signal_type or "BUY" in signal.signal_type else OrderSide.SELL
        
        position = SwingPosition(
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=signal.stop_loss,
            target_1=signal.target_1,
            target_2=signal.target_2,
            target_3=signal.target_3,
            entry_date=date.today(),
            entry_order_id=entry_order_id
        )
        
        # Place GTT orders for SL and target
        gtt_result = self.order_manager.place_gtt_orders(
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            stop_loss=signal.stop_loss,
            target=signal.target_1
        )
        
        position.sl_order_id = gtt_result.get("sl_gtt_id")
        
        # Add to risk guard
        self.risk_guard.add_position(position)
        
        # Persist
        self._save_positions()
        
        # Notify
        self._notify("opened", position)
        
        return position
    
    def update_prices(self, prices: Dict[str, float]):
        """Update current prices for all positions."""
        for symbol, price in prices.items():
            self.risk_guard.update_position_price(symbol, price)
        
        # Check for SL hits in paper mode
        if get_config().mode == TradingMode.PAPER:
            self._check_paper_exits(prices)
        
        # Persist updated positions
        self._save_positions()
    
    def _check_paper_exits(self, prices: Dict[str, float]):
        """Check for SL/target hits in paper trading."""
        positions = self.risk_guard.get_all_positions()
        
        for position in positions:
            price = prices.get(position.symbol)
            if not price:
                continue
            
            # Check stop loss
            if position.side == OrderSide.BUY:
                if price <= position.stop_loss:
                    self.close_position(position.symbol, price, "stop_loss")
                elif price >= position.target_1 and position.partial_exits == 0:
                    # Book partial profit at target 1
                    partial_qty = position.quantity // 3
                    if partial_qty > 0:
                        self.risk_guard.book_partial_profit(
                            position.symbol, partial_qty, price
                        )
            else:
                if price >= position.stop_loss:
                    self.close_position(position.symbol, price, "stop_loss")
                elif price <= position.target_1 and position.partial_exits == 0:
                    partial_qty = position.quantity // 3
                    if partial_qty > 0:
                        self.risk_guard.book_partial_profit(
                            position.symbol, partial_qty, price
                        )
    
    def close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str
    ) -> Optional[dict]:
        """
        Close a swing position.
        
        Args:
            symbol: Symbol to close.
            exit_price: Exit price.
            exit_reason: Reason for exit.
        
        Returns:
            Trade result dict.
        """
        position = self.risk_guard.get_position(symbol)
        if not position:
            return None
        
        # Cancel GTT orders
        if position.sl_order_id:
            self.order_manager.cancel_gtt(position.sl_order_id)
        
        # Place exit order
        self.order_manager.place_exit_order(
            symbol=symbol,
            side=position.side,
            quantity=position.quantity,
            price=exit_price
        )
        
        # Close in risk guard
        result = self.risk_guard.close_position(symbol, exit_price, exit_reason)
        
        # Save trade to database
        if result:
            try:
                from data.database import TradeRecord
                holding_days = (result.exit_time - result.entry_time).days
                trade_record = TradeRecord(
                    symbol=result.symbol,
                    side=position.side.value,
                    quantity=position.quantity,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    entry_time=result.entry_time.isoformat(),
                    exit_time=result.exit_time.isoformat(),
                    pnl=result.pnl,
                    pnl_percent=result.pnl_percent,
                    signal_type="",
                    trading_style="swing",
                    exit_reason=result.exit_reason,
                    holding_duration=f"{holding_days} days"
                )
                self._db.save_trade(trade_record)
                self._db.delete_position(symbol)
            except Exception as e:
                logger.error(f"Failed to save swing trade to database: {e}")
        
        # Persist to JSON (backup)
        self._save_positions()
        
        # Notify
        self._notify("closed", position)
        
        if result:
            return {
                "symbol": result.symbol,
                "pnl": result.pnl,
                "holding_days": (result.exit_time - result.entry_time).days,
                "exit_reason": result.exit_reason
            }
        
        return None
    
    def update_stop_loss(self, symbol: str, new_sl: float) -> bool:
        """Update stop loss for a position."""
        position = self.risk_guard.get_position(symbol)
        if not position:
            return False
        
        old_sl = position.stop_loss
        position.stop_loss = new_sl
        
        # Update GTT order
        if position.sl_order_id:
            self.order_manager.modify_gtt_sl(position.sl_order_id, new_sl)
        
        logger.info(f"SL updated: {symbol} | {old_sl:.2f} -> {new_sl:.2f}")
        
        self._save_positions()
        return True
    
    def get_daily_review(self) -> Dict:
        """Get daily review of all positions."""
        positions = self.risk_guard.get_all_positions()
        
        review = {
            "date": date.today().isoformat(),
            "total_positions": len(positions),
            "total_value": sum(p.position_value for p in positions),
            "unrealized_pnl": sum(p.pnl for p in positions),
            "positions_to_review": [],
            "positions_near_target": [],
            "positions_near_sl": []
        }
        
        for p in positions:
            # Check if approaching max holding days
            if p.holding_days >= 12:
                review["positions_to_review"].append({
                    "symbol": p.symbol,
                    "holding_days": p.holding_days,
                    "pnl_percent": p.pnl_percent
                })
            
            # Check if near target
            if p.side == OrderSide.BUY:
                distance_to_target = (p.target_1 - p.current_price) / p.current_price * 100
                distance_to_sl = (p.current_price - p.stop_loss) / p.current_price * 100
            else:
                distance_to_target = (p.current_price - p.target_1) / p.current_price * 100
                distance_to_sl = (p.stop_loss - p.current_price) / p.current_price * 100
            
            if distance_to_target < 2:
                review["positions_near_target"].append({
                    "symbol": p.symbol,
                    "distance_percent": distance_to_target
                })
            
            if distance_to_sl < 2:
                review["positions_near_sl"].append({
                    "symbol": p.symbol,
                    "distance_percent": distance_to_sl
                })
        
        return review
    
    def _notify(self, event: str, position: SwingPosition):
        """Notify callbacks."""
        for callback in self._position_callbacks:
            try:
                callback(position, event)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def register_callback(self, callback: Callable[[SwingPosition, str], None]):
        """Register position event callback."""
        self._position_callbacks.append(callback)


# Singletons
_swing_order_manager: Optional[SwingOrderManager] = None
_swing_position_tracker: Optional[SwingPositionTracker] = None


def get_swing_order_manager() -> SwingOrderManager:
    """Get singleton swing order manager."""
    global _swing_order_manager
    if _swing_order_manager is None:
        _swing_order_manager = SwingOrderManager()
    return _swing_order_manager


def get_swing_position_tracker() -> SwingPositionTracker:
    """Get singleton swing position tracker."""
    global _swing_position_tracker
    if _swing_position_tracker is None:
        _swing_position_tracker = SwingPositionTracker(
            order_manager=get_swing_order_manager(),
            risk_guard=get_swing_risk_guard()
        )
    return _swing_position_tracker
