# AI Crypto Trading Bot — Project Plan

## 1. Project Overview

Build an AI-assisted cryptocurrency trading bot that can:

- Monitor cryptocurrency prices continuously.
- Calculate technical indicators.
- Collect and analyze relevant crypto news.
- Use Claude as an AI market analyst.
- Generate BUY / SELL / HOLD signals.
- Apply strict risk-management rules.
- Execute paper trades first.
- Backtest strategies against historical data.
- Send trade and risk notifications through Telegram.
- Provide a web dashboard.
- Support live trading only after extensive testing and with multiple safety controls.

### Core principle

Claude is **not** the execution authority.

The architecture must be:

```text
Market Data
     |
     +---- Technical Analysis
     |
     +---- News Analysis
     |
     v
  Claude AI
     |
     v
Trading Signal
     |
     v
Risk Manager
     |
   PASS / REJECT
     |
     v
Execution Engine
     |
     +---- Paper Trading
     |
     +---- Live Trading (disabled by default)
```

The AI can recommend an action, but the Risk Manager can always reject it.

---

# 2. Important Disclaimer

This project is software for automated trading research and experimentation.

It must NOT assume that AI can reliably predict cryptocurrency prices or guarantee profits.

The system must be designed around:

- capital preservation
- controlled risk
- auditability
- testing
- realistic fees and slippage
- failure handling
- emergency shutdown

Never present simulated or historical profits as guaranteed future returns.

---

# 3. Development Strategy

Build the project in the following order:

1. Project foundation
2. Configuration and secrets
3. Exchange market-data layer
4. Technical indicators
5. News collection
6. Claude analysis
7. Risk management
8. Trading decision engine
9. Paper trading
10. Backtesting
11. Performance analytics
12. Telegram notifications
13. Dashboard
14. Live-trading execution layer
15. Security review
16. Deployment

Do not skip directly to live trading.

---

# 4. Recommended Technology Stack

## Backend

- Python 3.12+
- FastAPI
- Pydantic
- SQLAlchemy
- SQLite for development
- PostgreSQL for production

## Trading / Market Data

- CCXT
- Exchange REST APIs
- WebSocket market data where useful

Initial exchange:

- Binance

Initial symbols:

- BTC/USDT
- ETH/USDT
- SOL/USDT

## Data / Analysis

- pandas
- numpy
- pandas-ta or TA-Lib

Indicators:

- EMA 9
- EMA 20
- EMA 50
- EMA 200
- RSI 14
- MACD
- ATR 14
- Bollinger Bands
- Volume moving average
- Volume ratio
- Price returns

## AI

- Anthropic Claude API

Claude is used for:

- market interpretation
- news interpretation
- market-regime classification
- signal explanation

Claude is NOT responsible for:

- holding exchange API credentials
- directly placing orders
- bypassing risk limits

## Scheduling

- APScheduler

## Notifications

- Telegram Bot API

## Deployment

- Docker
- Docker Compose
- VPS or cloud server

---

# 5. Project Structure

Create:

```text
aicryptotrader/
│
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   │
│   ├── models/
│   │   ├── candle.py
│   │   ├── news.py
│   │   ├── signal.py
│   │   ├── trade.py
│   │   └── portfolio.py
│   │
│   ├── market_data/
│   │   ├── exchange.py
│   │   ├── market_service.py
│   │   └── websocket.py
│   │
│   ├── indicators/
│   │   └── technical_analysis.py
│   │
│   ├── news/
│   │   ├── collector.py
│   │   ├── normalizer.py
│   │   └── sentiment.py
│   │
│   ├── ai/
│   │   ├── claude_client.py
│   │   ├── prompts.py
│   │   └── analyzer.py
│   │
│   ├── strategy/
│   │   └── decision_engine.py
│   │
│   ├── risk/
│   │   └── risk_manager.py
│   │
│   ├── execution/
│   │   ├── paper_trader.py
│   │   └── live_trader.py
│   │
│   ├── portfolio/
│   │   └── portfolio_service.py
│   │
│   └── notifications/
│       └── telegram.py
│
├── backtesting/
│   ├── engine.py
│   ├── metrics.py
│   └── reports.py
│
├── dashboard/
│
├── tests/
│
├── scripts/
│
├── data/
├── logs/
│
├── .env.example
├── .gitignore
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── README.md
└── CLAUDE.md
```

---

# 6. Configuration

Create `.env.example`.

Never hard-code credentials.

Example:

