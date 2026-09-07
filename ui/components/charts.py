"""TradingView Lightweight Charts component for the trading dashboard."""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scanner.equity_scanner import get_scanner
from core.config import get_config


def get_chart_data(symbol: str, timeframe: str = "D", days: int = 90) -> pd.DataFrame:
    """
    Get OHLC data for charting.
    
    Args:
        symbol: Trading symbol.
        timeframe: Chart timeframe (1m, 5m, 15m, D, W).
        days: Number of days of data.
    
    Returns:
        DataFrame with OHLC data.
    """
    scanner = get_scanner()
    
    # Load data if not already loaded
    if symbol not in scanner._historical_data or scanner._historical_data[symbol].empty:
        # Generate sample data for demo
        import numpy as np
        
        if timeframe in ["1m", "5m", "15m"]:
            # Intraday data
            periods = 390 if timeframe == "1m" else (78 if timeframe == "5m" else 26)
            freq = "1min" if timeframe == "1m" else ("5min" if timeframe == "5m" else "15min")
            dates = pd.date_range(
                end=datetime.now(),
                periods=periods,
                freq=freq
            )
        else:
            # Daily/Weekly data
            dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
        
        data = []
        price = np.random.uniform(500, 3000)
        
        for dt in dates:
            trend = np.random.uniform(-0.002, 0.004)
            price = price * (1 + trend)
            o = price * (1 + np.random.uniform(-0.01, 0.01))
            h = o * (1 + np.random.uniform(0, 0.02))
            l = o * (1 - np.random.uniform(0, 0.02))
            c = np.random.uniform(l, h)
            v = int(np.random.uniform(100000, 5000000))
            
            data.append({
                'time': dt,
                'open': round(o, 2),
                'high': round(h, 2),
                'low': round(l, 2),
                'close': round(c, 2),
                'volume': v
            })
            price = c
        
        return pd.DataFrame(data)
    
    df = scanner.get_historical_data(symbol)
    if df.empty:
        return pd.DataFrame()
    
    # Rename columns for chart
    df = df.rename(columns={'timestamp': 'time'})
    
    return df


def get_sr_levels(symbol: str, mode: str = "intraday") -> List[dict]:
    """
    Get support/resistance levels for overlay.
    
    Args:
        symbol: Trading symbol.
        mode: Trading mode (intraday/swing).
    
    Returns:
        List of level dicts with price and type.
    """
    scanner = get_scanner()
    df = scanner.get_historical_data(symbol)
    
    if df.empty:
        return []
    
    levels = []
    
    if mode == "swing":
        from strategies.swing_levels import SwingLevelCalculator
        calc = SwingLevelCalculator()
        sr_levels = calc.calculate_all_swing_levels(df)
    else:
        from strategies.sr_levels import SRLevelCalculator
        calc = SRLevelCalculator()
        sr_levels = calc.calculate_all_levels(df)
    
    for level in sr_levels.get('all', [])[:10]:  # Top 10 levels
        levels.append({
            'price': level.price,
            'type': level.level_type,
            'color': '#00c853' if level.level_type == 'support' else '#ff5252'
        })
    
    return levels


