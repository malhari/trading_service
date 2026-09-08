"""Positions panel component for the trading dashboard."""

import streamlit as st
import pandas as pd
from datetime import datetime, date
from typing import List, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import get_config, TradingMode
from core.models import OrderSide


def get_intraday_positions() -> List[dict]:
    """Get current intraday positions from order service."""
    # First try order service (actual executed orders)
    from services.order_service import get_order_service
    
    order_service = get_order_service()
    service_positions = order_service.get_positions()
    
    result = []
    
    # Convert service positions
    for pos in service_positions:
        if pos.get('status') == 'open':
            result.append({
                'symbol': pos['symbol'],
                'side': pos['side'],
                'quantity': pos['quantity'],
                'entry_price': pos['entry_price'],
                'current_price': pos.get('current_price', pos['entry_price']),
                'stop_loss': pos.get('stop_loss', pos['entry_price'] * 0.98),
                'target': pos.get('target', pos['entry_price'] * 1.04),
                'pnl': pos.get('pnl', 0),
                'pnl_percent': (pos.get('pnl', 0) / (pos['entry_price'] * pos['quantity']) * 100) if pos['entry_price'] > 0 else 0,
                'entry_time': datetime.now(),
                'sl_at_be': False,
                'source': 'order_service'
            })
    
    # Also get from old position tracker
    try:
        from core.position_tracker import get_position_tracker
        tracker = get_position_tracker()
        positions = tracker.get_all_positions()
        
        for pos in positions:
            # Skip if already in result
            if any(r['symbol'] == pos.symbol and r.get('source') == 'order_service' for r in result):
                continue
            
            result.append({
                'symbol': pos.symbol,
                'side': pos.side.value,
                'quantity': pos.quantity,
                'entry_price': pos.entry_price,
                'current_price': pos.current_price,
                'stop_loss': pos.stop_loss,
                'target': pos.target,
                'pnl': pos.pnl,
                'pnl_percent': pos.pnl_percent,
                'entry_time': pos.entry_time,
                'sl_at_be': pos.is_sl_at_breakeven,
                'source': 'tracker'
            })
    except Exception:
        pass
    
    return result


def get_swing_positions() -> List[dict]:
    """Get current swing positions."""
    from risk.swing_risk import get_swing_risk_guard
    
    guard = get_swing_risk_guard()
    positions = guard.get_all_positions()
    
    result = []
    for pos in positions:
        result.append({
            'symbol': pos.symbol,
            'side': pos.side.value,
            'quantity': pos.quantity,
            'entry_price': pos.entry_price,
            'current_price': pos.current_price,
            'stop_loss': pos.stop_loss,
            'target_1': pos.target_1,
            'target_2': pos.target_2,
            'target_3': pos.target_3,
            'pnl': pos.pnl,
            'pnl_percent': pos.pnl_percent,
            'entry_date': pos.entry_date,
            'holding_days': pos.holding_days,
            'sector': pos.sector,
            'trailing_active': pos.is_trailing_sl_active,
            'partial_exits': pos.partial_exits
        })
    
    # Add sample positions for demo if empty
    if not result:
        import numpy as np
        
        sample_positions = [
            {'symbol': 'HDFCBANK', 'side': 'BUY', 'quantity': 20, 'days': 5},
            {'symbol': 'TATAMOTORS', 'side': 'BUY', 'quantity': 50, 'days': 8},
            {'symbol': 'INFY', 'side': 'SELL', 'quantity': 15, 'days': 3},
        ]
        
        for sp in sample_positions:
            if np.random.random() > 0.3:  # 70% chance to show
                entry = np.random.uniform(500, 2500)
                current = entry * (1 + np.random.uniform(-0.05, 0.08))
                
                result.append({
                    'symbol': sp['symbol'],
                    'side': sp['side'],
                    'quantity': sp['quantity'],
                    'entry_price': entry,
                    'current_price': current,
                    'stop_loss': entry * 0.95 if sp['side'] == 'BUY' else entry * 1.05,
                    'target_1': entry * 1.06 if sp['side'] == 'BUY' else entry * 0.94,
                    'target_2': entry * 1.09 if sp['side'] == 'BUY' else entry * 0.91,
                    'target_3': entry * 1.15 if sp['side'] == 'BUY' else entry * 0.85,
                    'pnl': (current - entry) * sp['quantity'] if sp['side'] == 'BUY' else (entry - current) * sp['quantity'],
                    'pnl_percent': ((current - entry) / entry) * 100 if sp['side'] == 'BUY' else ((entry - current) / entry) * 100,
                    'entry_date': date.today(),
                    'holding_days': sp['days'],
                    'sector': 'banking' if 'BANK' in sp['symbol'] else 'auto' if 'TATA' in sp['symbol'] else 'it',
                    'trailing_active': np.random.random() > 0.5,
                    'partial_exits': np.random.randint(0, 2)
                })
    
    return result


def render_positions(mode: str = "intraday"):
    """
    Render the positions panel.
    
    Args:
        mode: Trading mode (intraday/swing).
    """
    if mode == "intraday":
        positions = get_intraday_positions()
    else:
        positions = get_swing_positions()
    
    if not positions:
        st.info("No open positions")
        return
    
    # Calculate totals
    total_pnl = sum(p['pnl'] for p in positions)
    total_value = sum(p['current_price'] * p['quantity'] for p in positions)
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Positions", len(positions))
    
    with col2:
        st.metric("Total Value", f"Rs.{total_value:,.0f}")
    
    with col3:
        pnl_color = "normal" if total_pnl >= 0 else "inverse"
        st.metric("Total P&L", f"Rs.{total_pnl:,.2f}", delta=f"{total_pnl:+,.2f}", delta_color=pnl_color)
    
    with col4:
        total_pnl_pct = (total_pnl / total_value * 100) if total_value > 0 else 0
        st.metric("P&L %", f"{total_pnl_pct:+.2f}%")
    
    st.markdown("---")
    
    # Render each position
    for pos in positions:
        render_position_row(pos, mode)


