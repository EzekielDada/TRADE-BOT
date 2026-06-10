# 🤖 Production-Ready Algorithmic Trading Bot

A complete, production-grade cryptocurrency trading bot built with real API integrations, dual AI engines (Groq + Google Gemini), and advanced risk management.

## ⚡ Key Features

- **Real API Integrations**: Bybit (primary) + KuCoin (backup) for actual trading
- **Dual AI Engines**: 
  - Groq (Llama 3.3 70B) for fast sentiment analysis
  - Google Gemini for deep contextual analysis
- **Consensus Engine**: Intelligent signal weighting with disagreement detection
- **Event Pattern Recognition**: Historical pattern database with ~20 real trading patterns
- **Multi-Source Sentiment Analysis**: News, Reddit, Fear & Greed, funding rates, L/S ratios
- **Advanced Risk Management**: Position sizing, stop loss, trailing stops, circuit breakers
- **Market Regime Detection**: Trending/Ranging/Volatile/Uncertain regimes with adaptive trading
- **Paper Trading**: Full simulation mode for testing (works without exchange keys!)
- **Real-time Dashboard**: Streamlit-based monitoring and control
- **Backtesting Engine**: Historical testing with walk-forward analysis
- **Comprehensive Logging**: Structured logs for trading, signals, patterns, AI responses
- **Natural Language Control**: Execute trading commands in plain English

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     TRADING BOT CORE                         │
│                        (main.py)                             │
└────────────────────┬────────────────────────────────────────┘
                     │
         ┌───────────┼───────────┬───────────────┐
         │           │           │               │
    ┌────▼────┐  ┌──▼───┐  ┌───▼────┐  ┌──────▼──┐
    │  MARKET  │  │ NEWS  │  │   AI   │  │ SIGNALS │
    │   DATA   │  │ DATA  │  │ LAYER  │  │ LAYER   │
    └────┬────┘  └──┬────┘  └───┬────┘  └──────┬──┘
         │          │            │             │
         │      ┌───▼────────────▼────┐        │
         │      │  CONSENSUS ENGINE   │        │
         │      └────────────────────┘        │
         │                                    │
         └────────────────┬───────────────────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
         ┌────▼───┐  ┌───▼────┐  ┌──▼──────┐
         │  RISK  │  │ ORDER  │  │BACKTESTS│
         │MANAGER │  │MANAGER │  │ ENGINE  │
         └────┬───┘  └───┬────┘  └─────────┘
              │          │
         ┌────▼──────────▼────┐
         │  STORAGE (SQLite)  │
         └────────────────────┘
```

## 📋 Requirements

### API Keys Required (All Free)

1. **Groq API** - https://console.groq.com
   - Model: llama-3.3-70b-versatile
   - Speed: ~100ms per request
   - Free tier: Unlimited for 1 week trial, then 30 requests/min

2. **Google Gemini API** - https://aistudio.google.com  
   - Model: gemini-1.5-flash
   - Free tier: 15 requests/min, 1M tokens/day

3. **Bybit Exchange** - https://bybit.com
   - **MUST START WITH TESTNET**: https://testnet.bybit.com
   - Register SEPARATELY from main account
   - API Key + Secret in Account > API Management

4. **KuCoin Exchange** (Optional backup) - https://kucoin.com
   - API Key + Secret + Passphrase

5. **NewsAPI** - https://newsapi.org
   - Free tier: 100 requests/day

6. **CryptoPanic API** - https://cryptopanic.com
   - Free tier: Available without key

7. **Reddit API (PRAW)** - https://reddit.com/prefs/apps
   - Create script app
   - Client ID + Client Secret

8. **No key needed**:
   - Fear & Greed Index (https://api.alternative.me/fng/)
   - Bybit Public API for funding rates
   - CoinGecko for BTC dominance

## 🚀 Installation

### 1. Clone and Setup

```bash
# Clone repository
git clone <repo-url>
cd trading-bot

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy .env.example to .env
cp .env.example .env