def render_chart(symbol: Optional[str], timeframe: str = "D", mode: str = "intraday"):
    """
    Render TradingView-style chart.
    
    Args:
        symbol: Trading symbol to display.
        timeframe: Chart timeframe.
        mode: Trading mode.
    """
    config = get_config()
    
    # Symbol selector if none selected
    if not symbol:
        watchlist = config.get_active_watchlist()
        symbol = st.selectbox(
            "Select Symbol",
            options=watchlist.symbols,
            key="chart_symbol_select"
        )
        st.session_state.selected_symbol = symbol
    
    if not symbol:
        st.info("Select a symbol to view chart")
        return
    
    # Timeframe selector
    if mode == "intraday":
        tf_options = ["1m", "5m", "15m"]
        tf_labels = ["1 Min", "5 Min", "15 Min"]
    else:
        tf_options = ["D", "W"]
        tf_labels = ["Daily", "Weekly"]
    
    selected_tf = st.radio(
        "Timeframe",
        options=tf_options,
        format_func=lambda x: tf_labels[tf_options.index(x)],
        horizontal=True,
        label_visibility="collapsed"
    )
    
    # Get chart data
    df = get_chart_data(symbol, selected_tf)
    
    if df.empty:
        st.warning(f"No data available for {symbol}")
        return
    
    # Try to use streamlit-lightweight-charts
    try:
        from streamlit_lightweight_charts import renderLightweightCharts
        
        # Prepare candlestick data
        candle_data = []
        for _, row in df.iterrows():
            candle_data.append({
                'time': row['time'].strftime('%Y-%m-%d') if hasattr(row['time'], 'strftime') else str(row['time']),
                'open': row['open'],
                'high': row['high'],
                'low': row['low'],
                'close': row['close']
            })
        
        # Prepare volume data
        volume_data = []
        for _, row in df.iterrows():
            color = '#26a69a' if row['close'] >= row['open'] else '#ef5350'
            volume_data.append({
                'time': row['time'].strftime('%Y-%m-%d') if hasattr(row['time'], 'strftime') else str(row['time']),
                'value': row['volume'],
                'color': color
            })
        
        # Chart options
        chart_options = {
            "layout": {
                "background": {"color": "#0e1117"},
                "textColor": "#d1d4dc"
            },
            "grid": {
                "vertLines": {"color": "#1a1d24"},
                "horzLines": {"color": "#1a1d24"}
            },
            "crosshair": {
                "mode": 0
            },
            "rightPriceScale": {
                "borderColor": "#2d3139"
            },
            "timeScale": {
                "borderColor": "#2d3139",
                "timeVisible": True
            }
        }
        
        # Series
        series = [
            {
                "type": "Candlestick",
                "data": candle_data,
                "options": {
                    "upColor": "#26a69a",
                    "downColor": "#ef5350",
                    "borderUpColor": "#26a69a",
                    "borderDownColor": "#ef5350",
                    "wickUpColor": "#26a69a",
                    "wickDownColor": "#ef5350"
                }
            },
            {
                "type": "Histogram",
                "data": volume_data,
                "options": {
                    "priceFormat": {"type": "volume"},
                    "priceScaleId": "volume"
                },
                "priceScale": {
                    "scaleMargins": {"top": 0.8, "bottom": 0}
                }
            }
        ]
        
        # Add S/R levels as lines
        sr_levels = get_sr_levels(symbol, mode)
        for level in sr_levels[:5]:  # Top 5 levels
            series.append({
                "type": "Line",
                "data": [
                    {"time": candle_data[0]['time'], "value": level['price']},
                    {"time": candle_data[-1]['time'], "value": level['price']}
                ],
                "options": {
                    "color": level['color'],
                    "lineWidth": 1,
                    "lineStyle": 2,  # Dashed
                    "title": level['type']
                }
            })
        
        renderLightweightCharts([
            {
                "chart": chart_options,
                "series": series
            }
        ], key=f"chart_{symbol}_{selected_tf}")
        
    except ImportError:
        # Fallback to plotly
        render_plotly_chart(df, symbol, sr_levels if 'sr_levels' in dir() else [])


def render_plotly_chart(df: pd.DataFrame, symbol: str, sr_levels: List[dict] = None):
    """Fallback chart using Plotly."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    
    # Create figure with secondary y-axis
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3]
    )
    
    # Candlestick chart
    fig.add_trace(
        go.Candlestick(
            x=df['time'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name=symbol,
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350'
        ),
        row=1, col=1
    )
    
    # Volume bars
    colors = ['#26a69a' if close >= open else '#ef5350' 
              for close, open in zip(df['close'], df['open'])]
    
    fig.add_trace(
        go.Bar(
            x=df['time'],
            y=df['volume'],
            name='Volume',
            marker_color=colors
        ),
        row=2, col=1
    )
    
    # Add S/R levels
    if sr_levels:
        for level in sr_levels[:5]:
            fig.add_hline(
                y=level['price'],
                line_dash="dash",
                line_color=level['color'],
                annotation_text=level['type'],
                row=1, col=1
            )
    
    # Update layout
    fig.update_layout(
        title=f"{symbol}",
        template="plotly_dark",
        paper_bgcolor='#0e1117',
        plot_bgcolor='#0e1117',
        xaxis_rangeslider_visible=False,
        height=500,
        showlegend=False,
        margin=dict(l=0, r=0, t=30, b=0)
    )
    
    fig.update_xaxes(gridcolor='#1a1d24')
    fig.update_yaxes(gridcolor='#1a1d24')
    
    st.plotly_chart(fig, use_container_width=True)


def render_mini_chart(symbol: str, height: int = 100):
    """Render a small sparkline chart for watchlist."""
    df = get_chart_data(symbol, "D", days=30)
    
    if df.empty:
        return
    
    # Simple line chart
    import plotly.graph_objects as go
    
    color = '#26a69a' if df.iloc[-1]['close'] >= df.iloc[0]['close'] else '#ef5350'
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df['time'],
        y=df['close'],
        mode='lines',
        line=dict(color=color, width=1),
        fill='tozeroy',
        fillcolor=f"rgba({','.join([str(int(color[i:i+2], 16)) for i in (1, 3, 5)])}, 0.1)"
    ))
    
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False)
    )
    
    st.plotly_chart(fig, use_container_width=True, key=f"mini_{symbol}")
