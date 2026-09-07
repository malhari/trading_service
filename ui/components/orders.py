"""Order execution panel component for the trading dashboard."""

import streamlit as st
from datetime import datetime
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import get_config, TradingMode
from core.models import OrderSide, OrderType


def calculate_quantity(
    capital: float,
    risk_percent: float,
    entry_price: float,
    stop_loss: float
) -> int:
    """
    Calculate position size based on risk.
    
    Args:
        capital: Trading capital.
        risk_percent: Risk percentage (0.01 = 1%).
        entry_price: Entry price.
        stop_loss: Stop loss price.
    
    Returns:
        Calculated quantity.
    """
    risk_amount = capital * risk_percent
    risk_per_share = abs(entry_price - stop_loss)
    
    if risk_per_share == 0:
        return 0
    
    quantity = int(risk_amount / risk_per_share)
    return max(1, quantity)


def render_order_panel(mode: str = "intraday"):
    """
    Render the order execution panel.
    
    Args:
        mode: Trading mode (intraday/swing).
    """
    config = get_config()
    
    # Mode indicator
    if config.mode == TradingMode.PAPER:
        st.info("PAPER TRADING MODE", icon="📝")
    else:
        st.error("LIVE TRADING MODE", icon="🔴")
    
    # Check for pending order from signals
    pending = st.session_state.get('pending_order')
    
    # Check for modify SL request
    modify_sl = st.session_state.get('modify_sl')
    
    if modify_sl:
        render_modify_sl_form(modify_sl, mode)
        return
    
    # Get watchlist
    watchlist = config.get_active_watchlist()
    
    # Symbol selector
    default_symbol = pending['symbol'] if pending else (st.session_state.get('selected_symbol') or watchlist.symbols[0])
    default_idx = watchlist.symbols.index(default_symbol) if default_symbol in watchlist.symbols else 0
    
    symbol = st.selectbox(
        "Symbol",
        options=watchlist.symbols,
        index=default_idx,
        key=f"order_symbol_{mode}"
    )
    
    # Side selector
    col1, col2 = st.columns(2)
    
    with col1:
        buy_type = "primary" if not pending or pending.get('side') == 'BUY' else "secondary"
        if st.button("BUY", use_container_width=True, type=buy_type, key=f"buy_btn_{mode}"):
            st.session_state['order_side'] = 'BUY'
    
    with col2:
        sell_type = "primary" if pending and pending.get('side') == 'SELL' else "secondary"
        if st.button("SELL", use_container_width=True, type=sell_type, key=f"sell_btn_{mode}"):
            st.session_state['order_side'] = 'SELL'
    
    side = st.session_state.get('order_side', pending.get('side', 'BUY') if pending else 'BUY')
    
    st.markdown("---")
    
    # Order type
    order_type = st.radio(
        "Order Type",
        options=["MARKET", "LIMIT"],
        horizontal=True,
        key=f"order_type_{mode}"
    )
    
    # Price inputs
    col1, col2 = st.columns(2)
    
    with col1:
        default_entry = pending.get('entry', 0) if pending else 0
        entry_price = st.number_input(
            "Entry Price" if order_type == "LIMIT" else "Approx. Price",
            min_value=0.0,
            value=float(default_entry),
            step=0.05,
            key=f"entry_price_{mode}"
        )
    
    with col2:
        default_sl = pending.get('stop_loss', 0) if pending else 0
        stop_loss = st.number_input(
            "Stop Loss",
            min_value=0.0,
            value=float(default_sl),
            step=0.05,
            key=f"stop_loss_{mode}"
        )
    
    # Target
    default_target = pending.get('target', 0) if pending else 0
    target = st.number_input(
        "Target",
        min_value=0.0,
        value=float(default_target),
        step=0.05,
        key=f"target_{mode}"
    )
    
    st.markdown("---")
    
    # Quantity calculation
    risk_config = config.get_active_risk_config()
    
    # Auto-calculate quantity
    if entry_price > 0 and stop_loss > 0:
        suggested_qty = calculate_quantity(
            capital=config.capital,
            risk_percent=risk_config.risk_per_trade,
            entry_price=entry_price,
            stop_loss=stop_loss
        )
    else:
        suggested_qty = 1
    
    col1, col2 = st.columns(2)
    
    with col1:
        quantity = st.number_input(
            "Quantity",
            min_value=1,
            value=suggested_qty,
            step=1,
            key=f"quantity_{mode}"
        )
    
    with col2:
        st.caption("Suggested based on risk")
        st.write(f"Suggested: {suggested_qty}")
    
    # Order summary
    st.markdown("---")
    st.markdown("**Order Summary**")
    
    if entry_price > 0 and quantity > 0:
        position_value = entry_price * quantity
        risk = abs(entry_price - stop_loss) * quantity if stop_loss > 0 else 0
        reward = abs(target - entry_price) * quantity if target > 0 else 0
        rr_ratio = reward / risk if risk > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Position Value", f"Rs.{position_value:,.2f}")
        
        with col2:
            st.metric("Max Risk", f"Rs.{risk:,.2f}")
        
        with col3:
            st.metric("R:R Ratio", f"{rr_ratio:.2f}")
        
        # Risk warning
        capital_pct = (position_value / config.capital) * 100
        if capital_pct > 20:
            st.warning(f"Position is {capital_pct:.1f}% of capital (max recommended: 20%)")
    
    st.markdown("---")
    
    # Execute button
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button(
            f"Place {side} Order",
            use_container_width=True,
            type="primary",
            key=f"execute_{mode}"
        ):
            execute_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                entry_price=entry_price if order_type == "LIMIT" else 0,
                stop_loss=stop_loss,
                target=target,
                mode=mode
            )
    
    with col2:
        if st.button("Clear", use_container_width=True, key=f"clear_{mode}"):
            clear_order_form()


