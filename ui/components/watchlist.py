"""Watchlist panel component for the trading dashboard."""

import streamlit as st
import pandas as pd
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import get_config
from scanner.equity_scanner import get_scanner


def get_watchlist_data(mode: str = "intraday") -> pd.DataFrame:
    """
    Get watchlist data with prices and trends.
    
    Args:
        mode: Trading mode (intraday/swing).
    
    Returns:
        DataFrame with watchlist data.
    """
    config = get_config()
    watchlist = config.get_active_watchlist()
    scanner = get_scanner()
    
    data = []
    
    for symbol in watchlist.symbols:
        df = scanner.get_historical_data(symbol)
        
        if df.empty:
            # Generate sample data
            import numpy as np
            price = np.random.uniform(500, 3000)
            change = np.random.uniform(-3, 4)
            volume_ratio = np.random.uniform(0.5, 2.5)
            trend = np.random.choice(['uptrend', 'downtrend', 'sideways'])
            strength = np.random.uniform(0.3, 0.8)
            atr_pct = np.random.uniform(1.5, 3.5)
        else:
            price = df.iloc[-1]['close']
            prev_close = df.iloc[-2]['close'] if len(df) > 1 else price
            change = ((price - prev_close) / prev_close) * 100
            
            # Calculate trend
            if mode == "swing":
                from strategies.swing_levels import SwingLevelCalculator
                calc = SwingLevelCalculator()
                trend_analysis = calc.analyze_trend(df)
                trend = trend_analysis.direction
                strength = trend_analysis.strength
                atr_pct = trend_analysis.atr_percent
            else:
                from strategies.sr_levels import SRLevelCalculator
                calc = SRLevelCalculator()
                atr = calc.calculate_atr(df)
                atr_pct = (atr / price) * 100 if price > 0 else 0
                
                # Simple trend based on recent closes
                if len(df) >= 5:
                    recent = df.tail(5)['close']
                    if recent.iloc[-1] > recent.iloc[0] * 1.02:
                        trend = 'uptrend'
                        strength = 0.6
                    elif recent.iloc[-1] < recent.iloc[0] * 0.98:
                        trend = 'downtrend'
                        strength = 0.6
                    else:
                        trend = 'sideways'
                        strength = 0.3
                else:
                    trend = 'sideways'
                    strength = 0.3
            
            # Volume ratio
            if len(df) >= 20:
                avg_vol = df['volume'].tail(20).mean()
                current_vol = df.iloc[-1]['volume']
                volume_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
            else:
                volume_ratio = 1.0
        
        data.append({
            'Symbol': symbol,
            'Price': price,
            'Change%': change,
            'Trend': trend,
            'Strength': strength,
            'ATR%': atr_pct,
            'Vol Ratio': volume_ratio
        })
    
    return pd.DataFrame(data)


def render_watchlist(mode: str = "intraday"):
    """
    Render the watchlist panel.
    
    Args:
        mode: Trading mode (intraday/swing).
    """
    # Get watchlist data
    df = get_watchlist_data(mode)
    
    if df.empty:
        st.info("No symbols in watchlist")
        return
    
    # Filters
    col1, col2 = st.columns(2)
    
    with col1:
        trend_filter = st.selectbox(
            "Trend",
            options=["All", "Uptrend", "Downtrend", "Sideways"],
            key=f"trend_filter_{mode}"
        )
    
    with col2:
        sort_by = st.selectbox(
            "Sort by",
            options=["Symbol", "Change%", "Strength", "Vol Ratio"],
            key=f"sort_by_{mode}"
        )
    
    # Apply filters
    if trend_filter != "All":
        df = df[df['Trend'] == trend_filter.lower()]
    
    # Sort
    ascending = sort_by == "Symbol"
    df = df.sort_values(sort_by, ascending=ascending)
    
    # Render watchlist items
    st.markdown("---")
    
    for _, row in df.iterrows():
        render_watchlist_item(row, mode)


def render_watchlist_item(row: pd.Series, mode: str):
    """Render a single watchlist item."""
    symbol = row['Symbol']
    price = row['Price']
    change = row['Change%']
    trend = row['Trend']
    strength = row['Strength']
    atr = row['ATR%']
    vol_ratio = row['Vol Ratio']
    
    # Color based on change
    change_color = "green" if change >= 0 else "red"
    
    # Trend indicator
    if trend == 'uptrend':
        trend_icon = "UP"
        trend_color = "green"
    elif trend == 'downtrend':
        trend_icon = "DN"
        trend_color = "red"
    else:
        trend_icon = "--"
        trend_color = "orange"
    
    # Create clickable item
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        if st.button(
            f"**{symbol}**",
            key=f"wl_{symbol}_{mode}",
            use_container_width=True
        ):
            st.session_state.selected_symbol = symbol
            st.rerun()
        
        st.caption(f"Rs.{price:,.2f}")
    
    with col2:
        st.markdown(f":{change_color}[{change:+.2f}%]")
        st.markdown(f":{trend_color}[{trend_icon}]")
    
    with col3:
        # Volume indicator
        if vol_ratio >= 1.5:
            vol_icon = "HIGH"
            vol_color = "green"
        elif vol_ratio <= 0.7:
            vol_icon = "LOW"
            vol_color = "red"
        else:
            vol_icon = "AVG"
            vol_color = "gray"
        
        st.caption(f"Vol: :{vol_color}[{vol_icon}]")
        st.caption(f"ATR: {atr:.1f}%")
    
    st.markdown("---")


def render_compact_watchlist(mode: str = "intraday", max_items: int = 10):
    """Render a compact version of the watchlist."""
    df = get_watchlist_data(mode)
    
    if df.empty:
        return
    
    # Show top movers
    df_sorted = df.sort_values('Change%', ascending=False)
    
    st.markdown("**Top Movers**")
    
    for _, row in df_sorted.head(max_items).iterrows():
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.write(row['Symbol'])
        
        with col2:
            change_color = "green" if row['Change%'] >= 0 else "red"
            st.markdown(f":{change_color}[{row['Change%']:+.2f}%]")


def get_sector_breakdown(mode: str = "intraday") -> dict:
    """Get sector breakdown of watchlist."""
    from risk.swing_risk import SECTOR_MAP
    
    config = get_config()
    watchlist = config.get_active_watchlist()
    
    sectors = {}
    for symbol in watchlist.symbols:
        sector = SECTOR_MAP.get(symbol, "other")
        sectors[sector] = sectors.get(sector, 0) + 1
    
    return sectors