```text
ANTHROPIC_API_KEY=

BINANCE_API_KEY=
BINANCE_SECRET=

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

DATABASE_URL=sqlite:///./data/trading.db

PAPER_TRADING=true
LIVE_TRADING=false

STARTING_BALANCE=10000

MAX_POSITION_SIZE_PCT=5
MAX_TOTAL_EXPOSURE_PCT=30
MAX_DAILY_LOSS_PCT=2
MAX_DRAWDOWN_PCT=10

MIN_AI_CONFIDENCE=0.70
```

Important:

- `.env` must be in `.gitignore`.
- Never print API secrets in logs.
- Never commit credentials to Git.
- Binance API keys must not have withdrawal permissions.
- Live trading must be disabled by default.

---

# 7. Market Data System

The MarketDataService must collect:

- current price
- bid / ask
- OHLCV candles
- volume
- order book information when required

Supported timeframes:

```text
5m
15m
1h
4h
1d
```

The system should retain enough candles to calculate long-term indicators such as EMA 200.

Handle:

- connection errors
- rate limits
- timeouts
- missing candles
- stale data
- malformed exchange responses

Never make a trading decision using stale or incomplete market data.

---

# 8. Technical Analysis

Calculate:

```text
EMA 9
EMA 20
EMA 50
EMA 200
RSI 14
MACD
ATR 14
Bollinger Bands
Volume MA
Volume Ratio
Price Change
```

Example structured output:

```json
{
  "symbol": "BTC/USDT",
  "timeframe": "1h",
  "price": 105200,
  "ema9": 105050,
  "ema20": 104800,
  "ema50": 103900,
  "ema200": 101500,
  "rsi": 61.2,
  "macd": 420,
  "atr": 1850,
  "volume_ratio": 1.42
}
```

If there is not enough historical data:

```text
decision = HOLD
```

---

# 9. News System

Collect recent crypto news from legally accessible APIs and RSS feeds.

Potential sources can include:

- crypto news APIs
- RSS feeds
- official project announcements
- exchange announcements
- government/regulatory announcements

Do not scrape websites in violation of their terms.

Each article should contain:

```text
id
title
source
url
published_at
content/summary
mentioned_assets
```

Remove duplicate stories.

Classify relevance:

```text
BTC
ETH
SOL
CRYPTO_MARKET
REGULATION
MACRO
EXCHANGE
SECURITY
OTHER
```

News must never directly execute a trade.

---

# 10. News Sentiment

Analyze:

- sentiment
- market impact
- affected assets
- confidence
- whether the news is new or already priced in

Example:

```json
{
  "sentiment": "BULLISH",
  "impact": "HIGH",
  "confidence": 0.86,
  "assets": ["BTC"],
  "summary": "Strong positive catalyst for BTC."
}
```

Avoid treating every positive headline as a BUY signal.

---

# 11. Claude AI Analyst

Claude receives structured information.

Example:

```json
{
  "symbol": "BTC/USDT",
  "timeframe": "1h",
  "price": 105200,
  "technical_analysis": {
    "trend": "BULLISH",
    "rsi": 61.2,
    "ema20": 104800,
    "ema50": 103900,
    "volume_ratio": 1.42
  },
  "news": [
    {
      "title": "Example crypto news",
      "sentiment": "BULLISH",
      "impact": "MEDIUM"
    }
  ],
  "portfolio": {
    "exposure_pct": 18,
    "daily_pnl_pct": 0.4
  }
}
```

Claude must return strict JSON:

```json
{
  "decision": "BUY",
  "confidence": 0.81,
  "market_regime": "TRENDING",
  "risk_level": "MEDIUM",
  "suggested_stop_loss_pct": 2.0,
  "suggested_take_profit_pct": 4.0,
  "reasoning_summary": "Bullish trend with supportive volume and no major negative catalyst."
}
```

Allowed decisions:

```text
BUY
SELL
HOLD
```

If information is insufficient:

```text
HOLD
```

---

# 12. Claude Prompt Principles

Claude should be instructed:

1. Do not guarantee profits.
2. Do not invent market data.
3. Do not invent news.
4. Use only supplied information.
5. Prefer HOLD when uncertain.
6. Never bypass risk limits.
7. Return valid JSON.
8. Explain the signal briefly.
9. Consider conflicting technical and news signals.
10. Avoid overtrading.

The prompt should explicitly state:

> You are a market-analysis component inside a larger risk-controlled trading system. You do not execute trades and you cannot override the risk manager.

