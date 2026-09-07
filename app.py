#!/usr/bin/env python3
"""
Trading Service - Main Application Entry Point

Supports both Intraday and Swing trading:
- Intraday: Breakout strategies with auto square-off (MIS)
- Swing: Trend following with multi-day holds (CNC)
"""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, date
from typing import Optional

from core.config import get_config, load_config, TradingMode, TradingStyle
from core.models import OHLC, Tick
from core.session_manager import MarketPhase
from monitoring.llm_metrics import get_metrics, health_check, setup_logging

logger = logging.getLogger(__name__)


class TradingService:
    """Main trading service orchestrator supporting both intraday and swing."""
    
    def __init__(self):
        self.config = get_config()
        self._running = False
        self._initialized = False
        
        # Components will be initialized based on trading style
        self.kite = None
        self.scanner = None
        self.metrics = get_metrics()
    
    def initialize(self, access_token: Optional[str] = None) -> bool:
        """Initialize the trading service."""
        logger.info("=" * 60)
        logger.info("Trading Service Initialization")
        logger.info("=" * 60)
        logger.info(f"Mode: {self.config.mode.value}")
        logger.info(f"Style: {self.config.trading_style.value.upper()}")
        logger.info(f"Capital: Rs.{self.config.capital:,.2f}")
        
        # Get appropriate watchlist
        watchlist = self.config.get_active_watchlist()
        logger.info(f"Watchlist: {len(watchlist.symbols)} symbols")
        
        # Initialize Kite client for LIVE mode
        if self.config.mode == TradingMode.LIVE:
            from data.kite_client import get_kite_client
            self.kite = get_kite_client()
            
            if not access_token:
                logger.error("Access token required for LIVE mode")
                self._print_login_instructions()
                return False
            
            if not self.kite.initialize(access_token):
                logger.error("Failed to initialize Kite client")
                return False
            
            logger.info("Kite Connect initialized")
        else:
            logger.info("Paper trading mode - Kite connection skipped")
        
        # Initialize based on trading style
        if self.config.trading_style == TradingStyle.SWING:
            self._initialize_swing()
        else:
            self._initialize_intraday()
        
        self._initialized = True
        logger.info("Initialization complete")
        logger.info("=" * 60)
        
        return True
    
    def _initialize_intraday(self):
        """Initialize intraday trading components."""
        from core.session_manager import get_session_manager
        from core.position_tracker import get_position_tracker
        from langgraph_flow.graph import get_trading_engine
        from risk.risk_guard import get_risk_guard
        from scanner.equity_scanner import get_scanner
        
        self.session = get_session_manager()
        self.position_tracker = get_position_tracker()
        self.engine = get_trading_engine()
        self.risk_guard = get_risk_guard()
        self.scanner = get_scanner()
        
        # Register callbacks
        self.session.register_phase_callback(self._on_phase_change)
        self.session.register_square_off_callback(self._on_intraday_square_off)
        
        # Reset daily state
        self.risk_guard.reset_daily_state()
        
        logger.info("Intraday components initialized")
    
    def _initialize_swing(self):
        """Initialize swing trading components."""
        from core.swing_tracker import get_swing_position_tracker
        from langgraph_flow.swing_graph import get_swing_trading_engine
        from risk.swing_risk import get_swing_risk_guard
        from scanner.equity_scanner import get_scanner
        
        self.swing_tracker = get_swing_position_tracker()
        self.swing_engine = get_swing_trading_engine()
        self.swing_risk = get_swing_risk_guard()
        self.scanner = get_scanner()
        
        # Initialize swing engine
        self.swing_engine.initialize()
        
        logger.info("Swing trading components initialized")
        logger.info(f"Loaded {len(self.swing_risk.get_all_positions())} existing positions")
    
    def _print_login_instructions(self):
        """Print Kite login instructions."""
        logger.info("")
        logger.info("To get access token:")
        logger.info("1. Go to https://kite.zerodha.com/connect/login?api_key=YOUR_API_KEY")
        logger.info("2. Login and authorize")
        logger.info("3. Copy request_token from redirect URL")
        logger.info("4. Use KiteConnect to generate access_token")
        logger.info("")
    
    def start(self):
        """Start the trading service."""
        if not self._initialized:
            logger.error("Service not initialized")
            return
        
        logger.info("Starting trading service...")
        self._running = True
        
        # Load market data
        self._load_market_data()
        
        if self.config.trading_style == TradingStyle.SWING:
            self._swing_trading_loop()
        else:
            self._intraday_trading_loop()
    
    def stop(self):
        """Stop the trading service gracefully."""
        logger.info("Stopping trading service...")
        self._running = False
        
        if self.config.trading_style == TradingStyle.INTRADAY:
            self._cleanup_intraday()
        else:
            self._cleanup_swing()
        
        # Print summary
        print(self.metrics.get_summary())
        
        logger.info("Trading service stopped")
    
    def _cleanup_intraday(self):
        """Cleanup intraday positions."""
        from core.session_manager import get_session_manager
        
        # Square off any remaining positions
        if hasattr(self, 'position_tracker'):
            positions = self.position_tracker.get_all_positions()
            if positions:
                logger.info(f"Squaring off {len(positions)} positions...")
                prices = self.scanner.get_current_prices()
                self.position_tracker.square_off_all(prices)
        
        # Stop session monitoring
        if hasattr(self, 'session'):
            self.session.stop_monitoring()
    
    def _cleanup_swing(self):
        """Cleanup swing trading (positions persist)."""
        # Positions are persisted, just log status
        if hasattr(self, 'swing_tracker'):
            review = self.swing_tracker.get_daily_review()
            logger.info(f"Swing positions: {review['total_positions']}")
            logger.info(f"Unrealized P&L: Rs.{review['unrealized_pnl']:.2f}")
    
    def _load_market_data(self):
        """Load historical market data."""
        logger.info("Loading market data...")
        
        watchlist = self.config.get_active_watchlist()
        
        if self.config.mode == TradingMode.LIVE:
            self.scanner.load_historical_data(watchlist.symbols)
            if self.config.trading_style == TradingStyle.INTRADAY:
                self.scanner.load_intraday_data(watchlist.symbols)
        else:
            self._generate_sample_data(watchlist.symbols)
        
        logger.info(f"Loaded data for {len(watchlist.symbols)} symbols")
    
    def _generate_sample_data(self, symbols):
        """Generate sample data for paper trading."""
        import pandas as pd
        import numpy as np
        
        # More data for swing trading
        days = 90 if self.config.trading_style == TradingStyle.SWING else 30
        
        for symbol in symbols:
            dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
            base_price = np.random.uniform(500, 3000)
            
            daily_data = []
            price = base_price
            
            for dt in dates:
                # Add some trend
                trend = np.random.uniform(-0.005, 0.008)
                price = price * (1 + trend)
                
                open_price = price * (1 + np.random.uniform(-0.01, 0.01))
                high = open_price * (1 + np.random.uniform(0, 0.025))
                low = open_price * (1 - np.random.uniform(0, 0.025))
                close = np.random.uniform(low, high)
                volume = int(np.random.uniform(100000, 5000000))
                
                daily_data.append({
                    'timestamp': dt,
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'close': close,
                    'volume': volume,
                    'symbol': symbol
                })
                
                price = close
            
            self.scanner._historical_data[symbol] = pd.DataFrame(daily_data)
    
    # ==================== Intraday Trading ====================
    
    def _intraday_trading_loop(self):
        """Main loop for intraday trading."""
        from core.session_manager import get_session_manager
        
        session = get_session_manager()
        session.start_monitoring()
        
        # Start WebSocket for LIVE mode
        if self.config.mode == TradingMode.LIVE:
            self._start_ticker()
        
        scan_interval = 60  # seconds
        last_scan = 0
        
        logger.info("Entering intraday trading loop...")
        
        while self._running:
            try:
                current_time = time.time()
                
                if current_time - last_scan >= scan_interval:
                    if session.is_trading_allowed():
                        self._scan_intraday()
                    last_scan = current_time
                
                # Update paper orders
                if self.config.mode == TradingMode.PAPER:
                    prices = self.scanner.get_current_prices()
                    self.position_tracker.update_prices(prices)
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                self.metrics.record_error()
                time.sleep(5)
    
    def _scan_intraday(self):
        """Scan for intraday opportunities."""
        candles = self.scanner.get_all_current_candles()
        
        for symbol, candle in candles.items():
            result = self.engine.process_candle(symbol, candle)
            
            if result.get("signal"):
                self.metrics.record_signal()
            
            if result.get("order_id"):
                logger.info(f"Trade: {symbol} - {result.get('messages', [])}")
    
    def _on_phase_change(self, phase: MarketPhase):
        """Handle intraday phase changes."""
        logger.info(f"Market phase: {phase.value}")
    
    def _on_intraday_square_off(self):
        """Handle intraday square-off."""
        logger.info("Intraday square-off triggered!")
        prices = self.scanner.get_current_prices()
        results = self.position_tracker.square_off_all(prices)
        
        for result in results:
            self.metrics.record_trade(
                symbol=result.symbol,
                side=result.side.value,
                pnl=result.pnl,
                exit_reason="square_off"
            )
    
    def _start_ticker(self):
        """Start WebSocket ticker."""
        watchlist = self.config.get_active_watchlist()
        self.kite.register_tick_callback(self._on_tick)
        self.kite.start_ticker(watchlist.symbols)
    
    def _on_tick(self, tick: Tick):
        """Handle incoming tick."""
        self.scanner.update_tick(tick)
        
        if self.config.trading_style == TradingStyle.INTRADAY:
            self.engine.process_tick(tick)
        else:
            # Update swing positions
            self.swing_risk.update_position_price(tick.symbol, tick.last_price)
    
    # ==================== Swing Trading ====================
    
    def _swing_trading_loop(self):
        """Main loop for swing trading."""
        logger.info("Entering swing trading loop...")
        logger.info("Swing trading runs daily analysis (not continuous scanning)")
        
        # Do daily analysis
        self._run_swing_daily_analysis()
        
        # Monitor positions
        update_interval = 300  # 5 minutes
        last_update = 0
        
        while self._running:
            try:
                current_time = time.time()
                
                if current_time - last_update >= update_interval:
                    self._update_swing_positions()
                    last_update = current_time
                
                time.sleep(10)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in swing loop: {e}")
                time.sleep(60)
    
    def _run_swing_daily_analysis(self):
        """Run daily swing trading analysis."""
        logger.info("")
        logger.info("=" * 50)
        logger.info("Daily Swing Analysis")
        logger.info("=" * 50)
        
        # Get symbol data
        symbol_data = {}
        watchlist = self.config.get_active_watchlist()
        
        for symbol in watchlist.symbols:
            df = self.scanner.get_historical_data(symbol)
            if not df.empty:
                symbol_data[symbol] = df
        
        # Scan for signals
        signals = self.swing_engine.scan_watchlist(symbol_data)
        
        if signals:
            logger.info(f"\nFound {len(signals)} swing signals:")
            for sig in signals[:5]:  # Top 5
                logger.info(
                    f"  {sig.symbol}: {sig.signal_type} | "
                    f"Confidence: {sig.confidence:.2f} | "
                    f"R:R: {sig.risk_reward_1:.2f}"
                )
            
            # Process top signals through graph
            for sig in signals[:3]:  # Process top 3
                df = symbol_data.get(sig.symbol)
                if df is not None:
                    result = self.swing_engine.process_symbol(sig.symbol, df)
                    
                    if result.get("order_id"):
                        logger.info(f"Swing trade executed: {sig.symbol}")
                        self.metrics.record_signal()
        else:
            logger.info("No swing signals today")
        
        # Show watchlist summary
        summary = self.swing_engine.get_watchlist_summary(symbol_data)
        
        logger.info("\nWatchlist Summary:")
        for s in summary[:10]:
            trend_icon = "UP" if s["trend"] == "uptrend" else "DN" if s["trend"] == "downtrend" else "--"
            signal_mark = " *" if s["has_signal"] else ""
            logger.info(
                f"  {s['symbol']:12} | {trend_icon} | "
                f"Strength: {s['trend_strength']:.2f} | "
                f"ATR: {s['atr_percent']:.2f}%{signal_mark}"
            )
        
        # Show position review
        review = self.swing_tracker.get_daily_review()
        
        logger.info(f"\nPositions: {review['total_positions']}")
        logger.info(f"Unrealized P&L: Rs.{review['unrealized_pnl']:.2f}")
        
        if review['positions_to_review']:
            logger.info("\nPositions to review (long holding):")
            for p in review['positions_to_review']:
                logger.info(f"  {p['symbol']}: {p['holding_days']} days, {p['pnl_percent']:.2f}%")
        
        logger.info("=" * 50)
    
    def _update_swing_positions(self):
        """Update swing position prices."""
        if self.config.mode == TradingMode.PAPER:
            # Simulate price changes
            import numpy as np
            
            positions = self.swing_risk.get_all_positions()
            for pos in positions:
                # Random walk
                change = np.random.uniform(-0.01, 0.012)
                new_price = pos.current_price * (1 + change)
                self.swing_risk.update_position_price(pos.symbol, new_price)
        else:
            # Get live prices
            prices = self.scanner.get_current_prices()
            for symbol, price in prices.items():
                self.swing_risk.update_position_price(symbol, price)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Trading Service - Intraday & Swing Trading"
    )
    parser.add_argument(
        "--config", 
        type=str, 
        default="config.yaml",
        help="Config file path"
    )
    parser.add_argument(
        "--style",
        type=str,
        choices=["intraday", "swing"],
        help="Override trading style"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        help="Log file path"
    )
    parser.add_argument(
        "--access-token",
        type=str,
        help="Kite Connect access token"
    )
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="Run health check"
    )
    parser.add_argument(
        "--daily-report",
        action="store_true",
        help="Print daily report and exit (swing mode)"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(log_level=args.log_level, log_file=args.log_file)
    
    # Load config
    config = load_config(args.config)
    
    # Override style if specified
    if args.style:
        # Update the global config instance
        import core.config as config_module
        if config_module._config:
            config_module._config.trading_style = TradingStyle(args.style)
    
    # Health check
    if args.health_check:
        health = health_check()
        print(f"Status: {health['status']}")
        for check, result in health['checks'].items():
            print(f"  {check}: {result['status']}")
        sys.exit(0 if health['status'] == 'healthy' else 1)
    
    # Create service
    service = TradingService()
    
    # Signal handlers
    def signal_handler(signum, frame):
        service.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Daily report mode (force swing style)
    if args.daily_report:
        # Force swing mode for daily report
        import core.config as config_module
        if config_module._config:
            config_module._config.trading_style = TradingStyle.SWING
        
        if service.initialize(args.access_token):
            service._load_market_data()
            service._run_swing_daily_analysis()
        sys.exit(0)
    
    # Initialize and start
    if service.initialize(args.access_token):
        service.start()
    else:
        logger.error("Failed to initialize")
        sys.exit(1)


if __name__ == "__main__":
    main()
