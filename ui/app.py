"""
Trading Dashboard - Main Streamlit Application

Supports both Intraday and Swing trading modes with real-time
positions, signals, and order execution.
"""

import streamlit as st
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import pandas as pd

# Page config must be first Streamlit command
st.set_page_config(
    page_title="Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'About': "Trading Dashboard - Intraday & Swing Trading"
    }
)

# Load custom CSS
def load_css():
    css_file = Path(__file__).parent / "styles" / "custom.css"
    if css_file.exists():
        with open(css_file) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

load_css()

# Import backend components
from core.config import get_config, TradingStyle, TradingMode
from scanner.equity_scanner import get_scanner

# Initialize session state
def init_session_state():
    """Initialize session state variables."""
    if 'trading_mode' not in st.session_state:
        config = get_config()
        st.session_state.trading_mode = config.trading_style.value
    
    if 'selected_symbol' not in st.session_state:
        st.session_state.selected_symbol = None
    
    if 'signals' not in st.session_state:
        st.session_state.signals = []
    
    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = datetime.now()
    
    if 'auto_refresh' not in st.session_state:
        st.session_state.auto_refresh = True

init_session_state()

# Sidebar
def render_sidebar():
    """Render the sidebar with mode switcher and settings."""
    with st.sidebar:
        st.title("Trading Dashboard")
        
        # Mode indicator
        config = get_config()
        mode_color = "🟡" if config.mode == TradingMode.PAPER else "🔴"
        st.markdown(f"**Mode:** {mode_color} {config.mode.value}")
        
        st.divider()
        
        # Trading style switcher
        st.subheader("Trading Style")
        trading_style = st.radio(
            "Select Style",
            options=["intraday", "swing"],
            index=0 if st.session_state.trading_mode == "intraday" else 1,
            format_func=lambda x: "Intraday" if x == "intraday" else "Swing",
            horizontal=True,
            label_visibility="collapsed"
        )
        
        if trading_style != st.session_state.trading_mode:
            st.session_state.trading_mode = trading_style
            st.rerun()
        
        st.divider()
        
        # Quick stats
        st.subheader("Quick Stats")
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Capital", f"Rs.{config.capital:,.0f}")
        with col2:
            # Get position count based on mode
            if st.session_state.trading_mode == "intraday":
                from core.position_tracker import get_position_tracker
                tracker = get_position_tracker()
                pos_count = len(tracker.get_all_positions())
            else:
                from risk.swing_risk import get_swing_risk_guard
                guard = get_swing_risk_guard()
                pos_count = len(guard.get_all_positions())
            
            max_pos = config.risk.max_positions if st.session_state.trading_mode == "intraday" else config.swing_risk.max_positions
            st.metric("Positions", f"{pos_count}/{max_pos}")
        
        st.divider()
        
        # Auto-refresh toggle
        st.subheader("Settings")
        st.session_state.auto_refresh = st.checkbox(
            "Auto-refresh (5s)",
            value=st.session_state.auto_refresh
        )
        
        if st.button("Refresh Now", use_container_width=True):
            st.session_state.last_refresh = datetime.now()
            st.rerun()
        
        st.divider()
        
        # Session info
        if st.session_state.trading_mode == "intraday":
            from core.session_manager import get_session_manager
            session = get_session_manager()
            info = session.get_session_info()
            
            st.subheader("Market Session")
            st.write(f"**Phase:** {info['phase']}")
            st.write(f"**Trading:** {'Yes' if info['is_trading_allowed'] else 'No'}")
            if info['time_to_square_off']:
                st.write(f"**Square-off in:** {info['time_to_square_off']}")
        
        st.divider()
        
        # Last refresh time
        st.caption(f"Last updated: {st.session_state.last_refresh.strftime('%H:%M:%S')}")

def render_header():
    """Render the main header."""
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        if st.session_state.trading_mode == "intraday":
            st.header("Intraday Trading")
        else:
            st.header("Swing Trading")
    
    with col2:
        # Current time
        st.markdown(f"**{datetime.now().strftime('%H:%M:%S')}**")
    
    with col3:
        config = get_config()
        if config.mode == TradingMode.PAPER:
            st.warning("PAPER MODE", icon="📝")
        else:
            st.error("LIVE MODE", icon="🔴")

