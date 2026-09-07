"""Zerodha Kite Connect API wrapper."""

import logging
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional
from threading import Thread
import time

import pandas as pd
from kiteconnect import KiteConnect, KiteTicker

from core.config import get_config
from core.models import OHLC, Order, OrderSide, OrderStatus, OrderType, ProductType, Tick

logger = logging.getLogger(__name__)


class KiteClient:
    """Wrapper for Zerodha Kite Connect API."""
    
    def __init__(self):
        self.config = get_config()
        self.kite: Optional[KiteConnect] = None
        self.ticker: Optional[KiteTicker] = None
        self._access_token: Optional[str] = None
        self._instrument_map: Dict[str, int] = {}  # symbol -> token
        self._token_map: Dict[int, str] = {}  # token -> symbol
        self._tick_callbacks: List[Callable[[Tick], None]] = []
        self._is_connected = False
    
    def initialize(self, access_token: Optional[str] = None) -> bool:
        """
        Initialize Kite Connect with access token.
        
        Args:
            access_token: Pre-obtained access token. If None, will need manual login flow.
        
        Returns:
            True if initialization successful.
        """
        try:
            api_key = self.config.broker.api_key
            if not api_key:
                logger.error("KITE_API_KEY not configured")
                return False
            
            self.kite = KiteConnect(api_key=api_key)
            
            if access_token:
                self._access_token = access_token
                self.kite.set_access_token(access_token)
                logger.info("Kite Connect initialized with provided access token")
            else:
                # Generate login URL for manual authentication
                login_url = self.kite.login_url()
                logger.info(f"Please login at: {login_url}")
                logger.info("After login, call set_access_token() with the request_token")
                return False
            
            # Load instruments
            self._load_instruments()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Kite Connect: {e}")
            return False
    
    def generate_session(self, request_token: str) -> Optional[str]:
        """
        Generate access token from request token after login.
        
        Args:
            request_token: Token received after Kite login redirect.
        
        Returns:
            Access token if successful.
        """
        try:
            api_secret = self.config.broker.api_secret
            if not api_secret:
                logger.error("KITE_API_SECRET not configured")
                return None
            
            data = self.kite.generate_session(request_token, api_secret=api_secret)
            self._access_token = data["access_token"]
            self.kite.set_access_token(self._access_token)
            
            logger.info(f"Session generated successfully for user: {data.get('user_id')}")
            
            # Load instruments after successful authentication
            self._load_instruments()
            
            return self._access_token
            
        except Exception as e:
            logger.error(f"Failed to generate session: {e}")
            return None
    
    def _load_instruments(self):
        """Load NSE instruments mapping."""
        try:
            instruments = self.kite.instruments("NSE")
            
            for inst in instruments:
                symbol = inst["tradingsymbol"]
                token = inst["instrument_token"]
                self._instrument_map[symbol] = token
                self._token_map[token] = symbol
            
            logger.info(f"Loaded {len(self._instrument_map)} NSE instruments")
            
        except Exception as e:
            logger.error(f"Failed to load instruments: {e}")
    
    def get_instrument_token(self, symbol: str) -> Optional[int]:
        """Get instrument token for a symbol."""
        return self._instrument_map.get(symbol)
    
    def get_symbol(self, token: int) -> Optional[str]:
        """Get symbol for an instrument token."""
        return self._token_map.get(token)
    
    # ==================== Market Data ====================
    
    def get_quote(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Get live quotes for symbols.
        
        Args:
            symbols: List of trading symbols.
        
        Returns:
            Dict of symbol -> quote data.
        """
        try:
            # Convert symbols to exchange:symbol format
            instruments = [f"NSE:{s}" for s in symbols]
            quotes = self.kite.quote(instruments)
            
            # Convert to simpler format
            result = {}
            for key, data in quotes.items():
                symbol = key.split(":")[1]
                result[symbol] = {
                    "last_price": data["last_price"],
                    "open": data["ohlc"]["open"],
                    "high": data["ohlc"]["high"],
                    "low": data["ohlc"]["low"],
                    "close": data["ohlc"]["close"],
                    "volume": data["volume"],
                    "change": data["change"],
                }
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get quotes: {e}")
            return {}
    
    def get_historical_data(
        self,
        symbol: str,
        interval: str = "day",
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        days: int = 30
    ) -> pd.DataFrame:
        """
        Get historical OHLC data.
        
        Args:
            symbol: Trading symbol.
            interval: Candle interval (minute, 3minute, 5minute, 15minute, 30minute, 
                     60minute, day, week, month).
            from_date: Start date.
            to_date: End date.
            days: Number of days to fetch if dates not specified.
        
        Returns:
            DataFrame with OHLC data.
        """
        try:
            token = self.get_instrument_token(symbol)
            if not token:
                logger.error(f"Unknown symbol: {symbol}")
                return pd.DataFrame()
            
            if to_date is None:
                to_date = datetime.now()
            if from_date is None:
                from_date = to_date - timedelta(days=days)
            
            data = self.kite.historical_data(
                instrument_token=token,
                from_date=from_date,
                to_date=to_date,
                interval=interval,
                continuous=False,
                oi=False
            )
            
            if not data:
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            df["symbol"] = symbol
            df.rename(columns={"date": "timestamp"}, inplace=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to get historical data for {symbol}: {e}")
            return pd.DataFrame()
    
    def get_intraday_data(
        self,
        symbol: str,
        interval: str = "5minute",
        date: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        Get intraday OHLC data for a specific date.
        
        Args:
            symbol: Trading symbol.
            interval: Candle interval.
            date: Date for intraday data (defaults to today).
        
        Returns:
            DataFrame with intraday OHLC data.
        """
        if date is None:
            date = datetime.now()
        
        from_date = date.replace(hour=9, minute=15, second=0, microsecond=0)
        to_date = date.replace(hour=15, minute=30, second=0, microsecond=0)
        
        return self.get_historical_data(
            symbol=symbol,
            interval=interval,
            from_date=from_date,
            to_date=to_date
        )
    
    # ==================== WebSocket Streaming ====================
    
    def start_ticker(self, symbols: List[str]):
        """
        Start WebSocket ticker for real-time data.
        
        Args:
            symbols: List of symbols to subscribe.
        """
        try:
            tokens = [self.get_instrument_token(s) for s in symbols if self.get_instrument_token(s)]
            
            if not tokens:
                logger.error("No valid tokens to subscribe")
                return
            
            self.ticker = KiteTicker(
                api_key=self.config.broker.api_key,
                access_token=self._access_token
            )
            
            def on_ticks(ws, ticks):
                for tick_data in ticks:
                    tick = self._parse_tick(tick_data)
                    if tick:
                        for callback in self._tick_callbacks:
                            try:
                                callback(tick)
                            except Exception as e:
                                logger.error(f"Tick callback error: {e}")
            
            def on_connect(ws, response):
                logger.info("WebSocket connected")
                ws.subscribe(tokens)
                ws.set_mode(ws.MODE_FULL, tokens)
                self._is_connected = True
            
            def on_close(ws, code, reason):
                logger.warning(f"WebSocket closed: {code} - {reason}")
                self._is_connected = False
            
            def on_error(ws, code, reason):
                logger.error(f"WebSocket error: {code} - {reason}")
            
            def on_reconnect(ws, attempts_count):
                logger.info(f"WebSocket reconnecting... attempt {attempts_count}")
            
            self.ticker.on_ticks = on_ticks
            self.ticker.on_connect = on_connect
            self.ticker.on_close = on_close
            self.ticker.on_error = on_error
            self.ticker.on_reconnect = on_reconnect
            
            # Start in background thread
            ticker_thread = Thread(target=self.ticker.connect, daemon=True)
            ticker_thread.start()
            
            logger.info(f"Started ticker for {len(tokens)} symbols")
            
        except Exception as e:
            logger.error(f"Failed to start ticker: {e}")
    
    def stop_ticker(self):
        """Stop WebSocket ticker."""
        if self.ticker:
            self.ticker.close()
            self._is_connected = False
            logger.info("Ticker stopped")
    
    def register_tick_callback(self, callback: Callable[[Tick], None]):
        """Register a callback for tick data."""
        self._tick_callbacks.append(callback)
    
    def _parse_tick(self, tick_data: Dict) -> Optional[Tick]:
        """Parse raw tick data into Tick object."""
        try:
            token = tick_data.get("instrument_token")
            symbol = self.get_symbol(token)
            
            if not symbol:
                return None
            
            return Tick(
                symbol=symbol,
                instrument_token=token,
                last_price=tick_data.get("last_price", 0),
                volume=tick_data.get("volume_traded", 0),
                timestamp=tick_data.get("exchange_timestamp", datetime.now()),
                open=tick_data.get("ohlc", {}).get("open", 0),
                high=tick_data.get("ohlc", {}).get("high", 0),
                low=tick_data.get("ohlc", {}).get("low", 0),
                close=tick_data.get("ohlc", {}).get("close", 0),
                change=tick_data.get("change", 0),
                average_price=tick_data.get("average_traded_price", 0)
            )
            
        except Exception as e:
            logger.error(f"Failed to parse tick: {e}")
            return None
    
    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._is_connected
    
    # ==================== Order Management ====================
    
    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        order_type: OrderType = OrderType.MARKET,
        product: ProductType = ProductType.MIS,
        price: float = 0,
        trigger_price: float = 0,
        tag: str = ""
    ) -> Optional[str]:
        """
        Place an order.
        
        Args:
            symbol: Trading symbol.
            side: BUY or SELL.
            quantity: Order quantity.
            order_type: MARKET, LIMIT, SL, SL-M.
            product: MIS (intraday), CNC (delivery), NRML (F&O).
            price: Limit price (for LIMIT orders).
            trigger_price: Trigger price (for SL orders).
            tag: Order tag for identification.
        
        Returns:
            Order ID if successful.
        """
        try:
            order_params = {
                "tradingsymbol": symbol,
                "exchange": "NSE",
                "transaction_type": side.value,
                "quantity": quantity,
                "order_type": order_type.value,
                "product": product.value,
                "variety": "regular",
            }
            
            if price > 0:
                order_params["price"] = price
            
            if trigger_price > 0:
                order_params["trigger_price"] = trigger_price
            
            if tag:
                order_params["tag"] = tag
            
            order_id = self.kite.place_order(**order_params)
            
            logger.info(f"Order placed: {order_id} - {side.value} {quantity} {symbol}")
            return order_id
            
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None
    
    def modify_order(
        self,
        order_id: str,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        order_type: Optional[OrderType] = None
    ) -> bool:
        """Modify an existing order."""
        try:
            params = {"order_id": order_id, "variety": "regular"}
            
            if quantity is not None:
                params["quantity"] = quantity
            if price is not None:
                params["price"] = price
            if trigger_price is not None:
                params["trigger_price"] = trigger_price
            if order_type is not None:
                params["order_type"] = order_type.value
            
            self.kite.modify_order(**params)
            logger.info(f"Order modified: {order_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to modify order {order_id}: {e}")
            return False
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        try:
            self.kite.cancel_order(order_id=order_id, variety="regular")
            logger.info(f"Order cancelled: {order_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def get_orders(self) -> List[Order]:
        """Get all orders for the day."""
        try:
            orders = self.kite.orders()
            
            result = []
            for o in orders:
                result.append(Order(
                    order_id=o["order_id"],
                    symbol=o["tradingsymbol"],
                    instrument_token=o.get("instrument_token", 0),
                    side=OrderSide(o["transaction_type"]),
                    quantity=o["quantity"],
                    order_type=OrderType(o["order_type"]),
                    product=ProductType(o["product"]),
                    price=o.get("price", 0),
                    trigger_price=o.get("trigger_price", 0),
                    status=self._map_order_status(o["status"]),
                    filled_quantity=o.get("filled_quantity", 0),
                    average_price=o.get("average_price", 0),
                ))
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get orders: {e}")
            return []
    
    def get_positions(self) -> Dict:
        """Get current positions."""
        try:
            return self.kite.positions()
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return {"net": [], "day": []}
    
    def get_holdings(self) -> List[Dict]:
        """Get holdings (for CNC positions)."""
        try:
            return self.kite.holdings()
        except Exception as e:
            logger.error(f"Failed to get holdings: {e}")
            return []
    
    def _map_order_status(self, status: str) -> OrderStatus:
        """Map Kite order status to OrderStatus enum."""
        status_map = {
            "PENDING": OrderStatus.PENDING,
            "OPEN": OrderStatus.OPEN,
            "COMPLETE": OrderStatus.COMPLETE,
            "CANCELLED": OrderStatus.CANCELLED,
            "REJECTED": OrderStatus.REJECTED,
            "TRIGGER PENDING": OrderStatus.PENDING,
        }
        return status_map.get(status, OrderStatus.PENDING)
    
    # ==================== Account Info ====================
    
    def get_profile(self) -> Dict:
        """Get user profile."""
        try:
            return self.kite.profile()
        except Exception as e:
            logger.error(f"Failed to get profile: {e}")
            return {}
    
    def get_margins(self) -> Dict:
        """Get account margins."""
        try:
            return self.kite.margins()
        except Exception as e:
            logger.error(f"Failed to get margins: {e}")
            return {}
    
    def get_available_margin(self) -> float:
        """Get available margin for trading."""
        try:
            margins = self.get_margins()
            equity = margins.get("equity", {})
            return equity.get("available", {}).get("cash", 0)
        except Exception:
            return 0.0


# Singleton instance
_kite_client: Optional[KiteClient] = None


def get_kite_client() -> KiteClient:
    """Get the singleton Kite client instance."""
    global _kite_client
    if _kite_client is None:
        _kite_client = KiteClient()
    return _kite_client
