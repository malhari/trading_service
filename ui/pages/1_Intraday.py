"""
Intraday Trading Page

Focused on short-term, fast decisions with tick-by-tick charts,
real-time signals, and quick order execution.
"""

import streamlit as st
import sys
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime

# Page config
st.set_page_config(
    page_title="Intraday Trading",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load CSS
def load_css():
    css_file = Path(__file__).parent.parent / "styles" / "custom.css"
    if css_file.exists():
        with open(css_file) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

load_css()

# Import components
from core.config import get_config, TradingMode

# Initialize session state
if 'selected_symbol' not in st.session_state:
    st.session_state.selected_symbol = None

if 'trading_mode' not in st.session_state:
    st.session_state.trading_mode = "intraday"

# Force intraday mode on this page
st.session_state.trading_mode = "intraday"

# Sidebar
with st.sidebar:
    st.title("Intraday Trading")
    
    config = get_config()
    
    # Mode indicator
    mode_icon = "Paper" if config.mode == TradingMode.PAPER else "LIVE"
    mode_color = "warning" if config.mode == TradingMode.PAPER else "error"
    if config.mode == TradingMode.PAPER:
        st.warning(f"Mode: {mode_icon}", icon="📝")
    else:
        st.error(f"Mode: {mode_icon}", icon="🔴")
    
    st.divider()
    
    # Session info
    from core.session_manager import get_session_manager
    session = get_session_manager()
    info = session.get_session_info()
    
    st.subheader("Market Session")
    
    phase_colors = {
        'pre_market': 'blue',
        'trading': 'green',
        'post_market': 'orange',
        'closed': 'red'
    }
    phase = info['phase']
    st.markdown(f"**Phase:** :{phase_colors.get(phase, 'gray')}[{phase.upper()}]")
    
    if info['is_trading_allowed']:
        st.success("Trading Allowed", icon="✅")
    else:
        st.error("Trading Disabled", icon="❌")
    
    if info['time_to_square_off']:
        st.warning(f"Square-off in: {info['time_to_square_off']}", icon="⏰")
    
    st.divider()
    
    # Quick stats
    st.subheader("Quick Stats")
    
    from risk.risk_guard import get_risk_guard
    from core.position_tracker import get_position_tracker
    
    guard = get_risk_guard()
    tracker = get_position_tracker()
    
    status = guard.get_risk_status()
    positions = tracker.get_all_positions()
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Capital", f"Rs.{config.capital:,.0f}")
    with col2:
        st.metric("Positions", f"{len(positions)}/{config.risk.max_positions}")
    
    pnl = status.get('total_pnl', 0.0)
    pnl_color = "normal" if pnl >= 0 else "inverse"
    st.metric("Daily P&L", f"Rs.{pnl:,.2f}", delta=f"{pnl:+,.2f}", delta_color=pnl_color)
    
    st.divider()
    
    # Risk indicator
    if status.get('circuit_breaker', False):
        st.error("CIRCUIT BREAKER ACTIVE", icon="🚫")
    
    loss_limit_used = (abs(pnl) / (config.risk.max_daily_loss * config.capital)) * 100 if pnl < 0 else 0
    st.progress(min(loss_limit_used / 100, 1.0), text=f"Loss Limit: {loss_limit_used:.1f}%")
    
    st.divider()
    
    # Refresh
    if st.button("Refresh", use_container_width=True):
        st.rerun()
    
    st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

# Main content
st.header("Intraday Trading Dashboard")

# Import components
from ui.components.charts import render_chart
from ui.components.watchlist import render_watchlist
from ui.components.signals import render_signals
from ui.components.positions import render_positions, get_position_alerts
from ui.components.orders import render_order_panel
from ui.components.risk_dashboard import render_compact_risk_bar
from ui.components.llm_analysis import render_llm_analysis_panel

# Position alerts
alerts = get_position_alerts("intraday")
if alerts:
    for alert in alerts:
        if alert['type'] == 'NEAR_SL':
            st.warning(f"**{alert['symbol']}**: {alert['message']}", icon="⚠️")

# Top row: Watchlist | Chart | Signals
col1, col2, col3 = st.columns([1, 2.5, 1.5])

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
    st.subheader("Active Signals")
    render_signals(mode="intraday")

st.divider()

# Bottom row: Positions | AI Analysis | Order Panel
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    st.subheader("Open Positions")
    render_positions(mode="intraday")

with col2:
    # Show LLM analysis if a signal is selected
    signal_to_analyze = st.session_state.get('analyze_signal')
    render_llm_analysis_panel(signal=signal_to_analyze)

with col3:
    st.subheader("Quick Order")
    render_order_panel(mode="intraday")

st.divider()

# Risk bar at bottom
render_compact_risk_bar(mode="intraday")

# Auto-refresh
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=5000, key="intraday_refresh")
except ImportError:
    pass