# Edit .env and add all API keys
nano .env
```

**Critical**: The .env file contains secrets. **NEVER commit it to git.**

### 3. Get API Keys (Step by Step)

#### Groq API (2 minutes)
1. Go to https://console.groq.com
2. Sign up with email
3. Click "API Keys" in sidebar
4. Click "Create New API Key"
5. Copy key to `.env` → `GROQ_API_KEY`

#### Gemini API (1 minute)
1. Go to https://aistudio.google.com
2. Sign in with Google account
3. Click "Get API Key" → "Create new API key"
4. Copy key to `.env` → `GEMINI_API_KEY`

#### Bybit Testnet (10 minutes)
1. Go to https://testnet.bybit.com (NOT bybit.com!)
2. Register new account (separate from live)
3. Click Account → API Management
4. Create new API key (restrict to trading only)
5. Copy to `.env`:
   - `BYBIT_API_KEY`
   - `BYBIT_SECRET`
   - Keep `BYBIT_TESTNET=true`

#### Bybit Live (Optional, only after 4+ weeks of paper trading)
1. Go to https://bybit.com
2. Login to account
3. Account → API Management
4. Create new API key
5. In `.env`, set `BYBIT_TESTNET=false`
6. Add live API keys

#### NewsAPI (1 minute)
1. Go to https://newsapi.org
2. Register
3. Copy API key from dashboard to `.env` → `NEWSAPI_KEY`

#### Reddit API (5 minutes)
1. Login to https://reddit.com
2. Go to https://reddit.com/prefs/apps
3. Scroll to "App Management"
4. Click "Create an app"
5. Fill form: name="trading-bot", type="script", redirect URI="http://localhost:8000"
6. Copy to `.env`:
   - `REDDIT_CLIENT_ID` (shown as "client_id")
   - `REDDIT_CLIENT_SECRET` (shown as "client_secret")

#### CryptoPanic (Optional)
1. Go to https://cryptopanic.com
2. Create account
3. Account → API Access
4. Copy auth_token to `.env` → `CRYPTOPANIC_TOKEN`

## 📖 Usage

### 1. First Run (Paper Trading - RECOMMENDED)

```bash
# Ensure PAPER_TRADING=true and BYBIT_TESTNET=true in .env

# Start the bot
python main.py

# In another terminal, start dashboard:
streamlit run dashboard/app.py
```

The bot will:
- Load settings from `.env`
- Initialize all services
- Wait for premarket briefing (06:00 WAT)
- Begin trading loop (every 15 minutes)
- Log everything to `logs/`

**Paper trading works completely without exchange credentials** using Bybit's public API.

### 2. Monitor with Dashboard

Open http://localhost:8501 in browser

- **Overview**: Real-time prices, signals, Fear & Greed
- **Positions**: Open positions and trade history
- **Briefing**: Daily market analysis
- **Insights**: AI model scores and patterns
- **Control**: Execute commands, adjust settings

### 3. Run Backtests

```bash
python backtesting/backtest.py --symbol BTC/USDT --days 365 --output report.json
```

### 4. After 4+ Weeks of Successful Paper Trading

Only then switch to real money:

```bash
# In .env, change:
PAPER_TRADING=false
BYBIT_TESTNET=false

# Restart bot - NOW TRADES WITH REAL MONEY
python main.py
```

**⚠️ WARNING**: Trading with real money carries real financial risk. Past performance does not guarantee future results. Start with small position sizes. Never risk more than you can afford to lose.

## ⚙️ Configuration

Edit `config.py` or use environment variables:

```env
# Trading Mode
PAPER_TRADING=true              # Simulation
EXCHANGE=bybit                  # Primary
BACKUP_EXCHANGE=kucoin          # Fallback

# Symbols to Trade
SYMBOLS=BTC/USDT,ETH/USDT       # Comma-separated

# Timeframes
PRIMARY_TIMEFRAME=1h            # Main signal timeframe
ENTRY_TIMEFRAME=15m             # Fine-grained entries
TREND_TIMEFRAME=4h              # Macro context

# AI Weighting (must sum to 1.0)
TECHNICAL_WEIGHT=0.40
SENTIMENT_WEIGHT=0.40
MARKET_SENTIMENT_WEIGHT=0.20

# Risk Management
RISK_PER_TRADE=0.02             # 2% per trade
DAILY_LOSS_LIMIT=0.05           # Stop at -5% daily
WEEKLY_LOSS_LIMIT=0.10          # Stop at -10% weekly
MAX_DRAWDOWN=0.15               # Pause at -15% from peak
MAX_POSITIONS=3                 # Max concurrent

# Signal Thresholds
# 80-100 = STRONG_BUY
# 65-79  = BUY
# 40-64  = HOLD
# 25-39  = SELL
# 0-24   = STRONG_SELL