---

# 13. Risk Management

Initial paper-trading configuration:

```text
Starting balance: 10,000 USDT

Maximum position size: 5%
Maximum total exposure: 30%
Maximum open positions: 3
Maximum daily loss: 2%
Maximum drawdown: 10%
Minimum AI confidence: 70%
```

The RiskManager must reject signals when:

- confidence is too low
- stop loss is missing
- position is too large
- total exposure is too high
- daily loss limit is reached
- maximum drawdown is reached
- market data is stale
- abnormal volatility is detected
- duplicate position exists
- risk/reward is unacceptable

The RiskManager is independent from Claude.

---

# 14. Position Sizing

Do not simply allocate the maximum allowed capital to every BUY.

Calculate position size from:

```text
account equity
risk percentage
entry price
stop-loss distance
```

Example:

```text
Account = 10,000 USDT
Maximum risk per trade = 1%
Risk = 100 USDT
Entry = 100,000
Stop = 98,000
Distance = 2%

Position size should be calculated from the allowed risk,
not simply from available balance.
```

The exact formula must be implemented and tested carefully.

---

# 15. Trading Decision Pipeline

Every cycle:

```text
1. Fetch market data
2. Validate market data
3. Calculate indicators
4. Fetch recent news
5. Analyze relevant news
6. Build Claude input
7. Ask Claude for analysis
8. Validate Claude JSON
9. Send signal to RiskManager
10. RiskManager approves/rejects
11. If approved, create paper order
12. Update portfolio
13. Save audit record
14. Send Telegram notification
```

Never allow Claude to call the exchange directly.

---

# 16. Paper Trading

Start with:

```text
Virtual balance = 10,000 USDT
```

Simulate:

- BUY
- SELL
- fees
- slippage
- stop loss
- take profit
- open positions
- realized PnL
- unrealized PnL

Every trade must be stored.

Example:

```text
Trade ID
Timestamp
Symbol
Side
Entry Price
Exit Price
Quantity
Fees
Stop Loss
Take Profit
PnL
Strategy
AI Confidence
Reason
```

---

# 17. Performance Metrics

Calculate:

```text
Total Return
Daily Return
Win Rate
Loss Rate
Average Win
Average Loss
Profit Factor
Maximum Drawdown
Sharpe Ratio
Number of Trades
Average Holding Time
Fees Paid
```

Always compare the strategy against:

```text
BUY & HOLD BTC
BUY & HOLD ETH
```

A strategy that makes money but performs worse than buy-and-hold should not automatically be considered successful.

---

# 18. Backtesting

Build a backtesting engine.

Important:

## No look-ahead bias

At time T, the strategy can only use:

```text
Data available at or before T
```

It must never use future candles.

For news:

```text
Only use news whose publication timestamp
was already available at the simulated decision time.
```

Include realistic:

- exchange fees
- slippage
- spread assumptions

Test:

```text
BTC/USDT
ETH/USDT
SOL/USDT
```

Timeframes:

```text
15m
1h
4h
```

Generate equity curves and reports.

---

# 19. Paper Trading Validation Period

Before live trading:

Run the bot in paper mode.

Recommended minimum:

```text
Several weeks of continuous paper trading
```

Record:

- every signal
- every rejection
- every trade
- every error
- every API failure
- every abnormal condition

Do not judge the strategy only by total profit.

Pay special attention to:

```text
Maximum Drawdown
Profit Factor
Risk-adjusted returns
Loss streaks
Behavior during high volatility
```

---

# 20. Telegram Notifications

Send:

### BUY

```text
🤖 AI Crypto Trader

BTC/USDT

BUY
Confidence: 81%

Entry: $105,200
Stop Loss: $103,096
Take Profit: $109,408

Risk: MEDIUM
```

### SELL

Include:

- symbol
- price
- PnL
- reason

### Risk Alert

```text
⚠️ RISK LIMIT

Daily loss limit reached.

Trading paused.
```

### System Error

```text
🚨 SYSTEM ERROR

Market data unavailable.

Trading paused.
```

Do not allow Telegram messages to bypass safety controls.

---

# 21. Dashboard

Create a simple dashboard showing:

## Portfolio

```text
Balance
Equity
Total PnL
Daily PnL
Drawdown
Exposure
```

## Positions

```text
Symbol
Entry
Current Price
Size
PnL
Stop Loss
Take Profit
```

## AI Signals

```text
BTC   BUY    81%
ETH   HOLD   56%
SOL   SELL   74%
```

