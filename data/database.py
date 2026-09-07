"""SQLite database for trade persistence and history tracking."""

import sqlite3
import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Dict, Any
from contextlib import contextmanager
from dataclasses import dataclass, asdict, fields

logger = logging.getLogger(__name__)

# Database file path
DB_PATH = Path(__file__).parent.parent / "trading_data.db"


@dataclass
class TradeRecord:
    """Record of a completed trade."""
    id: Optional[int] = None
    symbol: str = ""
    side: str = ""  # BUY or SELL
    quantity: int = 0
    entry_price: float = 0.0
    exit_price: float = 0.0
    entry_time: str = ""
    exit_time: str = ""
    pnl: float = 0.0
    pnl_percent: float = 0.0
    signal_type: str = ""
    trading_style: str = ""  # intraday or swing
    exit_reason: str = ""  # target, stop_loss, manual, square_off
    holding_duration: str = ""
    notes: str = ""


@dataclass
class PositionRecord:
    """Record of an open position."""
    id: Optional[int] = None
    symbol: str = ""
    side: str = ""
    quantity: int = 0
    entry_price: float = 0.0
    current_price: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    target_2: Optional[float] = None
    target_3: Optional[float] = None
    entry_time: str = ""
    trading_style: str = ""
    signal_type: str = ""
    entry_order_id: str = ""
    sl_order_id: str = ""
    sector: str = ""
    is_trailing_active: bool = False
    partial_exits: int = 0


@dataclass
class DailyPnLRecord:
    """Daily P&L tracking."""
    id: Optional[int] = None
    date: str = ""
    trading_style: str = ""
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    trades_taken: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    max_drawdown: float = 0.0
    capital_used: float = 0.0


@dataclass
class OrderRecord:
    """Record of an order."""
    id: Optional[int] = None
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: int = 0
    order_type: str = ""  # MARKET, LIMIT, SL, SL-M
    price: float = 0.0
    trigger_price: float = 0.0
    status: str = ""  # PENDING, COMPLETE, CANCELLED, REJECTED
    trading_style: str = ""
    created_at: str = ""
    updated_at: str = ""
    exchange_order_id: str = ""
    message: str = ""


