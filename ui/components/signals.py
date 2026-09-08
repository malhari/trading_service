"""Signals panel component for the trading dashboard."""

import streamlit as st
import pandas as pd
from datetime import datetime
from typing import List, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import get_config


def get_intraday_signals() -> List[dict]:
    """Get current intraday signals."""
    config = get_config()
    
    signals = []
    
    # Check if we have signals stored in session state
    if 'intraday_signals' in st.session_state:
        for symbol, signal in st.session_state['intraday_signals'].items():
            signals.append(signal)
    
    # Generate some sample signals for demo if none stored
    if not signals:
        import numpy as np
        sample_symbols = config.watchlist.symbols[:3]
        
        for symbol in sample_symbols:
            if np.random.random() > 0.5:  # 50% chance of signal
                signal_type = np.random.choice(['BREAKOUT_LONG', 'BREAKOUT_SHORT', 'ORB_LONG', 'ORB_SHORT'])
                entry = np.random.uniform(1000, 3000)
                risk = entry * np.random.uniform(0.01, 0.02)
                
                signals.append({
                    'symbol': symbol,
                    'type': signal_type,
                    'entry': entry,
                    'stop_loss': entry - risk if 'LONG' in signal_type else entry + risk,
                    'target': entry + (risk * 2) if 'LONG' in signal_type else entry - (risk * 2),
                    'rr_ratio': 2.0,
                    'confidence': np.random.uniform(0.6, 0.95),
                    'volume_ratio': np.random.uniform(1.2, 2.5),
                    'timestamp': datetime.now()
                })
    
    return signals


def get_swing_signals() -> List[dict]:
    """Get current swing signals."""
    config = get_config()
    
    signals = []
    
    # Check if we have signals stored in session state
    if 'swing_signals' in st.session_state:
        for symbol, signal in st.session_state['swing_signals'].items():
            signals.append(signal)
    
    # Generate sample signals for demo if none stored
    if not signals:
        import numpy as np
        
        swing_watchlist = config.swing_watchlist.symbols[:5]
        
        for symbol in swing_watchlist:
            if np.random.random() > 0.6:  # 40% chance of signal
                signal_type = np.random.choice([
                    'BREAKOUT_LONG', 'BREAKOUT_SHORT', 
                    'PULLBACK_BUY', 'PULLBACK_SELL',
                    'CONSOLIDATION_BREAKOUT'
                ])
                entry = np.random.uniform(500, 3000)
                atr = entry * np.random.uniform(0.02, 0.04)
                
                is_long = 'LONG' in signal_type or 'BUY' in signal_type
                
                signals.append({
                    'symbol': symbol,
                    'type': signal_type,
                    'entry': entry,
                    'stop_loss': entry - (atr * 2) if is_long else entry + (atr * 2),
                    'target_1': entry + (atr * 2) if is_long else entry - (atr * 2),
                    'target_2': entry + (atr * 3) if is_long else entry - (atr * 3),
                    'target_3': entry + (atr * 5) if is_long else entry - (atr * 5),
                    'rr_ratio': np.random.uniform(2.0, 4.0),
                    'confidence': np.random.uniform(0.55, 0.95),
                    'holding_days': np.random.randint(3, 12),
                    'trend': np.random.choice(['uptrend', 'downtrend']),
                    'timestamp': datetime.now()
                })
    
    return sorted(signals, key=lambda x: x['confidence'], reverse=True)


def render_signals(mode: str = "intraday"):
    """
    Render the signals panel.
    
    Args:
        mode: Trading mode (intraday/swing).
    """
    if mode == "intraday":
        signals = get_intraday_signals()
    else:
        signals = get_swing_signals()
    
    if not signals:
        st.info("No active signals")
        return
    
    st.markdown(f"**{len(signals)} Active Signals**")
    
    for signal in signals:
        render_signal_card(signal, mode)


