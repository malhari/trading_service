"""LLM Analysis Panel component for the trading dashboard."""

import streamlit as st
from datetime import datetime
from typing import Dict, Optional, List
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import get_config


def get_llm_analysis(
    symbol: str,
    signal_type: str,
    entry: float,
    stop_loss: float,
    target: float,
    volume_ratio: float = 1.0
) -> Dict:
    """
    Get LLM analysis for a trade setup.
    
    Args:
        symbol: Trading symbol.
        signal_type: Type of signal.
        entry: Entry price.
        stop_loss: Stop loss price.
        target: Target price.
        volume_ratio: Volume relative to average.
    
    Returns:
        LLM analysis result.
    """
    from llm.llm_router import get_llm_router
    
    router = get_llm_router()
    
    result = router.validate_trade_setup(
        symbol=symbol,
        signal_type=signal_type,
        entry=entry,
        sl=stop_loss,
        target=target,
        volume_ratio=volume_ratio
    )
    
    return result


def get_market_sentiment(symbol: str) -> Dict:
    """Get market sentiment analysis for a symbol."""
    from llm.llm_router import get_llm_router
    
    router = get_llm_router()
    return router.analyze_market_sentiment(symbol)


def render_llm_analysis_panel(signal: Optional[Dict] = None):
    """
    Render the LLM analysis panel.
    
    Args:
        signal: Optional signal dict to analyze.
    """
    config = get_config()
    
    st.subheader("AI Analysis")
    
    # Check if LLM is enabled
    if not config.llm.enabled:
        st.warning("LLM analysis is disabled in config", icon="⚠️")
        st.caption(f"Provider: {config.llm.provider}")
        return
    
    # Show LLM status
    provider = config.llm.provider
    model = config.llm.model
    
    provider_icons = {
        "openai": "🤖",
        "ollama": "🦙",
        "llamacpp": "🦙",
        "lmstudio": "🖥️"
    }
    icon = provider_icons.get(provider.lower(), "🤖")
    
    st.caption(f"{icon} {provider.upper()} / {model}")
    
    # If we have a signal, analyze it
    if signal:
        render_signal_analysis(signal)
    else:
        # Manual analysis input
        render_manual_analysis()


def render_signal_analysis(signal: Dict):
    """Render analysis for a specific signal."""
    symbol = signal.get('symbol', '')
    signal_type = signal.get('type', '')
    entry = signal.get('entry', 0)
    stop_loss = signal.get('stop_loss', 0)
    target = signal.get('target', signal.get('target_1', 0))
    volume_ratio = signal.get('volume_ratio', 1.0)
    
    st.markdown(f"**Analyzing: {symbol}**")
    st.caption(signal_type)
    
    # Check session state for cached analysis
    cache_key = f"llm_analysis_{symbol}_{signal_type}"
    
    if cache_key not in st.session_state:
        with st.spinner("Getting AI analysis..."):
            try:
                analysis = get_llm_analysis(
                    symbol=symbol,
                    signal_type=signal_type,
                    entry=entry,
                    stop_loss=stop_loss,
                    target=target,
                    volume_ratio=volume_ratio
                )
                st.session_state[cache_key] = analysis
                st.session_state[f"{cache_key}_time"] = datetime.now()
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                return
    
    analysis = st.session_state[cache_key]
    analysis_time = st.session_state.get(f"{cache_key}_time", datetime.now())
    
    render_analysis_result(analysis, analysis_time)
    
    # Refresh button
    if st.button("Refresh Analysis", key=f"refresh_{cache_key}"):
        del st.session_state[cache_key]
        st.rerun()


def render_manual_analysis():
    """Render manual analysis input form."""
    st.markdown("**Analyze a Trade Setup**")
    
    config = get_config()
    watchlist = config.get_active_watchlist()
    
    col1, col2 = st.columns(2)
    
    with col1:
        symbol = st.selectbox(
            "Symbol",
            options=watchlist.symbols,
            key="llm_symbol"
        )
        
        entry = st.number_input(
            "Entry Price",
            min_value=0.0,
            value=1000.0,
            step=1.0,
            key="llm_entry"
        )
        
        signal_type = st.selectbox(
            "Signal Type",
            options=["BREAKOUT_LONG", "BREAKOUT_SHORT", "ORB_LONG", "ORB_SHORT", "PULLBACK_BUY"],
            key="llm_signal_type"
        )
    
    with col2:
        stop_loss = st.number_input(
            "Stop Loss",
            min_value=0.0,
            value=980.0,
            step=1.0,
            key="llm_sl"
        )
        
        target = st.number_input(
            "Target",
            min_value=0.0,
            value=1040.0,
            step=1.0,
            key="llm_target"
        )
        
        volume_ratio = st.number_input(
            "Volume Ratio",
            min_value=0.1,
            value=1.5,
            step=0.1,
            key="llm_volume"
        )
    
    if st.button("Analyze Trade", type="primary", use_container_width=True):
        with st.spinner("Getting AI analysis..."):
            try:
                analysis = get_llm_analysis(
                    symbol=symbol,
                    signal_type=signal_type,
                    entry=entry,
                    stop_loss=stop_loss,
                    target=target,
                    volume_ratio=volume_ratio
                )
                st.session_state['manual_analysis'] = analysis
                st.session_state['manual_analysis_time'] = datetime.now()
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                return
    
    if 'manual_analysis' in st.session_state:
        st.divider()
        render_analysis_result(
            st.session_state['manual_analysis'],
            st.session_state.get('manual_analysis_time', datetime.now())
        )