class TradingDatabase:
    """SQLite database manager for trading data."""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self._init_database()
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_database(self):
        """Initialize database tables."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Trades table - completed trades history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    pnl REAL NOT NULL,
                    pnl_percent REAL NOT NULL,
                    signal_type TEXT,
                    trading_style TEXT NOT NULL,
                    exit_reason TEXT,
                    holding_duration TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Positions table - open positions
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL UNIQUE,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    target REAL NOT NULL,
                    target_2 REAL,
                    target_3 REAL,
                    entry_time TEXT NOT NULL,
                    trading_style TEXT NOT NULL,
                    signal_type TEXT,
                    entry_order_id TEXT,
                    sl_order_id TEXT,
                    sector TEXT,
                    is_trailing_active INTEGER DEFAULT 0,
                    partial_exits INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Daily P&L table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_pnl (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    trading_style TEXT NOT NULL,
                    realized_pnl REAL DEFAULT 0,
                    unrealized_pnl REAL DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    trades_taken INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    max_drawdown REAL DEFAULT 0,
                    capital_used REAL DEFAULT 0,
                    UNIQUE(date, trading_style)
                )
            """)
            
            # Orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    order_type TEXT NOT NULL,
                    price REAL DEFAULT 0,
                    trigger_price REAL DEFAULT 0,
                    status TEXT NOT NULL,
                    trading_style TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    exchange_order_id TEXT,
                    message TEXT
                )
            """)
            
            # Signals table - for signal history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    target REAL NOT NULL,
                    confidence REAL,
                    volume_ratio REAL,
                    trading_style TEXT NOT NULL,
                    was_taken INTEGER DEFAULT 0,
                    outcome TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(exit_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_style ON trades(trading_style)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_style ON positions(trading_style)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_pnl_date ON daily_pnl(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)")
            
            logger.info(f"Database initialized at {self.db_path}")
    
    # ==================== Trade Operations ====================
    
    def save_trade(self, trade: TradeRecord) -> int:
        """Save a completed trade."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades (
                    symbol, side, quantity, entry_price, exit_price,
                    entry_time, exit_time, pnl, pnl_percent, signal_type,
                    trading_style, exit_reason, holding_duration, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.symbol, trade.side, trade.quantity, trade.entry_price,
                trade.exit_price, trade.entry_time, trade.exit_time,
                trade.pnl, trade.pnl_percent, trade.signal_type,
                trade.trading_style, trade.exit_reason, trade.holding_duration,
                trade.notes
            ))
            trade_id = cursor.lastrowid
            logger.info(f"Saved trade {trade_id}: {trade.symbol} {trade.side} P&L={trade.pnl:.2f}")
            return trade_id
    
    def get_trades(
        self,
        symbol: Optional[str] = None,
        trading_style: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> List[TradeRecord]:
        """Get trade history with filters."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM trades WHERE 1=1"
            params = []
            
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            if trading_style:
                query += " AND trading_style = ?"
                params.append(trading_style)
            if start_date:
                query += " AND exit_time >= ?"
                params.append(start_date)
            if end_date:
                query += " AND exit_time <= ?"
                params.append(end_date)
            
            query += " ORDER BY exit_time DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Filter to only fields that TradeRecord accepts
            trade_fields = {f.name for f in fields(TradeRecord)}
            return [
                TradeRecord(**{k: v for k, v in dict(row).items() if k in trade_fields})
                for row in rows
            ]
    
    def get_trade_stats(
        self,
        trading_style: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get aggregated trade statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                    SUM(pnl) as total_pnl,
                    AVG(pnl) as avg_pnl,
                    AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
                    AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss,
                    MAX(pnl) as best_trade,
                    MIN(pnl) as worst_trade
                FROM trades WHERE 1=1
            """
            params = []
            
            if trading_style:
                query += " AND trading_style = ?"
                params.append(trading_style)
            if start_date:
                query += " AND exit_time >= ?"
                params.append(start_date)
            if end_date:
                query += " AND exit_time <= ?"
                params.append(end_date)
            
            cursor.execute(query, params)
            row = cursor.fetchone()
            
            if row and row['total_trades'] > 0:
                win_rate = (row['winning_trades'] / row['total_trades']) * 100
                avg_win = row['avg_win'] or 0
                avg_loss = abs(row['avg_loss'] or 1)
                profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
                
                return {
                    'total_trades': row['total_trades'],
                    'winning_trades': row['winning_trades'],
                    'losing_trades': row['losing_trades'],
                    'win_rate': win_rate,
                    'total_pnl': row['total_pnl'] or 0,
                    'avg_pnl': row['avg_pnl'] or 0,
                    'avg_win': avg_win,
                    'avg_loss': row['avg_loss'] or 0,
                    'profit_factor': profit_factor,
                    'best_trade': row['best_trade'] or 0,
                    'worst_trade': row['worst_trade'] or 0
                }
            
            return {
                'total_trades': 0, 'winning_trades': 0, 'losing_trades': 0,
                'win_rate': 0, 'total_pnl': 0, 'avg_pnl': 0,
                'avg_win': 0, 'avg_loss': 0, 'profit_factor': 0,
                'best_trade': 0, 'worst_trade': 0
            }
    
    # ==================== Position Operations ====================
    
    def save_position(self, position: PositionRecord) -> int:
        """Save or update an open position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO positions (
                    symbol, side, quantity, entry_price, current_price,
                    stop_loss, target, target_2, target_3, entry_time,
                    trading_style, signal_type, entry_order_id, sl_order_id,
                    sector, is_trailing_active, partial_exits, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position.symbol, position.side, position.quantity,
                position.entry_price, position.current_price,
                position.stop_loss, position.target, position.target_2,
                position.target_3, position.entry_time, position.trading_style,
                position.signal_type, position.entry_order_id, position.sl_order_id,
                position.sector, int(position.is_trailing_active),
                position.partial_exits, datetime.now().isoformat()
            ))
            logger.info(f"Saved position: {position.symbol} {position.side}")
            return cursor.lastrowid
    
    def get_positions(self, trading_style: Optional[str] = None) -> List[PositionRecord]:
        """Get all open positions."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if trading_style:
                cursor.execute(
                    "SELECT * FROM positions WHERE trading_style = ?",
                    (trading_style,)
                )
            else:
                cursor.execute("SELECT * FROM positions")
            
            rows = cursor.fetchall()
            positions = []
            for row in rows:
                pos = PositionRecord(
                    id=row['id'],
                    symbol=row['symbol'],
                    side=row['side'],
                    quantity=row['quantity'],
                    entry_price=row['entry_price'],
                    current_price=row['current_price'],
                    stop_loss=row['stop_loss'],
                    target=row['target'],
                    target_2=row['target_2'],
                    target_3=row['target_3'],
                    entry_time=row['entry_time'],
                    trading_style=row['trading_style'],
                    signal_type=row['signal_type'],
                    entry_order_id=row['entry_order_id'] or '',
                    sl_order_id=row['sl_order_id'] or '',
                    sector=row['sector'] or '',
                    is_trailing_active=bool(row['is_trailing_active']),
                    partial_exits=row['partial_exits'] or 0
                )
                positions.append(pos)
            return positions
    
    def get_position(self, symbol: str) -> Optional[PositionRecord]:
        """Get a specific position by symbol."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            
            if row:
                return PositionRecord(
                    id=row['id'],
                    symbol=row['symbol'],
                    side=row['side'],
                    quantity=row['quantity'],
                    entry_price=row['entry_price'],
                    current_price=row['current_price'],
                    stop_loss=row['stop_loss'],
                    target=row['target'],
                    target_2=row['target_2'],
                    target_3=row['target_3'],
                    entry_time=row['entry_time'],
                    trading_style=row['trading_style'],
                    signal_type=row['signal_type'],
                    entry_order_id=row['entry_order_id'] or '',
                    sl_order_id=row['sl_order_id'] or '',
                    sector=row['sector'] or '',
                    is_trailing_active=bool(row['is_trailing_active']),
                    partial_exits=row['partial_exits'] or 0
                )
            return None
    
    def update_position_price(self, symbol: str, current_price: float):
        """Update current price of a position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE positions 
                SET current_price = ?, updated_at = ?
                WHERE symbol = ?
            """, (current_price, datetime.now().isoformat(), symbol))
    
    def update_position_sl(self, symbol: str, stop_loss: float, is_trailing: bool = False):
        """Update stop loss of a position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE positions 
                SET stop_loss = ?, is_trailing_active = ?, updated_at = ?
                WHERE symbol = ?
            """, (stop_loss, int(is_trailing), datetime.now().isoformat(), symbol))
    
    def delete_position(self, symbol: str):
        """Delete a position (when closed)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
            logger.info(f"Deleted position: {symbol}")
    
    def clear_intraday_positions(self):
        """Clear all intraday positions (for square-off)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM positions WHERE trading_style = 'intraday'")
            logger.info("Cleared all intraday positions")
    
    # ==================== Daily P&L Operations ====================
    
    def save_daily_pnl(self, record: DailyPnLRecord):
        """Save or update daily P&L record."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO daily_pnl (
                    date, trading_style, realized_pnl, unrealized_pnl,
                    total_pnl, trades_taken, winning_trades, losing_trades,
                    max_drawdown, capital_used
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.date, record.trading_style, record.realized_pnl,
                record.unrealized_pnl, record.total_pnl, record.trades_taken,
                record.winning_trades, record.losing_trades,
                record.max_drawdown, record.capital_used
            ))
    
    def get_daily_pnl(
        self,
        trading_style: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[DailyPnLRecord]:
        """Get daily P&L history."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM daily_pnl WHERE 1=1"
            params = []
            
            if trading_style:
                query += " AND trading_style = ?"
                params.append(trading_style)
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            
            query += " ORDER BY date DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [DailyPnLRecord(**dict(row)) for row in rows]
    
    def get_today_pnl(self, trading_style: str) -> Optional[DailyPnLRecord]:
        """Get today's P&L record."""
        today = date.today().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM daily_pnl WHERE date = ? AND trading_style = ?",
                (today, trading_style)
            )
            row = cursor.fetchone()
            if row:
                return DailyPnLRecord(**dict(row))
            return None
    
    # ==================== Order Operations ====================
    
    def save_order(self, order: OrderRecord) -> int:
        """Save or update an order."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO orders (
                    order_id, symbol, side, quantity, order_type,
                    price, trigger_price, status, trading_style,
                    created_at, updated_at, exchange_order_id, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.order_id, order.symbol, order.side, order.quantity,
                order.order_type, order.price, order.trigger_price,
                order.status, order.trading_style, order.created_at,
                datetime.now().isoformat(), order.exchange_order_id, order.message
            ))
            return cursor.lastrowid
    
    def update_order_status(self, order_id: str, status: str, message: str = ""):
        """Update order status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE orders 
                SET status = ?, message = ?, updated_at = ?
                WHERE order_id = ?
            """, (status, message, datetime.now().isoformat(), order_id))
    
    def get_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        trading_style: Optional[str] = None,
        limit: int = 50
    ) -> List[OrderRecord]:
        """Get order history."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM orders WHERE 1=1"
            params = []
            
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            if status:
                query += " AND status = ?"
                params.append(status)
            if trading_style:
                query += " AND trading_style = ?"
                params.append(trading_style)
            
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [OrderRecord(**dict(row)) for row in rows]
    
    # ==================== Signal Operations ====================
    
    def save_signal(
        self,
        symbol: str,
        signal_type: str,
        entry_price: float,
        stop_loss: float,
        target: float,
        trading_style: str,
        confidence: float = 0.0,
        volume_ratio: float = 0.0
    ) -> int:
        """Save a generated signal."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO signals (
                    symbol, signal_type, entry_price, stop_loss, target,
                    confidence, volume_ratio, trading_style
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, signal_type, entry_price, stop_loss, target,
                confidence, volume_ratio, trading_style
            ))
            return cursor.lastrowid
    
    def update_signal_outcome(self, signal_id: int, was_taken: bool, outcome: str):
        """Update signal outcome after trade completion."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE signals SET was_taken = ?, outcome = ? WHERE id = ?
            """, (int(was_taken), outcome, signal_id))


# Singleton instance
_db: Optional[TradingDatabase] = None


def get_database() -> TradingDatabase:
    """Get singleton database instance."""
    global _db
    if _db is None:
        _db = TradingDatabase()
    return _db