## System

```text
Exchange connection
News service
Claude API
Database
Paper/live mode
Last market update
```

---

# 22. Live Trading Safety

Live trading must be:

```text
LIVE_TRADING=false
```

by default.

Do not enable live trading automatically.

Require multiple explicit conditions.

Example:

```text
PAPER_TRADING=false
LIVE_TRADING=true
LIVE_TRADING_CONFIRMATION=true
```

Also implement:

```text
Emergency Kill Switch
Maximum Daily Loss
Maximum Position Size
Maximum Total Exposure
Maximum Open Positions
Duplicate Order Protection
Stale Data Protection
Exchange Error Protection
```

If the system detects an unknown order execution state:

```text
DO NOT blindly retry.
```

First reconcile the order status with the exchange.

---

# 23. Exchange API Security

The trading API key must:

- have trading permission only if required
- have withdrawals disabled
- never be stored in Git
- never be sent to Claude
- never be printed in logs
- be stored securely

Architecture:

```text
Claude
  |
  X  NO exchange credentials
  |
Risk Manager
  |
Execution Service
  |
Exchange API
```

---

# 24. Emergency Kill Switch

Implement:

```text
TRADING_ENABLED=false
```

If false:

```text
No new trades may be created.
```

The bot should still:

- collect market data
- monitor positions
- send alerts
- log activity

But it must not open new positions.

---

# 25. Error Handling

Every external service must have:

- timeout
- retry policy
- exponential backoff where appropriate
- structured logging
- graceful failure

Services:

```text
Exchange
Claude
News provider
Telegram
Database
```

If Claude is unavailable:

```text
HOLD
```

If market data is unavailable:

```text
NO TRADE
```

If risk manager fails:

```text
NO TRADE
```

If exchange state is unknown:

```text
NO NEW ORDER
```

Fail safely.

---

# 26. Logging

Create structured logs.

Example:

```text
2026-09-02 14:00:01
BTC/USDT
PRICE=105200
RSI=61.2
AI=BUY
CONFIDENCE=0.81
RISK=APPROVED
ACTION=PAPER_BUY
```

Never log:

```text
API keys
API secrets
private credentials
```

---

# 27. Database

Store:

## Candles

```text
symbol
timeframe
timestamp
open
high
low
close
volume
```

## News

```text
title
source
url
published_at
assets
sentiment
impact
```

## Signals

```text
timestamp
symbol
decision
confidence
reason
```

## Trades

```text
entry
exit
quantity
fees
PnL
```

## Portfolio

```text
balance
equity
exposure
drawdown
```

## System Events

```text
timestamp
level
component
message
```

---

# 28. Testing Requirements

Write tests for:

- indicator calculations
- position sizing
- risk limits
- daily loss limit
- drawdown limit
- duplicate orders
- stale data
- malformed Claude responses
- API failures
- paper trading
- PnL calculation
- backtesting
- look-ahead bias prevention

The bot must not be considered ready for live trading until tests pass.

---

# 29. Development Commands

Recommended:

```bash
python -m venv .venv

source .venv/bin/activate
```

Windows:

```bash
.venv\Scripts\activate
```

Install:

```bash
pip install -r requirements.txt
```

Run tests:

```bash
pytest
```

Run API:

```bash
uvicorn app.main:app --reload
```

Run paper trader:

```bash
python -m scripts.run_paper_trading
```

Run backtest:

```bash
python -m scripts.run_backtest
```

---

# 30. Claude Code Development Rules

Create a `CLAUDE.md` file with these rules:

```text
You are working on an automated crypto trading research system.

Never enable live trading automatically.

Never place real orders unless the user explicitly asks for live trading
implementation and all safety checks are present.

Never put secrets in source code.

Never give Claude direct access to exchange credentials.

Keep AI analysis separate from execution.

Keep risk management independent from AI.

Prefer HOLD when information is insufficient.

All trading decisions must be auditable.

All external API calls must handle errors safely.

Never introduce look-ahead bias into backtesting.

Never claim that a strategy guarantees profit.

Before changing architecture, inspect existing code.

Write tests for critical financial logic.

Do not remove risk controls to make a test pass.

Do not disable safety mechanisms without explicit instruction.
```

---

# 31. First Claude Code Prompt

Give Claude Code this instruction first:

