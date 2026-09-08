"""
Settings Page - Configure connections, alerts, and trading parameters.
"""

import streamlit as st
import sys
import os
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime

# Page config
st.set_page_config(
    page_title="Settings",
    page_icon="⚙️",
    layout="wide"
)

st.title("⚙️ Settings")

# Import services
from core.config import get_config
from services.live_data_service import get_live_data_service
from services.alert_service import get_alert_service
from services.order_service import get_order_service, ExecutionMode
from services.scanner_service import get_scanner_service

config = get_config()
live_data = get_live_data_service()
alerts = get_alert_service()
orders = get_order_service()
scanner = get_scanner_service()

# ==================== Zerodha Connection ====================
st.header("🔗 Zerodha Connection")

col1, col2 = st.columns([2, 1])

with col1:
    # Connection status
    if live_data.is_ready:
        st.success("✅ Connected to Zerodha", icon="✅")
        
        # Show account info
        try:
            from data.kite_client import get_kite_client
            kite = get_kite_client()
            if kite.kite:
                profile = kite.get_profile()
                if profile:
                    st.write(f"**User:** {profile.get('user_name', 'N/A')}")
                    st.write(f"**User ID:** {profile.get('user_id', 'N/A')}")
                
                margins = kite.get_margins()
                if margins:
                    equity = margins.get("equity", {})
                    available = equity.get("available", {}).get("cash", 0)
                    st.metric("Available Margin", f"Rs.{available:,.2f}")
        except Exception as e:
            st.warning(f"Could not fetch account details: {e}")
    else:
        st.warning("⚠️ Not connected to Zerodha")
        
        # Check if API key is configured
        api_key = os.getenv("KITE_API_KEY", "")
        
        if not api_key:
            st.error("KITE_API_KEY not found in .env file")
            st.code("""
# Add to your .env file:
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret
            """)
        else:
            st.info("Click 'Connect' to login to Zerodha")

with col2:
    if not live_data.is_ready:
        if st.button("🔌 Connect to Zerodha", type="primary", use_container_width=True):
            # Try to initialize with saved token
            if live_data.initialize():
                st.success("Connected!")
                st.rerun()
            else:
                # Need manual login
                login_url = live_data.get_login_url()
                if login_url.startswith("ERROR"):
                    st.error(login_url)
                else:
                    st.session_state.kite_login_url = login_url
                    st.info("Login URL generated. Click 'Open Login' below.")
        
        # Show login URL if available
        if "kite_login_url" in st.session_state:
            st.markdown(f"[🔗 Open Zerodha Login]({st.session_state.kite_login_url})")
            
            st.divider()
            st.write("After login, paste the request_token from the redirect URL:")
            
            request_token = st.text_input("Request Token", key="request_token")
            
            if st.button("Complete Login"):
                if request_token:
                    if live_data.complete_login(request_token):
                        st.success("Login successful!")
                        del st.session_state.kite_login_url
                        st.rerun()
                    else:
                        st.error("Login failed. Check the request token.")
                else:
                    st.warning("Enter the request token")
    else:
        if st.button("🔄 Refresh Connection", use_container_width=True):
            live_data.initialize()
            st.rerun()

st.divider()

# ==================== Trading Mode ====================
st.header("📊 Trading Mode")

col1, col2 = st.columns(2)

with col1:
    current_mode = "🟢 LIVE" if orders.is_live else "📝 PAPER"
    st.info(f"Current Mode: **{current_mode}**")
    
    mode_option = st.radio(
        "Select Mode",
        options=["Paper Trading", "Live Trading"],
        index=0 if not orders.is_live else 1,
        key="trading_mode_radio"
    )
    
    if st.button("Apply Mode", key="apply_mode"):
        if mode_option == "Live Trading":
            orders.set_mode(ExecutionMode.LIVE)
            st.warning("⚠️ Live trading enabled - real orders will be placed!")
        else:
            orders.set_mode(ExecutionMode.PAPER)
            st.success("Paper trading mode enabled")
        st.rerun()

with col2:
    st.markdown("""
    **Paper Trading:**
    - Simulated orders (no real money)
    - Good for testing strategies
    - Tracks P&L without risk
    
    **Live Trading:**
    - Real orders on Zerodha
    - Uses your actual capital
    - ⚠️ Risk of real losses
    """)

st.divider()

# ==================== Telegram Alerts ====================
st.header("📱 Telegram Alerts")

col1, col2 = st.columns(2)