def main():
    """Main application entry point."""
    # Render sidebar
    render_sidebar()
    
    # Render header
    render_header()
    
    # Auto-refresh
    if st.session_state.auto_refresh:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=5000, key="datarefresh")
        except ImportError:
            pass  # Auto-refresh not available
    
    # Import components
    from ui.components.charts import render_chart
    from ui.components.watchlist import render_watchlist
    from ui.components.signals import render_signals
    from ui.components.positions import render_positions
    from ui.components.orders import render_order_panel
    from ui.components.risk_dashboard import render_risk_dashboard
    
    # Main content based on trading mode
    if st.session_state.trading_mode == "intraday":
        render_intraday_layout()
    else:
        render_swing_layout()

def render_intraday_layout():
    """Render the intraday trading layout."""
    from ui.components.charts import render_chart
    from ui.components.watchlist import render_watchlist
    from ui.components.signals import render_signals
    from ui.components.positions import render_positions
    from ui.components.orders import render_order_panel
    from ui.components.risk_dashboard import render_risk_dashboard
    
    # Top row: Watchlist | Chart | Signals
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        st.subheader("Watchlist")
        render_watchlist(mode="intraday")
    
    with col2:
        st.subheader("Chart")
        render_chart(
            symbol=st.session_state.selected_symbol,
            timeframe="5m",
            mode="intraday"
        )
    
    with col3:
        st.subheader("Signals")
        render_signals(mode="intraday")
    
    st.divider()
    
    # Bottom row: Positions | Order Panel
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Open Positions")
        render_positions(mode="intraday")
    
    with col2:
        st.subheader("Order Panel")
        render_order_panel(mode="intraday")
    
    st.divider()
    
    # Risk metrics bar
    render_risk_dashboard(mode="intraday")

def render_swing_layout():
    """Render the swing trading layout."""
    from ui.components.charts import render_chart
    from ui.components.watchlist import render_watchlist
    from ui.components.signals import render_signals
    from ui.components.positions import render_positions
    from ui.components.orders import render_order_panel
    from ui.components.risk_dashboard import render_risk_dashboard
    
    # Top row: Watchlist | Chart | Analysis
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        st.subheader("Watchlist")
        render_watchlist(mode="swing")
    
    with col2:
        st.subheader("Chart")
        render_chart(
            symbol=st.session_state.selected_symbol,
            timeframe="D",
            mode="swing"
        )
    
    with col3:
        st.subheader("Analysis")
        render_analysis_panel()
    
    st.divider()
    
    # Bottom row: Positions | Signals
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Portfolio Positions")
        render_positions(mode="swing")
    
    with col2:
        st.subheader("Signals & Orders")
        
        tab1, tab2 = st.tabs(["Signals", "Order"])
        
        with tab1:
            render_signals(mode="swing")
        
        with tab2:
            render_order_panel(mode="swing")
    
    st.divider()
    
    # Portfolio summary
    render_risk_dashboard(mode="swing")

def render_analysis_panel():
    """Render the swing analysis panel."""
    if st.session_state.selected_symbol:
        symbol = st.session_state.selected_symbol
        
        # Get analysis data
        scanner = get_scanner()
        df = scanner.get_historical_data(symbol)
        
        if not df.empty:
            from strategies.swing_levels import SwingLevelCalculator
            
            calc = SwingLevelCalculator()
            trend = calc.analyze_trend(df)
            
            # Trend info
            trend_color = "green" if trend.direction == "uptrend" else "red" if trend.direction == "downtrend" else "orange"
            st.markdown(f"**Trend:** :{trend_color}[{trend.direction.upper()}]")
            st.progress(trend.strength, text=f"Strength: {trend.strength:.0%}")
            
            st.divider()
            
            # Key levels
            st.markdown("**Key Levels**")
            levels = calc.calculate_all_swing_levels(df)
            
            current_price = df.iloc[-1]['close']
            supports, resistances = calc.get_key_levels(current_price, levels['all'], count=2)
            
            if resistances:
                st.write(f"R1: {resistances[0].price:.2f}")
                if len(resistances) > 1:
                    st.write(f"R2: {resistances[1].price:.2f}")
            
            st.write(f"**Price: {current_price:.2f}**")
            
            if supports:
                st.write(f"S1: {supports[0].price:.2f}")
                if len(supports) > 1:
                    st.write(f"S2: {supports[1].price:.2f}")
            
            st.divider()
            
            # ATR info
            st.metric("ATR %", f"{trend.atr_percent:.2f}%")
        else:
            st.info("Select a symbol to see analysis")
    else:
        st.info("Select a symbol from the watchlist")


if __name__ == "__main__":
    main()