```text
Read this entire CRYPTO_BOT_PLAN.md and CLAUDE.md.

Do not implement the whole project at once.

First:

1. Analyze the requirements.
2. Create the project structure.
3. Create configuration management.
4. Create database models.
5. Create logging.
6. Create basic tests.
7. Create .env.example.
8. Create README.md.
9. Do NOT implement live trading.
10. Do NOT place real orders.

After implementation, run the tests and report:

- files created
- architecture
- tests passed
- remaining tasks
- security concerns
```

---

# 32. Second Phase Prompt

After Phase 1 is complete:

```text
Now implement the market-data subsystem.

Do not implement live trading.

Implement:

- CCXT exchange abstraction
- Binance market data
- OHLCV collection
- ticker
- volume
- data validation
- SQLite storage
- retry handling
- rate-limit handling
- tests

Run all tests after implementation.

Do not proceed to another subsystem until the tests pass.
```

---

# 33. Third Phase Prompt

```text
Now implement the technical-analysis subsystem.

Implement:

- EMA 9/20/50/200
- RSI 14
- MACD
- ATR 14
- Bollinger Bands
- Volume MA
- Volume ratio
- Price change

Create clean typed interfaces.

Add tests.

Do not implement trading execution.
```

---

# 34. Fourth Phase Prompt

```text
Now implement the news subsystem.

Use legally accessible APIs/RSS sources.

Implement:

- collection
- normalization
- deduplication
- asset detection
- publication timestamps
- storage
- sentiment/impact interface

Do not allow news to directly trigger trades.

Add tests.
```

---

# 35. Fifth Phase Prompt

```text
Now implement Claude AI analysis.

Claude receives structured technical, market and news data.

Return strict validated JSON:

decision
confidence
market_regime
risk_level
suggested_stop_loss_pct
suggested_take_profit_pct
reasoning_summary

If information is insufficient, return HOLD.

Claude must never execute trades.

Add response validation and tests.
```

---

# 36. Sixth Phase Prompt

```text
Now implement RiskManager.

It must independently evaluate AI signals.

Implement:

- position limits
- exposure limits
- daily loss limit
- maximum drawdown
- confidence threshold
- stop-loss requirement
- take-profit requirement
- stale-data protection
- abnormal-volatility protection
- duplicate-position protection

Every rejection must have a reason.

Add extensive tests.
```

---

# 37. Seventh Phase Prompt

```text
Now connect:

Market Data
→ Technical Analysis
→ News
→ Claude
→ Risk Manager
→ Paper Trader

Do not implement live trading.

Create a complete audit trail.

Run an end-to-end paper-trading simulation.

Report all problems found.
```

---

# 38. Eighth Phase Prompt

```text
Now implement the backtesting engine.

Requirements:

- no look-ahead bias
- realistic fees
- configurable slippage
- historical market data
- historical news timestamps
- position sizing
- stop loss
- take profit
- risk limits

Compare the strategy against buy-and-hold.

Generate performance metrics.

Add tests specifically for look-ahead bias.
```

---

# 39. Ninth Phase Prompt

```text
Now implement Telegram notifications and the dashboard.

Do not add any mechanism that bypasses RiskManager.

Dashboard must show:

- portfolio
- positions
- PnL
- drawdown
- exposure
- AI signals
- risk status
- system health
- paper/live mode
```

---

# 40. Final Live Trading Prompt

Only after substantial paper testing:

```text
Review the entire trading system for live-trading readiness.

Do NOT enable live trading automatically.

Audit:

- exchange API security
- API permissions
- risk controls
- duplicate orders
- unknown order states
- stale data
- Claude failures
- news failures
- database failures
- network failures
- kill switch
- maximum daily loss
- maximum drawdown
- position sizing
- logging
- monitoring

Then implement a separate LiveTradingService.

Live trading must remain disabled by default.

The system must require explicit configuration to enable it.

Never allow Claude to access exchange credentials.

Never allow Claude to directly submit orders.

The final architecture must remain:

Claude
→ Signal
→ RiskManager
→ LiveExecutionService
→ Exchange
```

---

# 41. Success Criteria

The project is successful when:

### Phase 1

- project runs locally
- tests pass
- configuration works

### Phase 2

- market data is reliable
- indicators calculate correctly

### Phase 3

- news is collected and normalized

### Phase 4

- Claude produces validated structured signals

### Phase 5

- RiskManager correctly rejects dangerous trades

### Phase 6

- paper trading works

### Phase 7

- backtesting works without look-ahead bias

### Phase 8

- performance dashboard works

### Phase 9

- Telegram notifications work

### Phase 10