# Scheduling
PREMARKET_TIME_WAT=06:00        # Morning briefing
EOD_REVIEW_TIME_WAT=23:00       # End of day
LOOP_INTERVAL_SECONDS=900       # 15 min trading loop
```

## 📊 Understanding the AI Layer

### Groq Analyzer (Fast Pass)
- **Model**: Llama 3.3 70B (open source)
- **Speed**: ~100ms per analysis
- **Input**: Headlines
- **Output**: Sentiment score (0.0-1.0), confidence, risk flags
- **Use**: Initial sentiment screen

### Gemini Analyzer (Deep Context)
- **Model**: Gemini 1.5 Flash (closed source, fast)
- **Speed**: ~1-2s per analysis
- **Input**: Full market context + headlines + patterns + technical indicators
- **Output**: Trade recommendation, key levels, macro risks
- **Use**: Final decision-making

### Consensus Engine
Combines both analyzers with intelligent weighting:
- If models agree within 0.15 → boost confidence by 20%
- If models disagree by 0.15-0.30 → weighted average (higher confidence gets 60%)
- If models disagree by >0.30 → NO TRADES (flag as UNCERTAIN)
- If either confidence <0.50 → weight at 30%, other at 70%

Position size reduced by:
- Models don't agree → 50% reduction
- Pattern score below -0.60 (bearish) → 50% reduction
- Overall confidence <0.60 → 25% reduction

Trades BLOCKED if:
- Risk keywords: "regulation", "ban", "hack", "lawsuit", "SEC", "crash", "depeg", "insolvent"
- Critical pattern detected
- Pattern score <-0.60
- Models disagree by >0.30

## 📈 Event Patterns (Real Historical)

Bot recognizes ~20 historical patterns:

### Bearish Patterns
- `sec_crackdown`: Historical avg -15% over 3-14 days
- `regulation_ban`: Historical avg -20% over 5-21 days
- `exchange_hack`: Historical avg -12% over 3-7 days
- `exchange_collapse`: Historical avg -30% over 14-60 days (CRITICAL)
- `fed_rate_hike`: Historical avg -8% over 1-5 days
- `stablecoin_depeg`: Historical avg -25% over 3-30 days (CRITICAL)
- `whale_movement`: Historical avg -5% over 0-2 days
- `network_attack`: Historical avg -30% over 7-30 days (CRITICAL)

### Bullish Patterns
- `regulation_positive`: Historical avg +10% over 1-5 days
- `etf_approval`: Historical avg +20% over 3-30 days
- `bitcoin_halving`: Historical avg +150% over 90-365 days
- `exchange_listing`: Historical avg +15% over 1-3 days
- `fed_rate_cut`: Historical avg +8% over 2-7 days
- `institutional_adoption`: Historical avg +8% over 1-7 days
- `network_upgrade`: Historical avg +12% over 3-14 days

Pattern matching uses fuzzy text matching (80%+ similarity required).

## 📡 Data Sources & Rate Limits

| Source | Rate Limit | Purpose | API Key |
|--------|-----------|---------|---------|
| Groq | 30 req/min (free) | Sentiment analysis | Required |
| Gemini | 15 req/min (free) | Deep analysis | Required |
| Bybit | 10 req/s | Trading, price data | Optional (paper mode) |
| NewsAPI | 100 req/day | News headlines | Recommended |
| Reddit (PRAW) | 60 req/min | Social sentiment | Recommended |
| CryptoPanic | Unlimited (free) | Crypto news | Optional |
| Fear & Greed | Unlimited (free) | Market sentiment | N/A |
| CoinGecko | 50 req/min (free) | Market data | N/A |

All API calls have:
- Retry logic with exponential backoff
- Rate limit handling
- Timeout protection (10-15s)
- Comprehensive error logging

## 📁 Project Structure

```
trading-bot/
├── main.py                 # Entry point & orchestration
├── config.py              # Settings & environment loading
├── models.py              # Data models (dataclasses)
├── utils.py               # Shared utilities
├── storage.py             # SQLite persistence
├── requirements.txt       # Python dependencies
├── .env.example           # Template environment variables
├── README.md              # This file
│
├── ai/                    # AI Analysis Layer
│   ├── groq_analyzer.py   # Groq sentiment analysis
│   ├── gemini_analyzer.py # Gemini contextual analysis
│   ├── consensus.py       # Combine AI outputs
│   └── event_patterns.py  # Pattern recognition DB
│
├── data/                  # Data Access Layer
│   ├── market_data.py     # Exchange data (OHLCV, tickers)
│   └── news_data.py       # News & social sentiment
│
├── strategies/            # Trading Strategies
│   ├── technical.py       # Technical indicators
│   ├── sentiment.py       # Sentiment aggregation
│   ├── signals.py         # Signal generation
│   └── market_regime.py   # Regime detection
│
├── execution/             # Order & Risk Management
│   ├── order_manager.py   # Execute trades (live/paper)
│   └── risk_manager.py    # Position sizing & stops
│
├── backtesting/           # Historical Testing
│   └── backtest.py        # Backtrader engine
│
├── dashboard/             # Web UI
│   ├── app.py            # Streamlit dashboard
│   └── control.py        # Command interface
│
├── tests/                 # Unit Tests
│   ├── test_consensus.py
│   └── test_signals.py
│
├── logs/                  # Log Files (auto-created)
│   ├── bot.log
│   ├── trades.log
│   ├── signals.log
│   ├── patterns.log
│   ├── commands.log
│   ├── errors.log
│   └── ai_responses.log
│
├── reports/               # Generated Reports
│   ├── daily/            # Daily briefings
│   ├── eod/              # End-of-day reviews
│   └── backtest/         # Backtest results
│
└── runtime/              # Bot State (auto-created)
    └── bot.db            # SQLite database
