"""Risk metrics dashboard component for the trading dashboard."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, date
from typing import Dict, List
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import get_config


def get_intraday_risk_metrics() -> Dict:
    """Get intraday risk metrics."""
    from risk.risk_guard import get_risk_guard
    from core.position_tracker import get_position_tracker
    
    config = get_config()
    guard = get_risk_guard()
    tracker = get_position_tracker()
    
    status = guard.get_risk_status()
    positions = tracker.get_all_positions()
    
    # Use total_pnl from status (realized + unrealized)
    total_pnl = status.get('total_pnl', 0.0)
    daily_loss_limit = status.get('daily_loss_limit', config.risk.max_daily_loss * config.capital)
    
    return {
        'capital': config.capital,
        'daily_pnl': total_pnl,
        'daily_pnl_percent': (total_pnl / config.capital) * 100 if config.capital > 0 else 0,
        'daily_loss_limit': daily_loss_limit,
        'loss_limit_used': status.get('loss_limit_used_percent', 0.0),
        'max_positions': config.risk.max_positions,
        'current_positions': len(positions),
        'circuit_breaker': status.get('circuit_breaker_triggered', False),
        'trades_today': status.get('trades_taken', 0),
        'capital_utilized': sum(p.entry_price * p.quantity for p in positions),
        'positions': positions
    }


def get_swing_risk_metrics() -> Dict:
    """Get swing risk metrics."""
    from risk.swing_risk import get_swing_risk_guard
    
    config = get_config()
    guard = get_swing_risk_guard()
    
    status = guard.get_risk_status()
    positions = guard.get_all_positions()
    
    # Use total_pnl_weekly from status
    weekly_pnl = status.get('total_pnl_weekly', 0.0)
    weekly_loss_limit = config.swing_risk.max_weekly_loss * config.capital
    
    # Calculate loss limit used
    loss_limit_used = 0.0
    if weekly_pnl < 0 and weekly_loss_limit > 0:
        loss_limit_used = (abs(weekly_pnl) / weekly_loss_limit) * 100
    
    return {
        'capital': config.capital,
        'weekly_pnl': weekly_pnl,
        'weekly_pnl_percent': (weekly_pnl / config.capital) * 100 if config.capital > 0 else 0,
        'weekly_loss_limit': weekly_loss_limit,
        'loss_limit_used': loss_limit_used,
        'max_positions': config.swing_risk.max_positions,
        'current_positions': len(positions),
        'sector_exposure': status.get('sector_exposure', {}),
        'max_sector_exposure': config.swing_risk.max_sector_exposure,
        'trades_this_week': status.get('trades_this_week', 0),
        'capital_utilized': status.get('total_position_value', 0),
        'positions': positions
    }


def render_risk_dashboard(mode: str = "intraday"):
    """
    Render the risk metrics dashboard.
    
    Args:
        mode: Trading mode (intraday/swing).
    """
    if mode == "intraday":
        metrics = get_intraday_risk_metrics()
        render_intraday_risk(metrics)
    else:
        metrics = get_swing_risk_metrics()
        render_swing_risk(metrics)


def render_intraday_risk(metrics: Dict):
    """Render intraday risk metrics."""
    # Circuit breaker warning
    if metrics.get('circuit_breaker', False):
        st.error("CIRCUIT BREAKER ACTIVE - Trading paused", icon="🚫")
    
    # Main metrics row
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        pnl_delta = "normal" if metrics['daily_pnl'] >= 0 else "inverse"
        st.metric(
            "Daily P&L",
            f"Rs.{metrics['daily_pnl']:,.2f}",
            delta=f"{metrics['daily_pnl_percent']:+.2f}%",
            delta_color=pnl_delta
        )
    
    with col2:
        st.metric(
            "Capital Utilized",
            f"Rs.{metrics['capital_utilized']:,.0f}",
            delta=f"{(metrics['capital_utilized']/metrics['capital']*100):.1f}%"
        )
    
    with col3:
        st.metric(
            "Positions",
            f"{metrics['current_positions']}/{metrics['max_positions']}"
        )
    
    with col4:
        st.metric(
            "Trades Today",
            metrics['trades_today']
        )
    
    with col5:
        st.metric(
            "Risk Limit",
            f"{metrics['loss_limit_used']:.1f}%"
        )
    
    # Risk gauge
    st.markdown("---")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # P&L gauge
        render_pnl_gauge(
            current=metrics['daily_pnl'],
            limit=-metrics['daily_loss_limit'],
            title="Daily P&L vs Loss Limit"
        )
    
    with col2:
        # Position utilization
        render_utilization_bar(
            current=metrics['current_positions'],
            max_val=metrics['max_positions'],
            title="Position Slots"
        )
        
        render_utilization_bar(
            current=metrics['capital_utilized'],
            max_val=metrics['capital'] * 0.8,  # 80% max
            title="Capital Usage",
            is_currency=True
        )


def render_swing_risk(metrics: Dict):
    """Render swing risk metrics."""
    # Main metrics row
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        pnl_delta = "normal" if metrics['weekly_pnl'] >= 0 else "inverse"
        st.metric(
            "Weekly P&L",
            f"Rs.{metrics['weekly_pnl']:,.2f}",
            delta=f"{metrics['weekly_pnl_percent']:+.2f}%",
            delta_color=pnl_delta
        )
    
    with col2:
        st.metric(
            "Capital Utilized",
            f"Rs.{metrics['capital_utilized']:,.0f}",
            delta=f"{(metrics['capital_utilized']/metrics['capital']*100):.1f}%"
        )
    
    with col3:
        st.metric(
            "Positions",
            f"{metrics['current_positions']}/{metrics['max_positions']}"
        )
    
    with col4:
        st.metric(
            "Trades This Week",
            metrics['trades_this_week']
        )
    
    with col5:
        st.metric(
            "Risk Limit",
            f"{metrics['loss_limit_used']:.1f}%"
        )
    
    st.markdown("---")
    
    # Sector exposure and P&L gauge
    col1, col2 = st.columns(2)
    
    with col1:
        render_sector_exposure(metrics['sector_exposure'], metrics['max_sector_exposure'])
    
    with col2:
        render_pnl_gauge(
            current=metrics['weekly_pnl'],
            limit=-metrics['weekly_loss_limit'],
            title="Weekly P&L vs Loss Limit"
        )


def render_pnl_gauge(current: float, limit: float, title: str = "P&L"):
    """Render a P&L gauge chart."""
    # Determine color
    if current >= 0:
        color = "#00c853"
    elif current > limit * 0.5:
        color = "#ffc107"
    else:
        color = "#ff5252"
    
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=current,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': title, 'font': {'color': '#d1d4dc'}},
        number={'prefix': "Rs.", 'font': {'color': '#d1d4dc'}},
        delta={'reference': 0, 'increasing': {'color': "#00c853"}, 'decreasing': {'color': "#ff5252"}},
        gauge={
            'axis': {'range': [limit, abs(limit)], 'tickcolor': '#d1d4dc'},
            'bar': {'color': color},
            'bgcolor': "#1a1d24",
            'bordercolor': "#2d3139",
            'steps': [
                {'range': [limit, limit * 0.5], 'color': "rgba(255, 82, 82, 0.3)"},
                {'range': [limit * 0.5, 0], 'color': "rgba(255, 193, 7, 0.3)"},
                {'range': [0, abs(limit)], 'color': "rgba(0, 200, 83, 0.3)"}
            ],
            'threshold': {
                'line': {'color': "#ff5252", 'width': 2},
                'thickness': 0.75,
                'value': limit
            }
        }
    ))
    
    fig.update_layout(
        paper_bgcolor='#0e1117',
        plot_bgcolor='#0e1117',
        font={'color': '#d1d4dc'},
        height=250,
        margin=dict(l=20, r=20, t=50, b=20)
    )
    
    st.plotly_chart(fig, use_container_width=True)


def render_utilization_bar(current: float, max_val: float, title: str, is_currency: bool = False):
    """Render a utilization progress bar."""
    pct = min((current / max_val * 100) if max_val > 0 else 0, 100)
    
    # Determine color
    if pct < 50:
        color = "green"
    elif pct < 80:
        color = "orange"
    else:
        color = "red"
    
    if is_currency:
        current_text = f"Rs.{current:,.0f}"
        max_text = f"Rs.{max_val:,.0f}"
    else:
        current_text = str(int(current))
        max_text = str(int(max_val))
    
    st.caption(f"{title}: {current_text} / {max_text}")
    st.progress(pct / 100)


def render_sector_exposure(exposure: Dict[str, float], max_exposure: float):
    """Render sector exposure pie chart."""
    if not exposure:
        # Sample data
        import numpy as np
        exposure = {
            'banking': np.random.uniform(0.1, 0.3),
            'it': np.random.uniform(0.1, 0.25),
            'auto': np.random.uniform(0.05, 0.2),
            'fmcg': np.random.uniform(0.05, 0.15),
            'other': np.random.uniform(0.05, 0.1)
        }
    
    # Filter non-zero sectors
    exposure = {k: v for k, v in exposure.items() if v > 0}
    
    if not exposure:
        st.info("No sector exposure")
        return
    
    # Create pie chart
    fig = go.Figure(data=[go.Pie(
        labels=list(exposure.keys()),
        values=list(exposure.values()),
        hole=0.4,
        marker=dict(colors=px.colors.qualitative.Set2)
    )])
    
    fig.update_layout(
        title="Sector Exposure",
        paper_bgcolor='#0e1117',
        plot_bgcolor='#0e1117',
        font={'color': '#d1d4dc'},
        height=250,
        margin=dict(l=20, r=20, t=50, b=20),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.2,
            xanchor="center",
            x=0.5
        )
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Check for over-exposure
    for sector, exp in exposure.items():
        if exp > max_exposure:
            st.warning(f"Over-exposed in {sector}: {exp:.1%} (max: {max_exposure:.1%})")


def render_win_rate_metrics(mode: str = "intraday"):
    """Render win rate and performance metrics."""
    import numpy as np
    
    # Sample metrics
    metrics = {
        'win_rate': np.random.uniform(0.45, 0.60),
        'avg_win': np.random.uniform(500, 2000),
        'avg_loss': np.random.uniform(200, 800),
        'profit_factor': np.random.uniform(1.2, 2.5),
        'expectancy': np.random.uniform(100, 500),
        'max_drawdown': np.random.uniform(0.05, 0.15)
    }
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Win Rate", f"{metrics['win_rate']:.1%}")
        st.metric("Profit Factor", f"{metrics['profit_factor']:.2f}")
    
    with col2:
        st.metric("Avg Win", f"Rs.{metrics['avg_win']:,.0f}")
        st.metric("Avg Loss", f"Rs.{metrics['avg_loss']:,.0f}")
    
    with col3:
        st.metric("Expectancy", f"Rs.{metrics['expectancy']:,.0f}")
        st.metric("Max Drawdown", f"{metrics['max_drawdown']:.1%}")


def render_pnl_chart(mode: str = "intraday", days: int = 30):
    """Render P&L chart over time."""
    import numpy as np
    
    # Generate sample data
    dates = pd.date_range(end=date.today(), periods=days, freq='D')
    pnl = np.cumsum(np.random.normal(200, 500, days))
    
    df = pd.DataFrame({
        'Date': dates,
        'P&L': pnl
    })
    
    fig = go.Figure()
    
    # Add line
    fig.add_trace(go.Scatter(
        x=df['Date'],
        y=df['P&L'],
        mode='lines',
        name='Cumulative P&L',
        line=dict(color='#2196f3', width=2),
        fill='tozeroy',
        fillcolor='rgba(33, 150, 243, 0.1)'
    ))
    
    # Add zero line
    fig.add_hline(y=0, line_dash="dash", line_color="#666")
    
    fig.update_layout(
        title=f"Cumulative P&L ({days} Days)",
        paper_bgcolor='#0e1117',
        plot_bgcolor='#0e1117',
        font={'color': '#d1d4dc'},
        height=300,
        margin=dict(l=40, r=20, t=50, b=40),
        xaxis=dict(gridcolor='#1a1d24'),
        yaxis=dict(gridcolor='#1a1d24', tickprefix='Rs.')
    )
    
    st.plotly_chart(fig, use_container_width=True)


def render_compact_risk_bar(mode: str = "intraday"):
    """Render a compact risk status bar."""
    if mode == "intraday":
        metrics = get_intraday_risk_metrics()
        pnl_key = "daily_pnl"
        pnl_label = "Daily"
    else:
        metrics = get_swing_risk_metrics()
        pnl_key = "weekly_pnl"
        pnl_label = "Weekly"
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        pnl = metrics[pnl_key]
        color = "green" if pnl >= 0 else "red"
        st.markdown(f"**{pnl_label} P&L:** :{color}[Rs.{pnl:,.2f}]")
    
    with col2:
        st.markdown(f"**Positions:** {metrics['current_positions']}/{metrics['max_positions']}")
    
    with col3:
        util = (metrics['capital_utilized'] / metrics['capital']) * 100
        st.markdown(f"**Capital:** {util:.1f}%")
    
    with col4:
        risk = metrics['loss_limit_used']
        risk_color = "green" if risk < 50 else "orange" if risk < 80 else "red"
        st.markdown(f"**Risk:** :{risk_color}[{risk:.1f}%]")