- live trading can be enabled safely

---

# 42. Important Strategic Principle

Do not optimize the system to "trade as much as possible."

Optimize it to:

```text
Trade only when the expected setup
is sufficiently strong
AND
risk is acceptable.
```

HOLD is a valid and often preferable decision.

The bot should be comfortable doing nothing.

---

# 43. Future Improvements

After the basic system works, possible improvements include:

- multiple strategies
- market-regime detection
- volatility-adjusted position sizing
- portfolio correlation analysis
- BTC dominance
- funding rates
- open interest
- liquidation data
- on-chain metrics
- macroeconomic calendar
- ETF flows
- advanced news classification
- strategy ensemble
- machine-learning models
- reinforcement learning research
- multi-exchange execution
- cloud deployment
- advanced monitoring

These should be added only after the basic system is stable.

---

# 44. Recommended Starting Configuration

For the first version:

```text
Exchange: Binance
Assets: BTC, ETH, SOL
Mode: Paper Trading
Starting Balance: 10,000 USDT
Timeframe: 1h
Max Position: 5%
Max Exposure: 30%
Max Daily Loss: 2%
Max Drawdown: 10%
Minimum AI Confidence: 70%
```

Do not start with dozens of coins.

A smaller system is easier to test, debug and understand.

---

# 45. Final Architecture

```text
                         ┌────────────────────┐
                         │ Binance Market Data│
                         └─────────┬──────────┘
                                   │
                                   ▼
                         ┌────────────────────┐
                         │ Technical Analysis │
                         └─────────┬──────────┘
                                   │
                                   │
┌─────────────────┐                ▼
│ Crypto News     │───────► ┌───────────────┐
│ APIs / RSS      │          │ Claude AI     │
└─────────────────┘          │ Market Analyst│
                             └───────┬───────┘
                                     │
                                     ▼
                             ┌───────────────┐
                             │ Trading Signal│
                             └───────┬───────┘
                                     │
                                     ▼
                             ┌───────────────┐
                             │ Risk Manager  │
                             └───────┬───────┘
                                     │
                           ┌─────────┴─────────┐
                           │                   │
                         REJECT              PASS
                           │                   │
                           ▼                   ▼
                          LOG          ┌───────────────┐
                                       │ Paper Trader  │
                                       └───────┬───────┘
                                               │
                                               ▼
                                       ┌───────────────┐
                                       │   Database    │
                                       └───────┬───────┘
                                               │
                           ┌───────────────────┴────────────────┐
                           │                                    │
                           ▼                                    ▼
                    ┌─────────────┐                      ┌─────────────┐
                    │ Telegram    │                      │ Dashboard   │
                    └─────────────┘                      └─────────────┘

                    LIVE TRADING — DISABLED BY DEFAULT

                              PASS
                                │
                                ▼
                       ┌─────────────────┐
                       │ Live Execution  │
                       │ Safety Layer    │
                       └────────┬────────┘
                                │
                                ▼
                          Binance Orders
```

---

# 46. End Goal

The final system should behave like a disciplined automated trading assistant:

```text
Observe
   ↓
Analyze
   ↓
Check News
   ↓
Ask Claude
   ↓
Validate Signal
   ↓
Check Risk
   ↓
Trade OR Do Nothing
   ↓
Record Everything
   ↓
Measure Performance
```

The goal is not to make Claude "guess the next candle."

The goal is to build a **testable, auditable, risk-controlled trading system in which Claude is one analytical component.**


# 47. Trading Costs — Fees, Spread and Slippage

Trading costs are a critical part of the system.

The bot must never evaluate a trade using gross profit alone.

Every potential trade must estimate:

- entry trading fee
- exit trading fee
- bid/ask spread
- expected slippage
- optional funding/borrow costs where applicable
- a safety margin

The core calculation is:

```text
Expected Net P&L
=
Expected Gross P&L
- Entry Fee
- Exit Fee
- Spread Cost
- Slippage Cost
- Other Applicable Costs
```

The system should use the account's actual exchange fee tier when available.

Do not permanently assume a universal fee such as 0.10%.

---

# 48. Fee Manager

Create:

```text
app/costs/
├── fee_manager.py
├── spread_estimator.py
└── slippage_estimator.py
```

The FeeManager should expose functions such as:

```text
estimate_entry_fee()
estimate_exit_fee()
estimate_total_fees()
```

Configuration should support:

```text
MAKER_FEE_PCT
TAKER_FEE_PCT
```

