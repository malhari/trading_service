"""
Swing Trading Page

Focused on medium-term trades with daily/weekly charts,
trend analysis, and portfolio management.
"""

import streamlit as st
import sys
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime, date

# Page config
st.set_page_config(
    page_title="Swing Trading",
    page_icon="📈",
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
    st.session_state.trading_mode = "swing"

# Force swing mode on this page
st.session_state.trading_mode = "swing"

# Sidebar
with st.sidebar:
    st.title("Swing Trading")
    
    config = get_config()
    
    # Mode indicator
    mode_icon = "Paper" if config.mode == TradingMode.PAPER else "LIVE"
    if config.mode == TradingMode.PAPER:
        st.warning(f"Mode: {mode_icon}", icon="📝")
    else:
        st.error(f"Mode: {mode_icon}", icon="🔴")
    
    st.divider()
    
    # Portfolio summary
    st.subheader("Portfolio Summary")
    
    from risk.swing_risk import get_swing_risk_guard
    
    guard = get_swing_risk_guard()
    status = guard.get_risk_status()
    positions = guard.get_all_positions()
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Capital", f"Rs.{config.capital:,.0f}")
    with col2:
        st.metric("Positions", f"{len(positions)}/{config.swing_risk.max_positions}")
    
    # Weekly P&L
    pnl = status.get('total_pnl_weekly', 0.0)
    pnl_color = "normal" if pnl >= 0 else "inverse"
    st.metric("Weekly P&L", f"Rs.{pnl:,.2f}", delta=f"{pnl:+,.2f}", delta_color=pnl_color)
    
    # Unrealized P&L
    unrealized = sum(p.pnl for p in positions)
    unrealized_color = "normal" if unrealized >= 0 else "inverse"
    st.metric("Unrealized P&L", f"Rs.{unrealized:,.2f}", delta_color=unrealized_color)
    
    st.divider()
    
    # Sector exposure
    st.subheader("Sector Exposure")
    
    sector_exposure = status.get('sector_exposure', {})
    if sector_exposure:
        for sector, exposure in sector_exposure.items():
            if exposure > 0:
                exp_color = "green" if exposure <= config.swing_risk.max_sector_exposure else "red"
                st.markdown(f"**{sector.title()}:** :{exp_color}[{exposure:.1%}]")
    else:
        st.caption("No positions")
    
    st.divider()
    
    # Economic calendar hint
    st.subheader("Upcoming Events")
    st.caption("Earnings & Economic Calendar")
    
    # Sample events
    events = [
        ("Sep 8", "RBI Policy", "High"),
        ("Sep 10", "TCS Results", "Medium"),
        ("Sep 12", "INFY Results", "Medium"),
    ]
    
    for date_str, event, impact in events:
        impact_color = "red" if impact == "High" else "orange" if impact == "Medium" else "gray"
        st.markdown(f"**{date_str}** - {event} :{impact_color}[{impact}]")
    
    st.divider()
    
    # Refresh
    if st.button("Refresh", use_container_width=True):
        st.rerun()
    
    st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

# Main content
st.header("Swing Trading Dashboard")

# Import components
from ui.components.charts import render_chart
from ui.components.watchlist import render_watchlist
from ui.components.signals import render_signals
from ui.components.positions import render_positions, get_position_alerts
from ui.components.orders import render_order_panel
from ui.components.risk_dashboard import render_risk_dashboard, render_sector_exposure, render_pnl_chart
from ui.components.llm_analysis import render_llm_analysis_panel, render_sentiment_panel

# Position alerts
alerts = get_position_alerts("swing")
if alerts:
    for alert in alerts:
        if alert['type'] == 'NEAR_SL':
            st.warning(f"**{alert['symbol']}**: {alert['message']}", icon="⚠️")
        elif alert['type'] == 'LONG_HOLDING':
            st.info(f"**{alert['symbol']}**: {alert['message']}", icon="📅")

# Top row: Watchlist | Chart | Analysis
col1, col2, col3 = st.columns([1, 2.5, 1.5])

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
    st.subheader("Technical Analysis")
    
    if st.session_state.selected_symbol:
        symbol = st.session_state.selected_symbol
        
        # Get analysis data
        from scanner.equity_scanner import get_scanner
        from strategies.swing_levels import SwingLevelCalculator
        
        scanner = get_scanner()
        df = scanner.get_historical_data(symbol)
        
        if not df.empty:
            calc = SwingLevelCalculator()
            trend = calc.analyze_trend(df)
            
            # Trend info
            trend_colors = {
                'uptrend': 'green',
                'downtrend': 'red',
                'sideways': 'orange'
            }
            st.markdown(f"**Trend:** :{trend_colors[trend.direction]}[{trend.direction.upper()}]")
            st.progress(trend.strength, text=f"Strength: {trend.strength:.0%}")
            
            st.markdown(f"**Price vs EMA:** {trend.price_vs_ema}")
            
            st.divider()
            
            # Key levels
            st.markdown("**Key Levels**")
            
            levels = calc.calculate_all_swing_levels(df)
            current_price = df.iloc[-1]['close']
            
            supports, resistances = calc.get_key_levels(current_price, levels['all'], count=3)
            
            if resistances:
                for i, r in enumerate(resistances[:3], 1):
                    st.markdown(f"R{i}: {r.price:.2f} ({r.level_type})")
            
            st.markdown(f"**Current: {current_price:.2f}**")
            
            if supports:
                for i, s in enumerate(supports[:3], 1):
                    st.markdown(f"S{i}: {s.price:.2f} ({s.level_type})")
            
            st.divider()
            
            # Technical Indicators (RSI, MACD, EMA)
            st.markdown("**Technical Indicators**")
            indicators = calc.get_indicator_signals(df)
            
            if "error" not in indicators:
                # RSI
                rsi_val = indicators["rsi"]["value"]
                rsi_sig = indicators["rsi"]["signal"]
                rsi_color = "green" if rsi_sig in ["oversold", "recovering_from_oversold"] else \
                            "red" if rsi_sig in ["overbought", "weakening_from_overbought"] else "gray"
                st.markdown(f"**RSI (14):** :{rsi_color}[{rsi_val}] - {rsi_sig.replace('_', ' ').title()}")
                
                # MACD
                macd_val = indicators["macd"]["macd"]
                macd_hist = indicators["macd"]["histogram"]
                macd_sig = indicators["macd"]["signal"]
                macd_color = "green" if "bullish" in macd_sig else "red" if "bearish" in macd_sig else "gray"
                crossover_icon = " 🔄" if indicators["macd"]["crossover"] else ""
                st.markdown(f"**MACD:** :{macd_color}[{macd_val}]{crossover_icon} - {macd_sig.replace('_', ' ').title()}")
                
                # EMA
                ema_21 = indicators["ema"]["ema_21"]
                ema_50 = indicators["ema"]["ema_50"]
                ema_sig = indicators["ema"]["signal"]
                ema_color = "green" if "uptrend" in ema_sig else "red" if "downtrend" in ema_sig else "gray"
                st.markdown(f"**EMA:** 21d={ema_21:.2f} | 50d={ema_50:.2f}")
                st.markdown(f"**Trend:** :{ema_color}[{ema_sig.replace('_', ' ').title()}]")
                
                # Overall signal
                st.divider()
                overall = indicators["overall_signal"]
                overall_color = "green" if overall == "bullish" else "red" if overall == "bearish" else "orange"
                st.markdown(f"### Overall: :{overall_color}[{overall.upper()}]")
                st.caption(f"Bullish signals: {indicators['bullish_count']} | Bearish signals: {indicators['bearish_count']}")
            
            st.divider()
            
            # ATR and volatility
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("ATR %", f"{trend.atr_percent:.2f}%")
            with col_b:
                st.metric("ATR", f"Rs.{trend.atr:.2f}")
            
            # Consolidation check
            zones = calc.find_consolidation_zones(df)
            if zones:
                st.info(f"In consolidation zone", icon="📊")
        else:
            st.info("Select a symbol for analysis")
    else:
        st.info("Select a symbol from watchlist")

st.divider()

# Middle row: Positions | Signals & Orders
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Portfolio Positions")
    render_positions(mode="swing")
    
    # Position details expander
    if positions:
        with st.expander("Position Details"):
            for pos in positions:
                st.markdown(f"### {pos.symbol}")
                
                col_a, col_b, col_c, col_d = st.columns(4)
                
                with col_a:
                    st.metric("Entry", f"Rs.{pos.entry_price:.2f}")
                
                with col_b:
                    st.metric("Current", f"Rs.{pos.current_price:.2f}")
                
                with col_c:
                    st.metric("Holding Days", pos.holding_days)
                
                with col_d:
                    pnl_color = "normal" if pos.pnl >= 0 else "inverse"
                    st.metric("P&L", f"Rs.{pos.pnl:.2f}", delta=f"{pos.pnl_percent:+.2f}%", delta_color=pnl_color)
                
                # Targets
                st.markdown(f"**SL:** {pos.stop_loss:.2f} | **T1:** {pos.target_1:.2f} | **T2:** {pos.target_2:.2f} | **T3:** {pos.target_3:.2f}")
                
                if pos.is_trailing_sl_active:
                    st.success("Trailing SL Active", icon="✅")
                
                st.markdown("---")

with col2:
    tab1, tab2, tab3, tab4 = st.tabs(["Scanner", "Signals", "AI Analysis", "Order"])
    
    with tab1:
        st.subheader("Swing Scanner")
        
        # Scanner settings
        scan_col1, scan_col2 = st.columns(2)
        with scan_col1:
            min_score = st.slider("Min Score", 40, 90, 60, 5)
        with scan_col2:
            scan_type = st.selectbox("Setup Type", ["All", "Bullish Only", "Bearish Only"])
        
        if st.button("🔍 Scan Watchlist", type="primary", use_container_width=True):
            from scanner.swing_scanner import get_swing_scanner
            
            scanner = get_swing_scanner()
            
            # Get watchlist symbols (use configured or default)
            watchlist = config.swing.watchlist if config.swing.watchlist else [
                "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
                "BHARTIARTL", "SBIN", "WIPRO", "TATASTEEL", "AXISBANK"
            ]
            
            with st.spinner("Scanning..."):
                if scan_type == "Bullish Only":
                    results = scanner.get_bullish_setups(watchlist)
                elif scan_type == "Bearish Only":
                    results = scanner.get_bearish_setups(watchlist)
                else:
                    results = scanner.scan_watchlist(watchlist, min_score=min_score)
                
                st.session_state.scan_results = results
        
        # Display scan results
        if "scan_results" in st.session_state and st.session_state.scan_results:
            results = st.session_state.scan_results
            st.success(f"Found {len(results)} setups")
            
            for r in results:
                with st.container(border=True):
                    # Header with symbol and score
                    score_color = "green" if r.score >= 75 else "orange" if r.score >= 60 else "gray"
                    st.markdown(f"### {r.symbol} :{score_color}[{r.score:.0f}]")
                    
                    # Type and price
                    type_emoji = "📈" if "bullish" in r.scan_type.value or "support" in r.scan_type.value or "oversold" in r.scan_type.value else "📉"
                    st.markdown(f"{type_emoji} **{r.scan_type.value.replace('_', ' ').title()}**")
                    st.markdown(f"Price: **Rs.{r.price:.2f}** | RSI: **{r.rsi:.1f}**")
                    
                    # Support/Resistance info
                    if r.nearest_support:
                        st.markdown(f"Support: Rs.{r.nearest_support:.2f} ({r.distance_to_support_pct:.1f}% away)")
                    if r.nearest_resistance:
                        st.markdown(f"Resistance: Rs.{r.nearest_resistance:.2f} ({r.distance_to_resistance_pct:.1f}% away)")
                    
                    # Volume
                    vol_icon = "📊" if r.volume_ratio >= 1.2 else "📉"
                    st.markdown(f"Volume: {vol_icon} {r.volume_ratio:.1f}x avg")
                    
                    # Recommendation
                    st.info(r.recommendation, icon="💡")
                    
                    # Action button
                    if st.button(f"Analyze {r.symbol}", key=f"scan_{r.symbol}"):
                        st.session_state.selected_symbol = r.symbol
                        st.rerun()
        elif "scan_results" in st.session_state:
            st.warning("No setups found matching criteria")
    
    with tab2:
        st.subheader("Swing Signals")
        render_signals(mode="swing")
    
    with tab3:
        # Show LLM analysis if a signal is selected
        signal_to_analyze = st.session_state.get('analyze_signal')
        render_llm_analysis_panel(signal=signal_to_analyze)
    
    with tab4:
        st.subheader("Place Order")
        render_order_panel(mode="swing")

st.divider()

# Bottom row: Risk Dashboard
col1, col2 = st.columns(2)

with col1:
    st.subheader("Risk Metrics")
    render_risk_dashboard(mode="swing")

with col2:
    st.subheader("P&L Trend")
    render_pnl_chart(mode="swing", days=30)

# Trade journal section
with st.expander("Trade Journal", expanded=False):
    st.subheader("Recent Trades")
    
    import pandas as pd
    import numpy as np
    
    # Sample journal entries
    journal = pd.DataFrame({
        'Date': pd.date_range(end=date.today(), periods=5, freq='D'),
        'Symbol': np.random.choice(['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'TATAMOTORS'], 5),
        'Type': np.random.choice(['BREAKOUT', 'PULLBACK', 'TREND'], 5),
        'Entry': np.random.uniform(1000, 3000, 5).round(2),
        'Exit': np.random.uniform(1000, 3000, 5).round(2),
        'P&L': np.random.uniform(-500, 1500, 5).round(2),
        'Notes': ['Good setup', 'Early exit', 'Held well', 'Stopped out', 'Partial profit']
    })
    
    st.dataframe(journal, use_container_width=True, hide_index=True)
    
    # Add note
    st.subheader("Add Note")
    note_symbol = st.selectbox("Symbol", config.swing_watchlist.symbols, key="note_symbol")
    note_text = st.text_area("Notes", key="note_text")
    
    if st.button("Save Note"):
        st.success("Note saved")