def render_analysis_result(analysis: Dict, analysis_time: datetime):
    """Render the LLM analysis result."""
    
    # Decision
    allow_trade = analysis.get('allow_trade', True)
    confidence = analysis.get('confidence', 0.5)
    reason = analysis.get('reason', 'No analysis available')
    suggestions = analysis.get('suggestions', [])
    
    # Decision badge
    if allow_trade:
        st.success("✅ TRADE APPROVED", icon="✅")
    else:
        st.error("❌ TRADE NOT RECOMMENDED", icon="❌")
    
    # Confidence meter
    st.markdown("**Confidence**")
    
    if confidence >= 0.8:
        conf_color = "green"
    elif confidence >= 0.6:
        conf_color = "orange"
    else:
        conf_color = "red"
    
    st.progress(confidence, text=f"{confidence:.0%}")
    
    # Reasoning
    st.markdown("**Analysis**")
    st.info(reason, icon="💡")
    
    # Suggestions
    if suggestions:
        st.markdown("**Suggestions**")
        for suggestion in suggestions:
            st.caption(f"• {suggestion}")
    
    # Timestamp
    st.caption(f"Analyzed at {analysis_time.strftime('%H:%M:%S')}")


def render_sentiment_panel(symbol: Optional[str] = None):
    """Render market sentiment analysis panel."""
    config = get_config()
    
    st.subheader("Market Sentiment")
    
    if not config.llm.enabled:
        st.warning("LLM disabled")
        return
    
    if not symbol:
        watchlist = config.get_active_watchlist()
        symbol = st.selectbox(
            "Select Symbol",
            options=watchlist.symbols,
            key="sentiment_symbol"
        )
    
    cache_key = f"sentiment_{symbol}"
    
    if st.button("Analyze Sentiment", key=f"btn_{cache_key}"):
        with st.spinner(f"Analyzing {symbol} sentiment..."):
            try:
                sentiment = get_market_sentiment(symbol)
                st.session_state[cache_key] = sentiment
            except Exception as e:
                st.error(f"Failed: {e}")
                return
    
    if cache_key in st.session_state:
        sentiment = st.session_state[cache_key]
        
        sentiment_val = sentiment.get('sentiment', 'neutral')
        confidence = sentiment.get('confidence', 0.5)
        factors = sentiment.get('factors', [])
        recommendation = sentiment.get('recommendation', 'no_preference')
        
        # Sentiment badge
        sentiment_colors = {
            'bullish': 'green',
            'bearish': 'red',
            'neutral': 'orange'
        }
        color = sentiment_colors.get(sentiment_val, 'gray')
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"**Sentiment:** :{color}[{sentiment_val.upper()}]")
            st.progress(confidence, text=f"Confidence: {confidence:.0%}")
        
        with col2:
            rec_text = recommendation.replace('_', ' ').title()
            st.markdown(f"**Recommendation:** {rec_text}")
        
        if factors:
            st.markdown("**Factors:**")
            for factor in factors:
                st.caption(f"• {factor}")


def render_llm_history():
    """Render LLM analysis history."""
    st.subheader("Analysis History")
    
    # Get all cached analyses from session state
    analyses = []
    for key, value in st.session_state.items():
        if key.startswith('llm_analysis_') and not key.endswith('_time'):
            time_key = f"{key}_time"
            analyses.append({
                'key': key,
                'symbol': key.replace('llm_analysis_', '').split('_')[0],
                'analysis': value,
                'time': st.session_state.get(time_key, datetime.now())
            })
    
    if not analyses:
        st.info("No analyses yet. Analyze a trade to see history.")
        return
    
    # Sort by time
    analyses.sort(key=lambda x: x['time'], reverse=True)
    
    for item in analyses[:5]:  # Show last 5
        with st.expander(f"{item['symbol']} - {item['time'].strftime('%H:%M')}"):
            analysis = item['analysis']
            allow = "✅ Approved" if analysis.get('allow_trade') else "❌ Not Recommended"
            st.write(f"**Decision:** {allow}")
            st.write(f"**Confidence:** {analysis.get('confidence', 0):.0%}")
            st.write(f"**Reason:** {analysis.get('reason', 'N/A')}")