def render_signal_card(signal: dict, mode: str):
    """Render a single signal card."""
    symbol = signal['symbol']
    signal_type = signal['type']
    entry = signal['entry']
    stop_loss = signal['stop_loss']
    confidence = signal['confidence']
    rr_ratio = signal['rr_ratio']
    
    # Determine if bullish or bearish
    is_bullish = 'LONG' in signal_type or 'BUY' in signal_type
    
    # Card styling
    card_class = "bullish" if is_bullish else "bearish"
    direction_icon = "LONG" if is_bullish else "SHORT"
    direction_color = "green" if is_bullish else "red"
    
    # Create card
    with st.container():
        # Header
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown(f"**{symbol}**")
            st.caption(signal_type.replace('_', ' '))
        
        with col2:
            st.markdown(f":{direction_color}[{direction_icon}]")
            st.caption(f"Conf: {confidence:.0%}")
        
        # Levels
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Entry", f"{entry:.2f}")
        
        with col2:
            st.metric("SL", f"{stop_loss:.2f}")
        
        with col3:
            if mode == "swing":
                st.metric("T1", f"{signal.get('target_1', signal.get('target', 0)):.2f}")
            else:
                target = signal.get('target', entry + (entry - stop_loss) * 2)
                st.metric("Target", f"{target:.2f}")
        
        # Additional info
        col1, col2 = st.columns(2)
        
        with col1:
            st.caption(f"R:R {rr_ratio:.2f}")
        
        with col2:
            if mode == "swing":
                st.caption(f"~{signal.get('holding_days', 5)} days")
            else:
                st.caption(f"Vol: {signal.get('volume_ratio', 1.0):.1f}x")
        
        # Action buttons
        btn_col1, btn_col2 = st.columns(2)
        
        with btn_col1:
            if st.button(
                "📋 Prepare",
                key=f"prepare_{symbol}_{signal_type}_{mode}",
                use_container_width=True
            ):
                take_trade(signal, mode)
        
        with btn_col2:
            if st.button(
                "⚡ Execute",
                key=f"execute_{symbol}_{signal_type}_{mode}",
                use_container_width=True,
                type="primary"
            ):
                # Show execution dialog
                st.session_state[f'show_exec_{symbol}'] = signal
                st.rerun()
        
        # Execution dialog
        if st.session_state.get(f'show_exec_{symbol}'):
            exec_signal = st.session_state[f'show_exec_{symbol}']
            with st.expander("⚡ Quick Execute", expanded=True):
                risk_amt = st.number_input(
                    "Risk Amount (Rs.)",
                    min_value=100,
                    max_value=10000,
                    value=1000,
                    step=100,
                    key=f"risk_{symbol}_{mode}"
                )
                
                # Calculate quantity preview
                risk_per_share = abs(exec_signal['entry'] - exec_signal['stop_loss'])
                est_qty = int(risk_amt / risk_per_share) if risk_per_share > 0 else 0
                st.caption(f"Est. Quantity: {est_qty} shares")
                
                from services.order_service import get_order_service
                order_service = get_order_service()
                mode_text = "PAPER" if not order_service.is_live else "🔴 LIVE"
                st.caption(f"Mode: {mode_text}")
                
                exec_col1, exec_col2 = st.columns(2)
                with exec_col1:
                    if st.button("✅ Confirm", key=f"confirm_{symbol}", type="primary"):
                        if execute_order_now(exec_signal, mode, quantity=0, risk_amount=risk_amt):
                            del st.session_state[f'show_exec_{symbol}']
                            st.rerun()
                
                with exec_col2:
                    if st.button("❌ Cancel", key=f"cancel_{symbol}"):
                        del st.session_state[f'show_exec_{symbol}']
                        st.rerun()
        
        st.markdown("---")


def take_trade(signal: dict, mode: str):
    """Execute a trade from a signal."""
    # Store signal for LLM analysis
    st.session_state['analyze_signal'] = signal
    
    st.session_state['pending_order'] = {
        'symbol': signal['symbol'],
        'side': 'BUY' if 'LONG' in signal['type'] or 'BUY' in signal['type'] else 'SELL',
        'entry': signal['entry'],
        'stop_loss': signal['stop_loss'],
        'target': signal.get('target_1', signal.get('target', 0)),
        'signal_type': signal['type'],
        'mode': mode
    }
    
    st.info(f"Order prepared for {signal['symbol']}. Go to Order Panel to execute.")
    st.rerun()


def execute_order_now(signal: dict, mode: str, quantity: int = 0, risk_amount: float = 1000):
    """
    Execute order immediately using the order service.
    
    Args:
        signal: Signal data with entry, sl, target
        mode: Trading mode (intraday/swing)
        quantity: Number of shares (0 = calculate from risk)
        risk_amount: Risk amount in Rs if quantity is 0
    """
    from services.order_service import get_order_service
    
    order_service = get_order_service()
    
    side = 'BUY' if 'LONG' in signal['type'] or 'BUY' in signal['type'] else 'SELL'
    product = "MIS" if mode == "intraday" else "CNC"
    target = signal.get('target_1', signal.get('target', 0))
    
    result = order_service.execute_signal(
        symbol=signal['symbol'],
        side=side,
        entry_price=signal['entry'],
        stop_loss=signal['stop_loss'],
        target=target,
        quantity=quantity,
        risk_amount=risk_amount,
        product=product
    )
    
    if result:
        st.success(f"✅ Order executed: {side} {result.quantity} {signal['symbol']} @ {signal['entry']:.2f}")
        st.info(f"SL: {signal['stop_loss']:.2f} | Target: {target:.2f}")
        return True
    else:
        st.error("❌ Order execution failed")
        return False


def render_signal_history(mode: str = "intraday", limit: int = 10):
    """Render recent signal history."""
    st.subheader("Signal History")
    
    # Sample history
    import numpy as np
    
    history = []
    for i in range(limit):
        outcome = np.random.choice(['target', 'stop_loss', 'active'])
        history.append({
            'Symbol': np.random.choice(['RELIANCE', 'TCS', 'INFY', 'HDFCBANK']),
            'Type': np.random.choice(['BREAKOUT_LONG', 'BREAKOUT_SHORT']),
            'Entry': np.random.uniform(1000, 3000),
            'Exit': np.random.uniform(1000, 3000),
            'P&L%': np.random.uniform(-2, 5),
            'Outcome': outcome,
            'Time': datetime.now()
        })
    
    df = pd.DataFrame(history)
    
    # Color P&L
    def color_pnl(val):
        color = 'green' if val > 0 else 'red'
        return f'color: {color}'
    
    st.dataframe(
        df.style.applymap(color_pnl, subset=['P&L%']),
        use_container_width=True,
        hide_index=True
    )


def get_signal_stats(mode: str = "intraday") -> dict:
    """Get signal statistics."""
    import numpy as np
    
    return {
        'total_signals': np.random.randint(10, 50),
        'signals_taken': np.random.randint(5, 30),
        'win_rate': np.random.uniform(0.45, 0.65),
        'avg_rr': np.random.uniform(1.5, 2.5),
        'best_signal': np.random.uniform(3, 8),
        'worst_signal': np.random.uniform(-3, -1)
    }
