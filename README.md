# SPY Gap Mean-Reversion Trading Bot

An intraday trading bot that exploits overnight gap mean-reversion on SPY using Bollinger-style volatility bands. Built with the official [alpaca-py](https://github.com/alpacahq/alpaca-py) SDK. **Paper trading only.**

## Strategy Overview

1. **Gap detection** — computes the overnight gap between prior regular-session close and today's open.
2. **Entry** — if the gap exceeds a threshold, the bot waits for price to touch a volatility band in the reversion direction:
   - Gap down + price touches lower band → **long**
   - Gap up + price touches upper band → **short**
3. **Exit** — mean/VWAP reversion, stop loss, or forced end-of-day flatten.
4. **Guardrails** — max trades/day, risk-based position sizing, entry window cutoff.

## State Machine

```
IDLE → ARMED → IN_TRADE → LOCKED
         ↑         |
         └─────────┘  (after exit, if trades remain)
```

- **IDLE** — waiting for market open
- **ARMED** — scanning for entry signals
- **IN_TRADE** — position open, monitoring for exit
- **LOCKED** — daily limit hit or past entry window with no position

## Project Structure

```
├── Procfile              # Railway worker definition
├── requirements.txt
├── .env.example          # Example environment config
├── src/
│   ├── __init__.py
│   ├── __main__.py       # `python -m src` entry point
│   ├── bot.py            # Main loop + state machine
│   ├── config.py         # Env var loading
│   ├── data.py           # Alpaca data fetching
│   ├── execution.py      # Order submission
│   ├── indicators.py     # Bands, gap, VWAP
│   ├── logging_utils.py  # JSON structured logging
│   ├── market_hours.py   # Market-hours gating
│   ├── risk.py           # Position sizing + trade limits
│   └── strategy.py       # Signal generation
```

## Local Setup

### 1. Clone and create a virtual environment

```bash
git clone <your-repo-url>
cd alpaca1
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your Alpaca paper-trading API keys
```

Get your paper-trading keys at <https://app.alpaca.markets/> → Paper Trading → API Keys.

### 4. Run the bot

```bash
python -m src.bot
```

The bot will:
- Wait for market open (09:30 ET) if run outside trading hours.
- Poll every 60 seconds during market hours.
- Flatten all positions 5 minutes before close.
- Shut down cleanly on `Ctrl+C` (SIGINT) or SIGTERM.

## DRY_RUN Mode

Set `DRY_RUN=true` in your `.env` to log all signals and would-be orders **without** submitting them to Alpaca. This is useful for verifying strategy logic before risking paper capital.

```env
DRY_RUN=true
```

## Railway Deployment

### 1. Push to GitHub

Commit and push this repo to GitHub.

### 2. Create a Railway project

1. Go to <https://railway.app/> and create a new project.
2. Connect your GitHub repo.
3. Railway will detect the `Procfile` and configure the service as a **worker** (not a web server).

### 3. Set environment variables

In the Railway dashboard, add these variables:

| Variable | Required | Description |
|---|---|---|
| `ALPACA_KEY` | Yes | Alpaca paper API key |
| `ALPACA_SECRET` | Yes | Alpaca paper API secret |
| `ALPACA_PAPER` | Yes | Must be `true` |
| `SYMBOL` | No | Default: `SPY` |
| `MAX_TRADES_PER_DAY` | No | Default: `5` |
| `RISK_PCT` | No | Default: `0.01` |
| `GAP_THRESHOLD` | No | Default: `0.005` |
| `BAND_LOOKBACK` | No | Default: `20` |
| `BAND_MULT` | No | Default: `2.0` |
| `ENTRY_WINDOW_MINUTES` | No | Default: `30` |
| `STOP_PCT` | No | Default: `0.01` |
| `USE_VWAP_EXIT` | No | Default: `true` |
| `DRY_RUN` | No | Default: `false` |

### 4. Deploy

Railway will build and start the worker automatically. Check logs in the Railway dashboard.

## Important Warnings

### Paper vs. Live Fills

- **Paper trading fills are instant and always at the quoted price.** Real markets have slippage, partial fills, and rejections.
- This bot uses **market orders**, which are fine for paper but can get poor fills in live trading on volatile names.
- The bot enforces `ALPACA_PAPER=true` and will **refuse to start** if set to `false`. This is intentional for v1.

### Not Financial Advice

This is an educational/experimental project. Do not use it with real money without thorough backtesting and understanding of the risks involved. Past performance of any strategy does not guarantee future results.

### Known Limitations

- No websocket streaming — the bot polls on a 1-minute interval. Latency-sensitive strategies should use the Alpaca streaming API.
- No persistence — state is in-memory and resets on restart. A restart mid-trade will trigger the EOD flatten logic on the next tick.
- Holiday calendar is not checked — the bot relies on weekday checks and will attempt to trade on market holidays (Alpaca will simply return no data).
- Position reconciliation on startup is minimal — if restarted with an open position, the bot won't know the original entry price.

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `SYMBOL` | `SPY` | Ticker to trade |
| `MAX_TRADES_PER_DAY` | `5` | Hard cap on round-trip trades per day |
| `RISK_PCT` | `0.01` | Fraction of equity risked per trade (1%) |
| `GAP_THRESHOLD` | `0.005` | Minimum absolute gap to trigger strategy (0.5%) |
| `BAND_LOOKBACK` | `20` | Rolling window for volatility bands (bars) |
| `BAND_MULT` | `2.0` | Band width multiplier (standard deviations) |
| `ENTRY_WINDOW_MINUTES` | `30` | Minutes after open to accept new entries |
| `STOP_PCT` | `0.01` | Stop-loss distance as fraction of entry price (1%) |
| `USE_VWAP_EXIT` | `true` | Exit when price reverts to VWAP |
| `DRY_RUN` | `false` | Log signals without placing orders |