The system must distinguish between maker and taker orders when applicable.

For backtesting, use configurable realistic fee assumptions.

For live trading, reconcile estimated fees with the actual exchange-reported execution fee whenever possible.

---

# 49. Spread Cost

A BUY normally executes near the ask and a SELL near the bid.

Therefore, the bot must consider the current bid/ask spread.

Example:

```text
Bid:  $105,000
Ask:  $105,050

Spread: $50
```

Do not assume the mid-price is the actual execution price.

For liquid markets the spread may be small, but during volatile periods it can expand substantially.

If the spread becomes abnormally large:

```text
NO TRADE
```

---

# 50. Slippage

The expected execution price may differ from the displayed price.

Estimate slippage using:

- current order book depth
- historical execution behavior
- order size
- market volatility

Example:

```text
Expected BUY price: $105,000
Estimated slippage: 0.05%

Effective price:
$105,052.50
```

The bot must include estimated slippage in expected profitability.

Never assume zero slippage in backtests.

---

# 51. Minimum Net Profit Filter

Create a dedicated profitability filter.

The bot must reject trades when the expected net return is too small after all estimated costs.

Example configuration:

```text
MIN_NET_PROFIT_PCT=0.50
```

However, do not blindly use one universal percentage for every market.

The final implementation should support:

- minimum net profit %
- minimum net profit amount
- minimum risk/reward ratio
- minimum expected edge after costs

Example:

```text
Expected gross return: 1.20%

Entry fee:             -0.10%
Exit fee:              -0.10%
Spread:                -0.08%
Slippage:              -0.05%
Safety margin:         -0.10%
--------------------------------
Expected net return:    0.77%
```

If the required minimum is 0.50%:

```text
TRADE MAY PROCEED
```

If:

```text
Expected net return: 0.32%
```

then:

```text
HOLD / REJECT
Reason: insufficient expected edge after costs
```

---

# 52. Position Sizing and Trading Costs

Position size must NOT be increased simply because the bot wants to make more money.

Position sizing is determined by risk.

Example:

```text
Account equity = €1,000
Maximum risk per trade = 1%
Maximum risk = €10

Entry = €100
Stop = €98

Stop distance = 2%
```

The position size is derived from the allowed loss at the stop, while fees and slippage are also included in the risk calculation.

The bot must ensure:

```text
Potential loss at stop
+
estimated trading costs
+
estimated slippage
<= allowed risk
```

---

# 53. Trade Viability Check

Before every trade:

```text
1. Calculate proposed entry.
2. Estimate position size.
3. Estimate entry fee.
4. Estimate exit fee.
5. Estimate spread.
6. Estimate slippage.
7. Calculate expected gross profit.
8. Calculate expected net profit.
9. Calculate net risk/reward.
10. Compare against minimum thresholds.
11. Send to RiskManager.
```

Only then can a trade be approved.

---

# 54. Avoiding Overtrading

The system must prevent excessive low-value trades.

Add:

```text
MIN_TRADE_INTERVAL
MAX_TRADES_PER_HOUR
MAX_TRADES_PER_DAY
MIN_EXPECTED_NET_EDGE
```

These should be configurable.

The bot should not trade simply because a small short-term signal appears.

A valid signal with insufficient expected edge after costs should become:

```text
HOLD
```

---

# 55. Example: Small Trade

Assume:

```text
Position: €100

Expected gross profit: €1.20

Entry fee:      €0.10
Exit fee:       €0.10
Spread:         €0.08
Slippage:       €0.05
Safety margin:  €0.05
```

Then:

```text
€1.20
-€0.10
-€0.10
-€0.08
-€0.05
-€0.05
──────
€0.82 expected net
```

If the strategy's minimum required net profit is €1:

```text
REJECT
```

This prevents the bot from making many trades where the exchange and execution costs consume most of the edge.

---

# 56. Example: Larger Position

A larger position can produce more absolute profit from the same percentage movement, but it also increases risk.

For example:

```text
€1,000 position
1% gross movement = €10 gross P&L

€100 position
1% gross movement = €1 gross P&L
```

The bot must NOT simply multiply position size to increase profits.

Instead:

```text
Risk limit
   ↓
Stop-loss distance
   ↓
Position size
   ↓
Estimated costs
   ↓
Net expected return
```

Position size is therefore a risk decision, not a profit-target decision.

---

# 57. Cost-Aware Backtesting

Backtesting must include:

```text
Trading fees
Spread
Slippage
```

Run every strategy under at least:

