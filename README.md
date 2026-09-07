# Trading Service - Intraday & Swing Trading

A comprehensive trading system for Indian equities using Zerodha Kite Connect API, supporting both **intraday breakout** and **swing trading** strategies with LLM-governed trade validation.

## Features

### Intraday Trading (MIS)
- Opening Range Breakout (ORB)
- Support/Resistance breakouts with volume confirmation
- Auto square-off before market close
- Real-time WebSocket data streaming
- Session-aware trading (no entries after 2:30 PM)

### Swing Trading (CNC)
- Multi-day position holding
- Trend following with EMA crossovers
- Consolidation breakout patterns
- Weekly pivot levels
- Trailing stop loss
- Position persistence across sessions
- Sector exposure limits

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Run Paper Trading

```bash
# Intraday mode (default)
python app.py --style intraday

# Swing mode
python app.py --style swing

# Daily swing report
python app.py --style swing --daily-report
```

### 4. Run Live Trading

```bash
python app.py --style swing --access-token YOUR_TOKEN
```

## Configuration

Edit `config.yaml`:

```yaml
# Trading mode
mode: PAPER  # PAPER or LIVE
trading_style: swing  # intraday or swing

# Capital
capital: 100000

# Intraday settings
intraday:
  start_time: "09:15"
  last_entry_time: "14:30"
  square_off_time: "15:15"

# Swing settings
swing:
  min_holding_days: 2
  max_holding_days: 15
  use_weekly_pivots: true

# Risk management
risk:  # Intraday
  max_positions: 5
  risk_per_trade: 0.005  # 0.5%
  max_daily_loss: 0.02   # 2%

swing_risk:  # Swing
  max_positions: 8
  risk_per_trade: 0.01   # 1%
  max_weekly_loss: 0.05  # 5%
  max_sector_exposure: 0.30  # 30%
```

## Architecture

```
trading_service/
├── app.py                     # Main entry point
├── config.yaml                # Configuration
├── core/
│   ├── config.py             # Config management
│   ├── models.py             # Data models
│   ├── session_manager.py    # Intraday session
│   ├── position_tracker.py   # Intraday positions
│   └── swing_tracker.py      # Swing positions (CNC)
├── data/
│   └── kite_client.py        # Zerodha API wrapper
├── strategies/
│   ├── sr_levels.py          # S/R calculator
│   ├── breakout_detector.py  # Intraday breakouts
│   ├── swing_levels.py       # Weekly pivots, trends
│   └── swing_breakout.py     # Swing signals
├── execution/
│   ├── zerodha.py            # Live execution
│   └── paper.py              # Paper trading
├── risk/
│   ├── risk_guard.py         # Intraday risk
│   └── swing_risk.py         # Swing risk
├── langgraph_flow/
│   ├── graph.py              # Intraday flow
│   └── swing_graph.py        # Swing flow
└── monitoring/
    └── llm_metrics.py        # Logging & metrics
```

## Intraday Strategy

### Breakout Conditions
1. Price closes above resistance (long) or below support (short)
2. Volume > 1.5x 20-day average
3. Risk-reward ratio ≥ 2:1
4. Within trading hours (9:15 AM - 2:30 PM)

### Session Phases
| Phase | Time | Action |
|-------|------|--------|
| Pre-Market | 09:00-09:15 | Load data |
| ORB | 09:15-09:30 | Opening range setup |
| Regular | 09:30-14:30 | Execute trades |
| No Entry | 14:30-15:15 | Manage positions |
| Square-off | 15:15 | Close all |

## Swing Strategy

### Signal Types
- **Trend Continuation**: Strong trend + pullback to EMA
- **Breakout**: Resistance/support break with volume
- **Consolidation Breakout**: Base breakout after tight range
- **Pullback Entry**: Trend pullback to support/resistance

### Risk Management
- 1% capital risk per trade
- Maximum 8 concurrent positions
- 30% max exposure per sector
- Trailing stop after 1.5:1 R:R achieved
- Weekly 5% loss circuit breaker

### Multiple Targets
- Target 1: 2x ATR (partial exit)
- Target 2: 3x ATR
- Target 3: 5x ATR

## CLI Commands

```bash
# Basic usage
python app.py                          # Run with config defaults
python app.py --style swing            # Force swing mode
python app.py --style intraday         # Force intraday mode

# Reports
python app.py --daily-report           # Swing analysis report
python app.py --health-check           # System health

# Live trading
python app.py --access-token TOKEN     # With Kite token

# Debugging
python app.py --log-level DEBUG        # Verbose logging
python app.py --log-file trading.log   # Log to file
```

## API Examples

### Intraday
```python
from langgraph_flow.graph import get_trading_engine
from scanner.equity_scanner import get_scanner

scanner = get_scanner()
scanner.load_historical_data()

engine = get_trading_engine()
engine.update_sr_levels("RELIANCE", daily_df, intraday_df)

result = engine.process_candle("RELIANCE", candle)
print(result["messages"])
```

### Swing
```python
from langgraph_flow.swing_graph import get_swing_trading_engine
from risk.swing_risk import get_swing_risk_guard

engine = get_swing_trading_engine()
engine.initialize()

# Scan watchlist
signals = engine.scan_watchlist(symbol_data)

# Check risk
risk_guard = get_swing_risk_guard()
check = risk_guard.check_trade_allowed(signal)

# Get portfolio
portfolio = risk_guard.get_portfolio_summary()
```

## Position Persistence

Swing positions are saved to `swing_positions.json` and automatically loaded on startup:

```json
{
  "updated_at": "2024-01-15T10:30:00",
  "positions": [
    {
      "symbol": "RELIANCE",
      "side": "BUY",
      "quantity": 10,
      "entry_price": 2450.0,
      "stop_loss": 2380.0,
      "target_1": 2590.0,
      "entry_date": "2024-01-10",
      "is_trailing_sl_active": true
    }
  ]
}
```

## Sector Mapping

Automatic sector classification for exposure limits:
- Banking: HDFCBANK, ICICIBANK, SBIN...
- IT: TCS, INFY, WIPRO...
- Oil & Gas: RELIANCE, ONGC, BPCL...
- Metals: TATASTEEL, HINDALCO...
- Auto: MARUTI, TATAMOTORS...
- FMCG: HINDUNILVR, ITC...

## Disclaimer

⚠️ **For educational purposes only.** Trading involves significant risk. Test thoroughly in paper mode. The developers are not responsible for any financial losses.

## License

MIT License