with col1:
    telegram_enabled = st.checkbox(
        "Enable Telegram Alerts",
        value=alerts.telegram_enabled,
        key="telegram_enabled"
    )
    alerts.telegram_enabled = telegram_enabled
    
    bot_token = st.text_input(
        "Bot Token",
        value=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        type="password",
        help="Get from @BotFather on Telegram"
    )
    
    chat_id = st.text_input(
        "Chat ID",
        value=os.getenv("TELEGRAM_CHAT_ID", ""),
        help="Your Telegram chat ID or group ID"
    )
    
    if st.button("Save & Test Telegram"):
        if bot_token and chat_id:
            alerts.configure_telegram(bot_token, chat_id)
            
            # Send test message
            from services.alert_service import Alert, AlertType, AlertPriority
            test_alert = Alert(
                alert_type=AlertType.SYSTEM,
                title="Test Alert",
                message="Telegram alerts configured successfully! 🎉",
                priority=AlertPriority.LOW
            )
            
            if alerts.telegram.send_alert(test_alert):
                st.success("Test message sent! Check your Telegram.")
            else:
                st.error("Failed to send test message. Check your credentials.")
        else:
            st.warning("Enter both Bot Token and Chat ID")

with col2:
    st.markdown("""
    **How to set up Telegram:**
    
    1. Open Telegram and search for **@BotFather**
    2. Send `/newbot` and follow prompts
    3. Copy the **Bot Token**
    4. Start a chat with your bot
    5. Get your **Chat ID** from @userinfobot
    
    **Or add to .env:**
    ```
    TELEGRAM_BOT_TOKEN=your_token
    TELEGRAM_CHAT_ID=your_chat_id
    ```
    """)

st.divider()

# ==================== Scanner Settings ====================
st.header("🔍 Scanner Settings")

col1, col2 = st.columns(2)

with col1:
    scan_interval = st.number_input(
        "Scan Interval (seconds)",
        min_value=30,
        max_value=300,
        value=scanner.scan_interval_seconds,
        step=30,
        key="scan_interval"
    )
    scanner.scan_interval_seconds = scan_interval
    
    min_score = st.slider(
        "Minimum Alert Score",
        min_value=50,
        max_value=90,
        value=scanner.min_score_for_alert,
        step=5,
        key="min_alert_score"
    )
    scanner.min_score_for_alert = min_score

with col2:
    # Scanner status
    if scanner._running:
        st.success("Scanner is running", icon="🔄")
        if st.button("Stop Scanner", key="stop_scanner"):
            scanner.stop()
            st.rerun()
    else:
        st.info("Scanner is stopped")
        if st.button("Start Scanner", type="primary", key="start_scanner"):
            scanner.start()
            st.success("Scanner started!")
            st.rerun()
    
    # Last scan info
    if scanner.last_scan_time:
        st.write(f"Last scan: {scanner.last_scan_time.strftime('%H:%M:%S')}")
        st.write(f"Signals found: {len(scanner.last_scan_results)}")

st.divider()

# ==================== Watchlist ====================
st.header("📋 Watchlist")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Intraday Watchlist")
    
    intraday_symbols = st.text_area(
        "Symbols (one per line)",
        value="\n".join(config.watchlist.symbols) if config.watchlist.symbols else "RELIANCE\nTCS\nINFY\nHDFCBANK",
        height=150,
        key="intraday_watchlist"
    )

with col2:
    st.subheader("Swing Watchlist")
    
    swing_symbols = st.text_area(
        "Symbols (one per line)",
        value="\n".join(config.swing_watchlist.symbols) if config.swing_watchlist.symbols else "RELIANCE\nTCS\nINFY\nHDFCBANK\nICICIBANK",
        height=150,
        key="swing_watchlist"
    )

if st.button("Update Watchlists", key="update_watchlist"):
    # Parse and update
    intraday_list = [s.strip().upper() for s in intraday_symbols.split("\n") if s.strip()]
    swing_list = [s.strip().upper() for s in swing_symbols.split("\n") if s.strip()]
    
    # Update scanner watchlist
    scanner.set_watchlist(swing_list)
    
    st.success(f"Updated: {len(intraday_list)} intraday, {len(swing_list)} swing symbols")

st.divider()

# ==================== Recent Alerts ====================
st.header("🔔 Recent Alerts")

recent = alerts.get_recent_alerts(10)

if recent:
    for alert in reversed(recent):
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.markdown(f"**{alert.title}**")
                st.write(alert.message[:100] + "..." if len(alert.message) > 100 else alert.message)
            
            with col2:
                st.caption(alert.timestamp.strftime("%H:%M:%S"))
                st.caption(alert.alert_type.value)
else:
    st.info("No recent alerts")

st.divider()

# ==================== System Status ====================
st.header("📈 System Status")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "Zerodha",
        "Connected" if live_data.is_ready else "Disconnected",
        delta="OK" if live_data.is_ready else "!"
    )

with col2:
    st.metric(
        "Trading Mode",
        "LIVE" if orders.is_live else "PAPER"
    )

with col3:
    st.metric(
        "Scanner",
        "Running" if scanner._running else "Stopped"
    )

with col4:
    st.metric(
        "Telegram",
        "Enabled" if alerts.telegram_enabled and alerts.telegram.is_configured else "Disabled"
    )