def render_position_row(pos: dict, mode: str):
    """Render a single position row."""
    symbol = pos['symbol']
    side = pos['side']
    quantity = pos['quantity']
    entry = pos['entry_price']
    current = pos['current_price']
    pnl = pos['pnl']
    pnl_pct = pos['pnl_percent']
    stop_loss = pos['stop_loss']
    
    # Colors
    side_color = "green" if side == "BUY" else "red"
    pnl_color = "green" if pnl >= 0 else "red"
    
    # Main row
    col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
    
    with col1:
        st.markdown(f"**{symbol}**")
        st.markdown(f":{side_color}[{side}] x {quantity}")
    
    with col2:
        st.caption("Entry")
        st.write(f"{entry:.2f}")
    
    with col3:
        st.caption("Current")
        st.write(f"{current:.2f}")
    
    with col4:
        st.caption("P&L")
        st.markdown(f":{pnl_color}[Rs.{pnl:,.2f}]")
        st.markdown(f":{pnl_color}[{pnl_pct:+.2f}%]")
    
    with col5:
        st.caption("SL")
        sl_hit = (current <= stop_loss if side == "BUY" else current >= stop_loss)
        sl_color = "red" if sl_hit else "gray"
        st.markdown(f":{sl_color}[{stop_loss:.2f}]")
    
    # Additional info for swing
    if mode == "swing":
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.caption(f"Holding: {pos.get('holding_days', 0)} days")
        
        with col2:
            st.caption(f"Sector: {pos.get('sector', 'N/A')}")
        
        with col3:
            if pos.get('trailing_active'):
                st.caption("Trailing SL: ACTIVE")
            else:
                st.caption("Trailing SL: OFF")
        
        with col4:
            if pos.get('partial_exits', 0) > 0:
                st.caption(f"Partial exits: {pos['partial_exits']}")
    
    # Action buttons
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("Close", key=f"close_{symbol}_{mode}", use_container_width=True):
            close_position(symbol, mode)
    
    with col2:
        if mode == "swing":
            if st.button("Partial", key=f"partial_{symbol}_{mode}", use_container_width=True):
                partial_close_position(symbol, mode)
    
    with col3:
        if st.button("Modify SL", key=f"modify_{symbol}_{mode}", use_container_width=True):
            modify_stop_loss(symbol, pos, mode)
    
    st.markdown("---")


def close_position(symbol: str, mode: str):
    """Close a position."""
    config = get_config()
    
    if config.mode == TradingMode.PAPER:
        if mode == "intraday":
            from core.position_tracker import get_position_tracker
            tracker = get_position_tracker()
            # Get current price (mock)
            import numpy as np
            current_price = np.random.uniform(1000, 3000)
            tracker.close_position(symbol, current_price, "manual")
        else:
            from risk.swing_risk import get_swing_risk_guard
            guard = get_swing_risk_guard()
            pos = guard.get_position(symbol)
            if pos:
                guard.close_position(symbol, pos.current_price, "manual")
        
        st.success(f"Position {symbol} closed")
        st.rerun()
    else:
        st.warning("Live trading - confirm in order panel")


def partial_close_position(symbol: str, mode: str):
    """Partial close a swing position."""
    st.session_state['partial_close'] = {
        'symbol': symbol,
        'mode': mode
    }
    st.info("Enter quantity to close in Order Panel")


def modify_stop_loss(symbol: str, pos: dict, mode: str):
    """Show dialog to modify stop loss."""
    st.session_state['modify_sl'] = {
        'symbol': symbol,
        'current_sl': pos['stop_loss'],
        'mode': mode
    }
    st.info("Enter new SL in Order Panel")


def render_position_summary(mode: str = "intraday"):
    """Render a compact position summary."""
    if mode == "intraday":
        positions = get_intraday_positions()
    else:
        positions = get_swing_positions()
    
    if not positions:
        st.caption("No positions")
        return
    
    total_pnl = sum(p['pnl'] for p in positions)
    pnl_color = "green" if total_pnl >= 0 else "red"
    
    st.metric(
        f"{len(positions)} Positions",
        f"Rs.{total_pnl:,.2f}",
        delta=f"{total_pnl:+,.2f}"
    )


def get_position_alerts(mode: str = "intraday") -> List[dict]:
    """Get alerts for positions needing attention."""
    if mode == "intraday":
        positions = get_intraday_positions()
    else:
        positions = get_swing_positions()
    
    alerts = []
    
    for pos in positions:
        # Check if near stop loss
        if pos['side'] == 'BUY':
            distance_to_sl = (pos['current_price'] - pos['stop_loss']) / pos['current_price'] * 100
        else:
            distance_to_sl = (pos['stop_loss'] - pos['current_price']) / pos['current_price'] * 100
        
        if distance_to_sl < 1:
            alerts.append({
                'symbol': pos['symbol'],
                'type': 'NEAR_SL',
                'message': f"Near stop loss ({distance_to_sl:.1f}% away)"
            })
        
        # Check if swing position held too long
        if mode == "swing" and pos.get('holding_days', 0) >= 12:
            alerts.append({
                'symbol': pos['symbol'],
                'type': 'LONG_HOLDING',
                'message': f"Held for {pos['holding_days']} days - review"
            })
    
    return alerts