```

## 🐛 Debugging

### Enable Verbose Logging

```bash
# In Python REPL:
from loguru import logger
logger.enable("trading_bot")  # Extra verbose
```

### Check Logs

```bash
# Watch trade log in real-time
tail -f logs/trades.log

# View AI responses for debugging
tail -f logs/ai_responses.log

# See all errors
tail -f logs/errors.log
```

### Validate Configuration

```bash
python -c "from config import Settings; s = Settings.from_env(); print(s)"
```

### Test API Connections

```bash
# Test Groq
python -c "from groq import Groq; c = Groq(api_key='YOUR_KEY'); print(c.models.list())"

# Test Gemini
python -c "import google.generativeai as genai; genai.configure(api_key='YOUR_KEY'); print(genai.list_models())"

# Test Bybit
python -c "import ccxt; ex = ccxt.bybit(); print(ex.fetch_ticker('BTC/USDT'))"
```

## 🌐 VPS Deployment (24/7 Trading)

### DigitalOcean Setup ($5-6/month)

```bash
# Create droplet: Ubuntu 22.04, $5/month

# SSH into droplet
ssh root@your-droplet-ip

# Install dependencies
apt update && apt install -y python3.10 python3.10-venv python3.10-dev

# Clone repo
cd ~
git clone <repo-url>
cd trading-bot

# Setup
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env
nano .env  # Paste your configuration

# Create systemd service
sudo tee /etc/systemd/system/trading-bot.service << EOF
[Unit]
Description=Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/trading-bot
ExecStart=/root/trading-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Start service
sudo systemctl enable trading-bot
sudo systemctl start trading-bot

# Check status
sudo systemctl status trading-bot

# View logs
sudo journalctl -u trading-bot -f
```

### Nginx Reverse Proxy for Dashboard

```bash
# Install nginx
sudo apt install -y nginx

# Create config
sudo tee /etc/nginx/sites-available/trading-bot << EOF
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8501;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

# Enable
sudo ln -s /etc/nginx/sites-available/trading-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Monitor from Anywhere

1. SSH tunnel to VPS
2. Access dashboard locally
3. Or setup Let's Encrypt SSL + password authentication

## ⚠️ Risk Warnings

**CRITICAL DISCLAIMERS:**

1. **Real Financial Risk**: This bot can lose real money. Do NOT trade with funds you cannot afford to lose.

2. **No Guarantees**: Past performance does not guarantee future results. Markets can gap violently against your positions.

3. **Start Small**: Use paper trading for AT LEAST 4 weeks before real money.

4. **AI Limitations**: AI models can fail, hallucinate, or be wrong. Always maintain circuit breakers and manual oversight.

5. **Regulatory Risk**: Crypto regulations change rapidly. Your jurisdiction may prohibit automated trading.

6. **Technical Risk**: Exchange APIs fail, orders hang, prices slip. Have manual intervention procedures.

7. **Position Limits**: Default max position is 10% of account. Adjust carefully.

8. **Monitor Daily**: Check the dashboard daily. Don't set and forget.

## 📞 Support

Issues or questions?

1. Check logs in `logs/` directory
2. Review README section matching your problem
3. Test API connections individually
4. Verify `.env` has all required keys
5. Run backtests to validate logic

## 📜 License

This project demonstrates real algorithmic trading architecture. Use at your own risk.

---

**Built with**: Python 3.10+, ccxt, pandas, Groq, Gemini, Streamlit

**Last Updated**: 2026-06-09

**Version**: 1.0.0 (Production Beta)