def execute_order(
    symbol: str,
    side: str,
    quantity: int,
    order_type: str,
    entry_price: float,
    stop_loss: float,
    target: float,
    mode: str
):
    """Execute the order."""
    config = get_config()
    
    # Validation
    if quantity <= 0:
        st.error("Quantity must be greater than 0")
        return
    
    if stop_loss <= 0:
        st.error("Stop loss is required")
        return
    
    if order_type == "LIMIT" and entry_price <= 0:
        st.error("Entry price required for limit orders")
        return
    
    # Risk check
    if mode == "intraday":
        from risk.risk_guard import get_risk_guard
        from core.models import BreakoutSignal, SignalType, SRLevel
        
        guard = get_risk_guard()
        
        signal = BreakoutSignal(
            symbol=symbol,
            signal_type=SignalType.BREAKOUT_LONG if side == "BUY" else SignalType.BREAKOUT_SHORT,
            entry_price=entry_price or 1000,  # Placeholder for market orders
            stop_loss=stop_loss,
            target=target or (entry_price * 1.04 if side == "BUY" else entry_price * 0.96),
            sr_level=SRLevel(price=entry_price or 1000, level_type="manual"),
            volume_ratio=1.0,
            timestamp=datetime.now(),
            confidence=0.8
        )
        
        check = guard.check_trade_allowed(signal)
        
        if not check.allowed:
            st.error(f"Risk check failed: {check.reason}")
            return
    else:
        from risk.swing_risk import get_swing_risk_guard
        from strategies.swing_breakout import SwingSignal
        from strategies.swing_levels import TrendAnalysis
        from core.models import SRLevel
        
        guard = get_swing_risk_guard()
        
        trend = TrendAnalysis(
            direction='sideways', strength=0.5,
            ema_short=0, ema_long=0,
            price_vs_ema='at',
            higher_highs=0, higher_lows=0,
            lower_highs=0, lower_lows=0,
            atr=20, atr_percent=2.0
        )
        
        signal = SwingSignal(
            symbol=symbol,
            signal_type='BREAKOUT_LONG' if side == 'BUY' else 'BREAKOUT_SHORT',
            entry_price=entry_price or 1000,
            stop_loss=stop_loss,
            target_1=target or (entry_price * 1.06 if side == 'BUY' else entry_price * 0.94),
            target_2=target * 1.5 if target else 0,
            target_3=target * 2.5 if target else 0,
            sr_level=SRLevel(price=entry_price or 1000, level_type="manual"),
            trend=trend,
            volume_ratio=1.0,
            atr=20,
            consolidation_days=0,
            timestamp=datetime.now(),
            confidence=0.8,
            holding_days_estimate=7
        )
        
        check = guard.check_trade_allowed(signal)
        
        if not check.allowed:
            st.error(f"Risk check failed: {check.reason}")
            return
    
    # Execute order (paper mode for now)
    if config.mode == TradingMode.PAPER:
        if mode == "intraday":
            from core.position_tracker import get_order_manager, get_position_tracker
            from core.models import OrderType as OT
            
            order_manager = get_order_manager()
            position_tracker = get_position_tracker()
            
            order_id = order_manager.place_entry_order(signal, quantity, OT.MARKET)
            
            if order_id:
                position_tracker.open_position(
                    signal=signal,
                    quantity=quantity,
                    entry_order_id=order_id,
                    entry_price=entry_price or signal.entry_price
                )
        else:
            from core.swing_tracker import get_swing_order_manager, get_swing_position_tracker
            
            order_manager = get_swing_order_manager()
            position_tracker = get_swing_position_tracker()
            
            order_id = order_manager.place_entry_order(signal, quantity)
            
            if order_id:
                position_tracker.open_position(
                    signal=signal,
                    quantity=quantity,
                    entry_order_id=order_id,
                    entry_price=entry_price or signal.entry_price
                )
        
        st.success(f"Order placed: {side} {quantity} {symbol}")
        clear_order_form()
        st.rerun()
    else:
        st.warning("Live trading requires Kite Connect authentication")


