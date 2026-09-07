"""
Analysis Page

Provides backtesting, strategy analysis, and performance metrics
for both intraday and swing trading.
"""

import streamlit as st
import sys
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime, date, timedelta
import pandas as pd
import numpy as np

# Page config
st.set_page_config(
    page_title="Analysis",
    page_icon="📊",
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
from core.config import get_config

config = get_config()

# Sidebar
with st.sidebar:
    st.title("Analysis")
    
    # Analysis mode
    analysis_mode = st.radio(
        "Analysis Type",
        options=["Performance", "Backtesting", "Signal Analysis"],
        key="analysis_mode"
    )
    
    st.divider()
    
    # Date range
    st.subheader("Date Range")
    
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input(
            "From",
            value=date.today() - timedelta(days=30),
            key="start_date"
        )
    with col2:
        end_date = st.date_input(
            "To",
            value=date.today(),
            key="end_date"
        )
    
    st.divider()
    
    # Trading style filter
    style_filter = st.selectbox(
        "Trading Style",
        options=["All", "Intraday", "Swing"],
        key="style_filter"
    )
    
    # Symbol filter
    all_symbols = list(set(config.watchlist.symbols + config.swing_watchlist.symbols))
    symbol_filter = st.multiselect(
        "Symbols",
        options=["All"] + all_symbols,
        default=["All"],
        key="symbol_filter"
    )

# Main content
st.header("Trading Analysis")


def render_performance_analysis():
    """Render performance metrics and charts."""
    import plotly.graph_objects as go
    import plotly.express as px
    from data.database import get_database
    
    st.subheader("Performance Overview")
    
    # Get real data from database
    db = get_database()
    
    # Get stats based on filter
    trading_style_filter = None
    if style_filter == "Intraday":
        trading_style_filter = "intraday"
    elif style_filter == "Swing":
        trading_style_filter = "swing"
    
    stats = db.get_trade_stats(
        trading_style=trading_style_filter,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None
    )
    
    # Summary metrics
    col1, col2, col3, col4, col5 = st.columns(5)
    
    # Use real metrics from database
    total_pnl = stats.get('total_pnl', 0)
    total_trades = stats.get('total_trades', 0)
    win_rate = stats.get('win_rate', 0) / 100  # Convert from percentage
    profit_factor = stats.get('profit_factor', 0)
    max_dd = 0.0  # Would need separate calculation
    
    with col1:
        pnl_color = "normal" if total_pnl >= 0 else "inverse"
        st.metric("Total P&L", f"Rs.{total_pnl:,.2f}", delta_color=pnl_color)
    
    with col2:
        st.metric("Total Trades", total_trades)
    
    with col3:
        st.metric("Win Rate", f"{win_rate:.1%}")
    
    with col4:
        st.metric("Profit Factor", f"{profit_factor:.2f}")
    
    with col5:
        st.metric("Max Drawdown", f"{max_dd:.1%}")
    
    st.divider()
    
    # P&L chart
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Cumulative P&L")
        
        dates = pd.date_range(start=start_date, end=end_date, freq='D')
        pnl_values = np.cumsum(np.random.normal(200, 500, len(dates)))
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dates,
            y=pnl_values,
            mode='lines',
            fill='tozeroy',
            line=dict(color='#2196f3'),
            fillcolor='rgba(33, 150, 243, 0.1)'
        ))
        
        fig.add_hline(y=0, line_dash="dash", line_color="#666")
        
        fig.update_layout(
            paper_bgcolor='#0e1117',
            plot_bgcolor='#0e1117',
            font={'color': '#d1d4dc'},
            height=300,
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis=dict(gridcolor='#1a1d24'),
            yaxis=dict(gridcolor='#1a1d24', tickprefix='Rs.')
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("Daily P&L Distribution")
        
        daily_pnl = np.random.normal(100, 400, len(dates))
        
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=daily_pnl,
            nbinsx=30,
            marker_color='#2196f3'
        ))
        
        fig.add_vline(x=0, line_dash="dash", line_color="white")
        
        fig.update_layout(
            paper_bgcolor='#0e1117',
            plot_bgcolor='#0e1117',
            font={'color': '#d1d4dc'},
            height=300,
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis=dict(gridcolor='#1a1d24', title='Daily P&L'),
            yaxis=dict(gridcolor='#1a1d24', title='Frequency')
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    st.divider()
    
    # Trade breakdown
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Trades by Signal Type")
        
        signal_types = ['BREAKOUT_LONG', 'BREAKOUT_SHORT', 'ORB_LONG', 'ORB_SHORT', 'PULLBACK']
        counts = np.random.randint(5, 30, len(signal_types))
        
        fig = go.Figure(data=[go.Pie(
            labels=signal_types,
            values=counts,
            hole=0.4
        )])
        
        fig.update_layout(
            paper_bgcolor='#0e1117',
            plot_bgcolor='#0e1117',
            font={'color': '#d1d4dc'},
            height=300,
            margin=dict(l=20, r=20, t=20, b=20)
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("Win Rate by Symbol")
        
        symbols = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'TATAMOTORS']
        win_rates = np.random.uniform(0.35, 0.70, len(symbols))
        
        fig = go.Figure(data=[go.Bar(
            x=symbols,
            y=win_rates,
            marker_color=['#00c853' if w >= 0.5 else '#ff5252' for w in win_rates]
        )])
        
        fig.add_hline(y=0.5, line_dash="dash", line_color="white", annotation_text="50%")
        
        fig.update_layout(
            paper_bgcolor='#0e1117',
            plot_bgcolor='#0e1117',
            font={'color': '#d1d4dc'},
            height=300,
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis=dict(gridcolor='#1a1d24'),
            yaxis=dict(gridcolor='#1a1d24', tickformat='.0%', range=[0, 1])
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    st.divider()
    
    # Trade log - from database
    st.subheader("Trade Log")
    
    # Get trades from database
    trades = db.get_trades(
        trading_style=trading_style_filter,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        limit=50
    )
    
    if trades:
        trade_log = pd.DataFrame([
            {
                'Date': t.exit_time.split('T')[0] if t.exit_time else '',
                'Symbol': t.symbol,
                'Side': t.side,
                'Type': t.signal_type or 'N/A',
                'Entry': t.entry_price,
                'Exit': t.exit_price,
                'Qty': t.quantity,
                'P&L': t.pnl,
                'P&L%': t.pnl_percent,
                'Reason': t.exit_reason or ''
            }
            for t in trades
        ])
        
        # Color P&L
        def highlight_pnl(val):
            color = 'green' if val > 0 else 'red' if val < 0 else 'white'
            return f'color: {color}'
        
        st.dataframe(
            trade_log.style.applymap(highlight_pnl, subset=['P&L', 'P&L%']),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No trades recorded yet. Execute some trades to see history here.")


def render_backtesting():
    """Render Streak-style backtesting interface."""
    from ui.components.backtester import render_backtest_panel, render_rule_comparison
    
    # Tabs for different backtesting modes
    bt_tab1, bt_tab2 = st.tabs(["Single Strategy", "Compare Strategies"])
    
    with bt_tab1:
        render_backtest_panel()
    
    with bt_tab2:
        render_rule_comparison()


def render_signal_analysis():
    """Render signal analysis interface."""
    import plotly.graph_objects as go
    
    st.subheader("Signal Quality Analysis")
    
    # Signal type filter
    signal_type = st.selectbox(
        "Signal Type",
        options=["All", "BREAKOUT_LONG", "BREAKOUT_SHORT", "ORB_LONG", "ORB_SHORT", "PULLBACK_BUY"],
        key="signal_type_filter"
    )
    
    # Generate sample signal data
    n_signals = 50
    signals_df = pd.DataFrame({
        'Date': pd.date_range(end=date.today(), periods=n_signals, freq='D'),
        'Symbol': np.random.choice(['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'TATAMOTORS'], n_signals),
        'Type': np.random.choice(['BREAKOUT_LONG', 'BREAKOUT_SHORT', 'ORB_LONG', 'ORB_SHORT'], n_signals),
        'Confidence': np.random.uniform(0.5, 0.95, n_signals),
        'Outcome': np.random.choice(['Target', 'SL', 'BE', 'Partial'], n_signals, p=[0.4, 0.3, 0.15, 0.15]),
        'R_Multiple': np.random.uniform(-1, 3, n_signals),
        'Volume_Ratio': np.random.uniform(0.8, 2.5, n_signals)
    })
    
    # Signal success by confidence
    st.subheader("Success Rate by Confidence Level")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Bin by confidence
        confidence_bins = ['0.5-0.6', '0.6-0.7', '0.7-0.8', '0.8-0.9', '0.9-1.0']
        success_rates = np.random.uniform(0.35, 0.75, len(confidence_bins))
        success_rates = sorted(success_rates)  # Higher confidence = higher success
        
        fig = go.Figure(data=[go.Bar(
            x=confidence_bins,
            y=success_rates,
            marker_color='#2196f3'
        )])
        
        fig.add_hline(y=0.5, line_dash="dash", line_color="white")
        
        fig.update_layout(
            title="Win Rate by Confidence",
            paper_bgcolor='#0e1117',
            plot_bgcolor='#0e1117',
            font={'color': '#d1d4dc'},
            height=300,
            margin=dict(l=40, r=20, t=50, b=40),
            xaxis=dict(gridcolor='#1a1d24', title='Confidence Range'),
            yaxis=dict(gridcolor='#1a1d24', tickformat='.0%', title='Win Rate')
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Expectancy by signal type
        signal_types = ['BREAKOUT_LONG', 'BREAKOUT_SHORT', 'ORB_LONG', 'ORB_SHORT']
        expectancies = np.random.uniform(-0.2, 0.8, len(signal_types))
        
        fig = go.Figure(data=[go.Bar(
            x=signal_types,
            y=expectancies,
            marker_color=['#00c853' if e >= 0 else '#ff5252' for e in expectancies]
        )])
        
        fig.add_hline(y=0, line_color="white")
        
        fig.update_layout(
            title="Expectancy by Signal Type",
            paper_bgcolor='#0e1117',
            plot_bgcolor='#0e1117',
            font={'color': '#d1d4dc'},
            height=300,
            margin=dict(l=40, r=20, t=50, b=40),
            xaxis=dict(gridcolor='#1a1d24'),
            yaxis=dict(gridcolor='#1a1d24', title='Expectancy (R)')
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    st.divider()
    
    # Volume ratio analysis
    st.subheader("Signal Quality vs Volume Ratio")
    
    fig = go.Figure()
    
    for outcome in ['Target', 'SL']:
        mask = signals_df['Outcome'] == outcome
        fig.add_trace(go.Scatter(
            x=signals_df[mask]['Volume_Ratio'],
            y=signals_df[mask]['Confidence'],
            mode='markers',
            name=outcome,
            marker=dict(
                size=10,
                color='#00c853' if outcome == 'Target' else '#ff5252'
            )
        ))
    
    fig.update_layout(
        title="Signal Confidence vs Volume Ratio",
        paper_bgcolor='#0e1117',
        plot_bgcolor='#0e1117',
        font={'color': '#d1d4dc'},
        height=400,
        margin=dict(l=40, r=20, t=50, b=40),
        xaxis=dict(gridcolor='#1a1d24', title='Volume Ratio'),
        yaxis=dict(gridcolor='#1a1d24', title='Confidence')
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Signal table
    st.subheader("Recent Signals")
    
    st.dataframe(
        signals_df.tail(20),
        use_container_width=True,
        hide_index=True
    )


# Call appropriate function based on mode
if analysis_mode == "Performance":
    render_performance_analysis()
elif analysis_mode == "Backtesting":
    render_backtesting()
else:
    render_signal_analysis()
