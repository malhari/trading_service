"""
Streak-style Backtesting UI Component.

Provides interface for:
- Selecting/creating trading rules
- Running backtests
- Viewing performance metrics
- Analyzing trade history
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, timedelta
from typing import Optional

from backtesting.backtest_engine import BacktestEngine, BacktestConfig, BacktestResult, TradeStatus
from backtesting.streak_rules import (
    StreakRule, StreakCondition, IndicatorType, Comparator,
    get_all_preset_rules
)


def render_backtest_panel():
    """Render the main backtesting panel."""
    st.subheader("Strategy Backtester")
    
    # Rule selection
    tab1, tab2 = st.tabs(["Preset Rules", "Custom Rule"])
    
    with tab1:
        selected_rule = render_preset_rules()
    
    with tab2:
        custom_rule = render_custom_rule_builder()
        if custom_rule:
            selected_rule = custom_rule
    
    st.divider()
    
    # Symbol and date selection
    col1, col2, col3 = st.columns(3)
    
    with col1:
        symbol = st.text_input("Symbol", value="RELIANCE", key="bt_symbol")
    
    with col2:
        lookback = st.selectbox(
            "Lookback Period",
            options=[180, 365, 730, 1095],
            format_func=lambda x: f"{x} days ({x//365}y {(x%365)//30}m)" if x >= 365 else f"{x} days ({x//30}m)",
            index=1,
            key="bt_lookback"
        )
    
    with col3:
        capital = st.number_input(
            "Initial Capital (Rs.)",
            min_value=10000,
            max_value=10000000,
            value=100000,
            step=10000,
            key="bt_capital"
        )
    
    # Advanced settings
    with st.expander("Advanced Settings"):
        adv_col1, adv_col2, adv_col3 = st.columns(3)
        
        with adv_col1:
            position_size = st.slider("Position Size %", 5, 50, 10, key="bt_pos_size")
        
        with adv_col2:
            commission = st.slider("Commission %", 0.0, 1.0, 0.1, 0.05, key="bt_commission")
        
        with adv_col3:
            slippage = st.slider("Slippage %", 0.0, 0.5, 0.05, 0.01, key="bt_slippage")
    
    # Run backtest button
    if st.button("Run Backtest", type="primary", use_container_width=True, key="run_bt"):
        if selected_rule:
            with st.spinner("Running backtest..."):
                result = run_backtest(
                    rule=selected_rule,
                    symbol=symbol,
                    lookback_days=lookback,
                    initial_capital=capital,
                    position_size_pct=position_size,
                    commission_pct=commission,
                    slippage_pct=slippage
                )
                
                if result:
                    st.session_state.backtest_result = result
        else:
            st.warning("Please select or create a rule first")
    
    # Display results
    if "backtest_result" in st.session_state and st.session_state.backtest_result:
        render_backtest_results(st.session_state.backtest_result)


def render_preset_rules() -> Optional[StreakRule]:
    """Render preset rule selection."""
    rules = get_all_preset_rules()
    
    rule_names = [r.name for r in rules]
    selected_idx = st.selectbox(
        "Select Strategy",
        options=range(len(rules)),
        format_func=lambda i: rule_names[i],
        key="preset_rule_idx"
    )
    
    if selected_idx is not None:
        rule = rules[selected_idx]
        
        # Show rule details
        st.markdown(f"**Description:** {rule.description}")
        
        with st.expander("Rule Details", expanded=False):
            st.markdown("**Entry Conditions (ALL must be true):**")
            for i, cond in enumerate(rule.entry_conditions, 1):
                st.markdown(f"  {i}. {cond}")
            
            st.markdown("**Exit Conditions (ANY triggers exit):**")
            for i, cond in enumerate(rule.exit_conditions, 1):
                st.markdown(f"  {i}. {cond}")
            
            st.markdown(f"""
            **Risk Management:**
            - Stop Loss: {rule.stop_loss_percent}%
            - Target: {rule.target_percent}%
            - Trailing SL: {rule.trailing_sl_percent}% (if enabled)
            - Max Holding: {rule.max_holding_days} days
            """)
        
        # Allow editing risk parameters
        st.markdown("**Adjust Parameters:**")
        param_col1, param_col2, param_col3 = st.columns(3)
        
        with param_col1:
            rule.stop_loss_percent = st.number_input(
                "Stop Loss %", 0.5, 10.0, rule.stop_loss_percent, 0.5,
                key=f"sl_{selected_idx}"
            )
        
        with param_col2:
            rule.target_percent = st.number_input(
                "Target %", 1.0, 20.0, rule.target_percent, 0.5,
                key=f"tgt_{selected_idx}"
            )
        
        with param_col3:
            rule.max_holding_days = st.number_input(
                "Max Days", 5, 60, rule.max_holding_days, 5,
                key=f"days_{selected_idx}"
            )
        
        return rule
    
    return None


def render_custom_rule_builder() -> Optional[StreakRule]:
    """Render custom rule builder interface."""
    st.markdown("### Build Custom Rule")
    
    rule_name = st.text_input("Rule Name", value="My Custom Rule", key="custom_rule_name")
    rule_desc = st.text_input("Description", value="", key="custom_rule_desc")
    
    # Entry conditions
    st.markdown("**Entry Conditions**")
    entry_conditions = []
    
    num_entry = st.number_input("Number of entry conditions", 1, 5, 2, key="num_entry")
    
    for i in range(int(num_entry)):
        with st.container(border=True):
            st.markdown(f"**Condition {i+1}**")
            cols = st.columns([2, 1, 1, 2, 1])
            
            with cols[0]:
                left_ind = st.selectbox(
                    "Left",
                    options=[ind.value for ind in IndicatorType if ind != IndicatorType.NUMBER],
                    key=f"entry_left_{i}"
                )
            
            with cols[1]:
                left_period = st.number_input("Period", 0, 200, 14, key=f"entry_left_period_{i}")
            
            with cols[2]:
                comparator = st.selectbox(
                    "Compare",
                    options=[c.value for c in Comparator],
                    key=f"entry_comp_{i}"
                )
            
            with cols[3]:
                right_ind = st.selectbox(
                    "Right",
                    options=[ind.value for ind in IndicatorType],
                    key=f"entry_right_{i}"
                )
            
            with cols[4]:
                if right_ind == "number":
                    right_val = st.number_input("Value", 0.0, 10000.0, 30.0, key=f"entry_right_val_{i}")
                    right_period = 0
                else:
                    right_val = 0.0
                    right_period = st.number_input("Period", 0, 200, 21, key=f"entry_right_period_{i}")
            
            entry_conditions.append(StreakCondition(
                left_indicator=IndicatorType(left_ind),
                left_period=int(left_period),
                comparator=Comparator(comparator),
                right_indicator=IndicatorType(right_ind),
                right_period=int(right_period),
                right_value=float(right_val)
            ))
    
    # Exit conditions
    st.markdown("**Exit Conditions**")
    exit_conditions = []
    
    num_exit = st.number_input("Number of exit conditions", 0, 3, 1, key="num_exit")
    
    for i in range(int(num_exit)):
        with st.container(border=True):
            st.markdown(f"**Exit Condition {i+1}**")
            cols = st.columns([2, 1, 1, 2, 1])
            
            with cols[0]:
                left_ind = st.selectbox(
                    "Left",
                    options=[ind.value for ind in IndicatorType if ind != IndicatorType.NUMBER],
                    key=f"exit_left_{i}"
                )
            
            with cols[1]:
                left_period = st.number_input("Period", 0, 200, 14, key=f"exit_left_period_{i}")
            
            with cols[2]:
                comparator = st.selectbox(
                    "Compare",
                    options=[c.value for c in Comparator],
                    key=f"exit_comp_{i}"
                )
            
            with cols[3]:
                right_ind = st.selectbox(
                    "Right",
                    options=[ind.value for ind in IndicatorType],
                    key=f"exit_right_{i}"
                )
            
            with cols[4]:
                if right_ind == "number":
                    right_val = st.number_input("Value", 0.0, 10000.0, 70.0, key=f"exit_right_val_{i}")
                    right_period = 0
                else:
                    right_val = 0.0
                    right_period = st.number_input("Period", 0, 200, 21, key=f"exit_right_period_{i}")
            
            exit_conditions.append(StreakCondition(
                left_indicator=IndicatorType(left_ind),
                left_period=int(left_period),
                comparator=Comparator(comparator),
                right_indicator=IndicatorType(right_ind),
                right_period=int(right_period),
                right_value=float(right_val)
            ))
    
    # Risk management
    st.markdown("**Risk Management**")
    risk_col1, risk_col2, risk_col3, risk_col4 = st.columns(4)
    
    with risk_col1:
        sl_pct = st.number_input("Stop Loss %", 0.5, 10.0, 2.0, 0.5, key="custom_sl")
    
    with risk_col2:
        target_pct = st.number_input("Target %", 1.0, 20.0, 4.0, 0.5, key="custom_tgt")
    
    with risk_col3:
        trailing_sl = st.number_input("Trailing SL % (0=off)", 0.0, 5.0, 0.0, 0.5, key="custom_tsl")
    
    with risk_col4:
        max_days = st.number_input("Max Days", 5, 60, 20, 5, key="custom_max_days")
    
    if entry_conditions:
        return StreakRule(
            name=rule_name,
            description=rule_desc,
            entry_conditions=entry_conditions,
            exit_conditions=exit_conditions,
            stop_loss_percent=sl_pct,
            target_percent=target_pct,
            trailing_sl_percent=trailing_sl if trailing_sl > 0 else None,
            max_holding_days=int(max_days)
        )
    
    return None


def run_backtest(
    rule: StreakRule,
    symbol: str,
    lookback_days: int,
    initial_capital: float,
    position_size_pct: float,
    commission_pct: float,
    slippage_pct: float
) -> Optional[BacktestResult]:
    """Run backtest with given parameters."""
    try:
        # Get historical data
        from scanner.equity_scanner import get_scanner
        
        scanner = get_scanner()
        df = scanner.get_historical_data(symbol, days=lookback_days)
        
        if df.empty or len(df) < 60:
            st.error(f"Insufficient data for {symbol}. Need at least 60 days.")
            return None
        
        # Ensure date column exists
        if 'date' not in df.columns:
            df['date'] = df.index
        
        # Configure and run backtest
        config = BacktestConfig(
            initial_capital=initial_capital,
            position_size_percent=position_size_pct,
            commission_percent=commission_pct,
            slippage_percent=slippage_pct,
            lookback_days=lookback_days
        )
        
        engine = BacktestEngine(config)
        result = engine.run_backtest(rule, df, symbol)
        
        return result
        
    except Exception as e:
        st.error(f"Backtest error: {e}")
        return None


def render_backtest_results(result: BacktestResult):
    """Render backtest results with metrics and charts."""
    st.divider()
    st.subheader(f"Results: {result.rule_name} on {result.symbol}")
    
    # Key metrics row
    metric_cols = st.columns(6)
    
    with metric_cols[0]:
        color = "normal" if result.total_pnl >= 0 else "inverse"
        st.metric("Total P&L", f"Rs.{result.total_pnl:,.0f}", f"{result.total_pnl_percent:+.1f}%", delta_color=color)
    
    with metric_cols[1]:
        st.metric("Win Rate", f"{result.win_rate:.1f}%", f"{result.winning_trades}W / {result.losing_trades}L")
    
    with metric_cols[2]:
        st.metric("Profit Factor", f"{result.profit_factor:.2f}")
    
    with metric_cols[3]:
        st.metric("Max Drawdown", f"{result.max_drawdown_percent:.1f}%")
    
    with metric_cols[4]:
        st.metric("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
    
    with metric_cols[5]:
        st.metric("Avg Holding", f"{result.avg_holding_days:.1f} days")
    
    # Tabs for detailed analysis
    tab1, tab2, tab3, tab4 = st.tabs(["Equity Curve", "Trade Analysis", "Exit Analysis", "Trade List"])
    
    with tab1:
        render_equity_curve(result)
    
    with tab2:
        render_trade_analysis(result)
    
    with tab3:
        render_exit_analysis(result)
    
    with tab4:
        render_trade_list(result)


def render_equity_curve(result: BacktestResult):
    """Render equity curve chart."""
    if not result.equity_curve:
        st.info("No equity data available")
        return
    
    # Convert to DataFrame
    equity_df = pd.DataFrame(result.equity_curve, columns=['Date', 'Equity'])
    equity_df['Date'] = pd.to_datetime(equity_df['Date'])
    
    # Calculate drawdown
    equity_df['Peak'] = equity_df['Equity'].cummax()
    equity_df['Drawdown'] = (equity_df['Peak'] - equity_df['Equity']) / equity_df['Peak'] * 100
    
    # Plot equity curve
    st.line_chart(equity_df.set_index('Date')['Equity'], use_container_width=True)
    
    # Plot drawdown
    st.markdown("**Drawdown %**")
    st.area_chart(equity_df.set_index('Date')['Drawdown'], use_container_width=True, color="#ff6b6b")
    
    # Stats
    col1, col2, col3 = st.columns(3)
    
    with col1:
        initial = equity_df['Equity'].iloc[0]
        final = equity_df['Equity'].iloc[-1]
        st.metric("Starting Capital", f"Rs.{initial:,.0f}")
    
    with col2:
        st.metric("Final Capital", f"Rs.{final:,.0f}")
    
    with col3:
        peak = equity_df['Equity'].max()
        st.metric("Peak Capital", f"Rs.{peak:,.0f}")


def render_trade_analysis(result: BacktestResult):
    """Render trade analysis metrics."""
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Winning Trades")
        st.metric("Count", result.winning_trades)
        st.metric("Avg Profit", f"Rs.{result.avg_profit:,.0f}")
        st.metric("Avg Profit %", f"{result.avg_profit_percent:.2f}%")
        st.metric("Largest Win", f"Rs.{result.largest_profit:,.0f}")
        st.metric("Avg Holding Days", f"{result.avg_winning_days:.1f}")
    
    with col2:
        st.markdown("### Losing Trades")
        st.metric("Count", result.losing_trades)
        st.metric("Avg Loss", f"Rs.{result.avg_loss:,.0f}")
        st.metric("Avg Loss %", f"{result.avg_loss_percent:.2f}%")
        st.metric("Largest Loss", f"Rs.{result.largest_loss:,.0f}")
        st.metric("Avg Holding Days", f"{result.avg_losing_days:.1f}")
    
    # Risk/Reward visualization
    st.divider()
    st.markdown("### Risk/Reward Analysis")
    
    rr_col1, rr_col2, rr_col3 = st.columns(3)
    
    with rr_col1:
        st.metric("Risk:Reward Ratio", f"1:{result.risk_reward_ratio:.2f}")
    
    with rr_col2:
        expectancy = (result.win_rate/100 * result.avg_profit_percent) + ((1-result.win_rate/100) * result.avg_loss_percent)
        st.metric("Expectancy per Trade", f"{expectancy:.2f}%")
    
    with rr_col3:
        st.metric("Total Trades", result.total_trades)


def render_exit_analysis(result: BacktestResult):
    """Render exit type analysis."""
    st.markdown("### How Trades Exited")
    
    # Exit type distribution
    exit_data = {
        'Exit Type': ['Target Hit', 'Stop Loss', 'Trailing SL', 'Exit Signal', 'Max Days'],
        'Count': [
            result.target_hits,
            result.stop_loss_hits,
            result.trailing_sl_hits,
            result.exit_condition_hits,
            result.max_days_exits
        ]
    }
    
    exit_df = pd.DataFrame(exit_data)
    exit_df = exit_df[exit_df['Count'] > 0]  # Only show non-zero
    
    if not exit_df.empty:
        st.bar_chart(exit_df.set_index('Exit Type')['Count'], use_container_width=True)
    
    # Exit analysis insights
    st.markdown("### Insights")
    
    if result.total_trades > 0:
        target_pct = (result.target_hits / result.total_trades) * 100
        sl_pct = (result.stop_loss_hits / result.total_trades) * 100
        trailing_pct = (result.trailing_sl_hits / result.total_trades) * 100
        
        insights = []
        
        if target_pct > 40:
            insights.append(f"Strong target hit rate ({target_pct:.0f}%) - strategy captures profits well")
        elif target_pct < 20:
            insights.append(f"Low target hit rate ({target_pct:.0f}%) - consider adjusting target or entry timing")
        
        if sl_pct > 40:
            insights.append(f"High stop loss rate ({sl_pct:.0f}%) - entry timing or SL placement may need review")
        
        if trailing_pct > 20:
            insights.append(f"Good trailing SL usage ({trailing_pct:.0f}%) - letting winners run")
        
        if result.max_days_exits > result.total_trades * 0.3:
            insights.append("Many trades hitting max days - consider shorter holding period or different exit signals")
        
        for insight in insights:
            st.info(insight, icon="💡")


def render_trade_list(result: BacktestResult):
    """Render detailed trade list."""
    if not result.trades:
        st.info("No trades to display")
        return
    
    trades_data = []
    for t in result.trades:
        trades_data.append({
            'Entry Date': t.entry_date,
            'Exit Date': t.exit_date,
            'Entry Price': f"Rs.{t.entry_price:.2f}",
            'Exit Price': f"Rs.{t.exit_price:.2f}" if t.exit_price else "-",
            'P&L': f"Rs.{t.pnl:,.0f}",
            'P&L %': f"{t.pnl_percent:+.2f}%",
            'Days': t.holding_days,
            'Exit Type': t.status.value.replace('_', ' ').title(),
            'Max Profit': f"{t.max_profit_percent:.1f}%",
            'Max DD': f"{t.max_drawdown_percent:.1f}%"
        })
    
    trades_df = pd.DataFrame(trades_data)
    
    # Color code P&L
    st.dataframe(
        trades_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            'P&L %': st.column_config.TextColumn(
                'P&L %',
                help="Percentage return on position"
            )
        }
    )
    
    # Download option
    csv = trades_df.to_csv(index=False)
    st.download_button(
        "Download Trade List (CSV)",
        csv,
        f"backtest_{result.symbol}_{result.rule_name.replace(' ', '_')}.csv",
        "text/csv"
    )


def render_rule_comparison():
    """Render rule comparison interface."""
    st.subheader("Compare Strategies")
    
    # Symbol input
    symbol = st.text_input("Symbol for comparison", value="RELIANCE", key="compare_symbol")
    
    # Select rules to compare
    all_rules = get_all_preset_rules()
    selected_rules = st.multiselect(
        "Select strategies to compare",
        options=[r.name for r in all_rules],
        default=[all_rules[0].name, all_rules[1].name] if len(all_rules) >= 2 else []
    )
    
    if st.button("Compare", type="primary", key="run_compare"):
        if len(selected_rules) < 2:
            st.warning("Select at least 2 strategies to compare")
            return
        
        with st.spinner("Running comparisons..."):
            # Get data
            from scanner.equity_scanner import get_scanner
            scanner = get_scanner()
            df = scanner.get_historical_data(symbol, days=365)
            
            if df.empty:
                st.error(f"Could not get data for {symbol}")
                return
            
            if 'date' not in df.columns:
                df['date'] = df.index
            
            # Run backtests
            config = BacktestConfig()
            engine = BacktestEngine(config)
            
            rules_to_test = [r for r in all_rules if r.name in selected_rules]
            comparison_df = engine.compare_rules(rules_to_test, df, symbol)
            
            # Display comparison
            st.dataframe(comparison_df, use_container_width=True, hide_index=True)
            
            # Visual comparison
            st.markdown("### Performance Comparison")
            
            # Get results for chart
            results = {}
            for rule in rules_to_test:
                results[rule.name] = engine.run_backtest(rule, df, symbol)
            
            # Win rate comparison
            win_rates = {name: r.win_rate for name, r in results.items()}
            st.bar_chart(pd.DataFrame({'Win Rate %': win_rates}).T, use_container_width=True)
            
            # Return comparison
            returns = {name: r.total_pnl_percent for name, r in results.items()}
            st.bar_chart(pd.DataFrame({'Return %': returns}).T, use_container_width=True)