```text
Optimistic cost assumption
Base cost assumption
Conservative cost assumption
```

Example:

```text
Scenario       Return

Optimistic     +18.4%
Base           +12.1%
Conservative    +6.2%
```

These numbers are examples only.

The strategy should not be considered robust if profitability disappears under modestly worse execution costs.

---

# 58. Net Performance Metrics

Dashboard and reports should show:

```text
Gross P&L
Trading Fees
Spread Cost
Slippage Cost
Other Costs
NET P&L
```

Example:

```text
Gross P&L:          +€420
Trading fees:        -€96
Spread:              -€31
Slippage:            -€24
Other costs:          -€5
────────────────────────
NET P&L:             +€264
```

The primary performance metric must be:

```text
NET P&L
```

not gross P&L.

---

# 59. Claude's Role in Cost-Aware Decisions

Claude should receive cost estimates as part of its context.

Example:

```json
{
  "expected_gross_return_pct": 1.20,
  "estimated_entry_fee_pct": 0.10,
  "estimated_exit_fee_pct": 0.10,
  "estimated_spread_pct": 0.08,
  "estimated_slippage_pct": 0.05,
  "expected_net_return_pct": 0.87
}
```

Claude should understand that a trade with a weak net edge is not attractive.

However, Claude must NOT be allowed to override the profitability filter.

The final authority remains:

```text
RiskManager + CostManager
```

---

# 60. Cost-Aware AI Prompt

Add this rule to the Claude system prompt:

```text
You are operating inside a cost-aware, risk-controlled trading system.

Never recommend a trade solely because the expected gross price movement is positive.

Consider estimated:
- entry fees
- exit fees
- spread
- slippage
- risk/reward

If the expected edge is too small after costs, prefer HOLD.

You cannot override the minimum-net-profit filter or RiskManager.
```

---

# 61. Cost Manager Architecture

Final trading pipeline:

```text
Market Data
      |
      +---- Bid / Ask
      +---- Order Book
      +---- Volatility
      |
      ▼
Technical Analysis
      |
      ▼
News Analysis
      |
      ▼
Claude AI
      |
      ▼
Expected Return
      |
      ▼
Cost Manager
      |
      +---- Fees
      +---- Spread
      +---- Slippage
      +---- Other Costs
      |
      ▼
Expected NET Edge
      |
      ▼
Risk Manager
      |
   ┌──┴──┐
REJECT  APPROVE
          |
          ▼
     Execution Engine
```

---

# 62. New Configuration

Add:

```text
MAKER_FEE_PCT=0.10
TAKER_FEE_PCT=0.10

MIN_NET_PROFIT_PCT=0.50
MIN_RISK_REWARD=1.5

MAX_SPREAD_PCT=0.20
MAX_ESTIMATED_SLIPPAGE_PCT=0.20

MAX_TRADES_PER_HOUR=3
MAX_TRADES_PER_DAY=20
```

These values are starting configuration examples and must be calibrated using the actual exchange account, market and strategy.

---

# 63. Claude Code Task — Add Cost System

Give Claude Code this prompt:

```text
Read CRYPTO_BOT_PLAN.md.

Implement the complete trading-cost subsystem.

Create:

app/costs/
├── fee_manager.py
├── spread_estimator.py
├── slippage_estimator.py
└── cost_manager.py

Requirements:

1. Estimate entry fees.
2. Estimate exit fees.
3. Estimate spread cost.
4. Estimate slippage.
5. Calculate total estimated trading costs.
6. Calculate expected gross P&L.
7. Calculate expected NET P&L.
8. Calculate expected net return percentage.
9. Implement a minimum-net-profit filter.
10. Implement minimum risk/reward validation.
11. Add maximum spread protection.
12. Add maximum slippage protection.
13. Integrate costs into position sizing.
14. Integrate costs into paper trading.
15. Integrate costs into backtesting.
16. Add cost metrics to the dashboard.
17. Add comprehensive unit tests.

Important:

The bot must never approve a trade based only on gross profit.

Every trade must be evaluated after:
- fees
- spread
- slippage
- applicable costs

If expected net edge is insufficient, return HOLD/REJECTED.

Do not implement live trading as part of this task.

Run all tests after implementation.
```

---

# 64. Final Principle

The bot should think:

```text
"Can I make money?"
```

but more importantly:

```text
"Is there enough expected edge AFTER
fees, spread, slippage and risk?"
```

Only if the answer is yes should the system consider trading.