def render_modify_sl_form(modify_sl: dict, mode: str):
    """Render form to modify stop loss."""
    symbol = modify_sl['symbol']
    current_sl = modify_sl['current_sl']
    
    st.subheader(f"Modify SL for {symbol}")
    
    new_sl = st.number_input(
        "New Stop Loss",
        min_value=0.0,
        value=float(current_sl),
        step=0.05,
        key=f"new_sl_{mode}"
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("Update SL", use_container_width=True, type="primary"):
            # Update SL
            if mode == "intraday":
                from core.position_tracker import get_position_tracker
                tracker = get_position_tracker()
                tracker.update_stop_loss(symbol, new_sl)
            else:
                from core.swing_tracker import get_swing_position_tracker
                tracker = get_swing_position_tracker()
                tracker.update_stop_loss(symbol, new_sl)
            
            st.success(f"Stop loss updated to {new_sl}")
            del st.session_state['modify_sl']
            st.rerun()
    
    with col2:
        if st.button("Cancel", use_container_width=True):
            del st.session_state['modify_sl']
            st.rerun()


def clear_order_form():
    """Clear the order form."""
    keys_to_clear = ['pending_order', 'order_side', 'modify_sl', 'partial_close']
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]


def render_order_history(mode: str = "intraday", limit: int = 10):
    """Render recent order history."""
    import pandas as pd
    import numpy as np
    
    # Sample history
    history = []
    for i in range(limit):
        status = np.random.choice(['COMPLETE', 'CANCELLED', 'REJECTED'])
        history.append({
            'Time': datetime.now(),
            'Symbol': np.random.choice(['RELIANCE', 'TCS', 'INFY', 'HDFCBANK']),
            'Side': np.random.choice(['BUY', 'SELL']),
            'Qty': np.random.randint(1, 50),
            'Price': np.random.uniform(1000, 3000),
            'Status': status
        })
    
    df = pd.DataFrame(history)
    
    def color_status(val):
        if val == 'COMPLETE':
            return 'color: green'
        elif val == 'REJECTED':
            return 'color: red'
        return 'color: orange'
    
    st.dataframe(
        df.style.applymap(color_status, subset=['Status']),
        use_container_width=True,
        hide_index=True
    )
