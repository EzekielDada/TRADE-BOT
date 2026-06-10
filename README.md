# Algorithmic Trading Bot

Production-oriented Python trading bot with:

- dual-AI sentiment analysis using Groq and Gemini
- real market data from Bybit public endpoints
- event-pattern risk detection from historical crypto/macro headlines
- scheduled daily briefing, intraday intelligence refresh, and end-of-day review
- SQLite-backed state, trades, signals, headlines, and reports
- Streamlit dashboard and natural-language control interface

## Architecture

```text
main.py
  -> schedule jobs
  -> data.market_data
  -> data.news_data
  -> strategies.technical / market_regime / sentiment / signals
  -> ai.groq_analyzer / gemini_analyzer / consensus / event_patterns
  -> execution.risk_manager / order_manager
  -> storage.py (SQLite)
  -> dashboard.app
```

## Required services

1. Groq: `https://console.groq.com`
2. Gemini: `https://aistudio.google.com`
3. Bybit testnet or live: `https://testnet.bybit.com` and `https://www.bybit.com`
4. NewsAPI: `https://newsapi.org`
5. CryptoCompare: `https://min-api.cryptocompare.com`

No keys are hardcoded. Everything is read from `.env`.

## API key setup

### Groq

1. Sign in at `console.groq.com`
2. Open `API Keys`
3. Create a key
4. Set `GROQ_API_KEY`

### Gemini

1. Open `aistudio.google.com`
2. Click `Get API key`
3. Create a key
4. Set `GEMINI_API_KEY`

### Bybit

1. Register on Bybit testnet first at `testnet.bybit.com`
2. Open `API Management`
3. Create an API key
4. Set `BYBIT_API_KEY`, `BYBIT_SECRET`, and keep `BYBIT_TESTNET=true`

### NewsAPI

1. Register at `newsapi.org`
2. Copy your API key
3. Set `NEWSAPI_KEY`

### CryptoCompare

1. Register at `min-api.cryptocompare.com`
2. Open `Settings -> API Keys`
3. Create a key
4. Set `CRYPTOCOMPARE_API_KEY`

## Python version

Use Python `3.11` or `3.12`.

The pinned stack is not a good fit for Python `3.14` because packages like `pandas==2.2.0` may fall back to source builds and fail on Windows.

## Installation

```bash
python -m venv .venv
```

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in the required keys.

## Important safety defaults

- Start with `PAPER_TRADING=True`
- Keep `BYBIT_TESTNET=true`
- Do not switch to live trading until the bot has run in paper mode for at least 4 weeks
- Never risk money you cannot afford to lose

## Running the bot

```bash
python main.py
```

Scheduled jobs:

- daily premarket briefing
- intraday intelligence refresh
- end-of-day review
- 15-minute trading loop

The trading loop is gated by the daily briefing. Selected assets are written into SQLite state and only those assets are traded that day.

## Dashboard

```bash
streamlit run dashboard/app.py
```

The dashboard includes:

- live overview
- positions and trade history
- AI insights
- control panel

Natural-language commands supported include:

- `Only trade BTC today`
- `Pause trading`
- `Resume trading`
- `Increase risk to 3%`
- `Switch to paper trading`
- `Switch to live trading`
- `What is the bot doing right now?`
- `Why did the bot take the last trade?`
- `How is the bot performing this week?`
- `Show me today's briefing`
- `What patterns are active right now?`
- `Stop the bot`

## Market data behavior

- Candles: Bybit (account API first, public REST as fallback)
- Paper trading still uses real public market data
- The market-data layer no longer invents synthetic candles

If Bybit data cannot be fetched, the bot raises a clear exception instead of fabricating price history.

## Backtesting

Run the backtesting module against real historical OHLCV stored or fetched from Bybit. Historical AI calls are not replayed; the backtest uses Fear & Greed plus price momentum as a documented proxy.

## Tests

```bash
python -m unittest discover -s tests
```

## Deployment

### DigitalOcean / VPS

1. Create a small Ubuntu droplet
2. Install Python 3.11 or 3.12
3. Clone the repo
4. Create `.env`
5. Install dependencies
6. Run `main.py` under `systemd`
7. Run `streamlit` separately and expose it with nginx if needed

### Suggested process split

- `python main.py` for the worker
- `streamlit run dashboard/app.py` for the UI

## Warning

Trading involves real financial risk. Past performance does not guarantee future results. AI analysis can fail, APIs can degrade, and exchange execution can behave unexpectedly during market stress.
