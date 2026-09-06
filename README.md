# AI Crypto Trading Bot

An AI-assisted cryptocurrency trading **research** system, built in strict,
gated phases. The goal is not "a bot that makes money" — it is to determine,
under realistic costs, execution constraints, and statistical validation,
whether a durable net trading edge exists at all.

> **No profit is claimed or guaranteed. This is not production trading software.**

## Current status: Phase 7 — Backtesting, Dashboard & Telegram

Phases 0–7 are complete: the software foundation (P0), market data (P1),
indicators + regime (P2), the cost gate (P3), the candidate generator +
advisory sizing (P4), the advisory news + Claude analyst (P5), the deterministic
**RiskManager (final authority)** + paper engine + persistence (P6), and now the
offline research + observability tooling (P7):

* a **pure-quant backtest engine** (`backtesting/`) that replays historical OHLCV
  through the **exact, unmodified** P2→P6 contracts via one global chronological
  multi-symbol event loop (deterministic ordering, one shared account,
  same-boundary reservation for the correlation/cash caps); versioned entry-fill
  modes (`next_open` default); decision-time frozen sizing; provable absence of
  look-ahead;
* **evidence-set** metrics / statistics (seeded bootstrap CI, autocorrelation) /
  robustness (seeded Monte Carlo, trade-removal, cost-scenario sweep) /
  walk-forward + OOS + pre-registration / buy-and-hold benchmark — all
  pure-Python (no numpy/scipy/pandas), reproducible, with a `backtest_runs` index;
* a **read-only FastAPI dashboard** (`dashboard/`) with the only two mutating
  endpoints being stop-direction-only pause/halt (via the existing kill switch);
* a **Telegram** alert channel + inbound pause/halt-only controls
  (`app/notifications/`), offline fixture transport by default.

Everything remains **offline and simulated**: `LIVE_TRADING` stays false; no real
exchange, network, or credentials. The backtest is **pure-quant** — no news/Claude
and **no fabricated historical AI** (Master Plan §8) — and makes **no edge or
performance claim** (no optimizer, no calibration). The dashboard and Telegram
**can never place a trade**. **Backtest/paper performance is never claimed to
equal live.**

## Source of truth

The authoritative architecture and scope document is the **Master Plan**:

```
/Users/josh/.claude/plans/curious-stargazing-chipmunk.md
```

`CRYPTO_BOT_PLAN.md` in this repo is an **early superseded draft** kept for
history only. Do not treat it as authoritative.

## Safety notice

* `LIVE_TRADING` defaults to `false`; enabling it fails at startup (fail-closed).
* No credentials are stored in the repository; `.env` is git-ignored.
* Everything runs offline; the test suite makes no network requests.
* The backtester reuses the frozen P2–P6 contracts, writes no operational tables,
  and never runs the news/Claude layer. The dashboard/Telegram can never trade.

## Requirements

* **Python 3.12+** (enforced via `pyproject.toml`).

## Setup (local development)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # optional; safe defaults work without it
```

## Run tests

```bash
pytest
```

## Initialize the database (offline)

```bash
python -m scripts.init_db
```

## Run the offline bootstrap

```bash
python -m app.main
```

## Run a backtest (offline, pure-quant)

Place a committed OHLCV snapshot under `data/backtests/datasets/<name>/`
(per-symbol/timeframe CSVs; see `backtesting/dataset.py`), then:

```bash
python -m scripts.run_backtest    # writes artifacts + a backtest_runs row; prints an evidence-set report
```

Backtests are offline and deterministic and make **no edge/performance claim**.

## Run the read-only dashboard (optional deps)

```bash
pip install -e ".[dashboard]"
python -m scripts.run_dashboard   # loopback only; read-only + stop-direction-only pause/halt
```

## Configuration

Typed, validated, environment-driven (Pydantic Settings). See `.env.example`
for all keys. Invalid configuration fails at startup (fail-closed).

## Project structure

```
app/            application package
  config.py     typed settings (safe defaults, fail-closed)
  database.py   SQLAlchemy engine/session/init
  models/       audit foundation models (system_events, errors, config_versions)
  logging_config.py  structured logging + secret redaction
  time_utils.py UTC time policy + helpers
  ids.py        UUID id strategy
  main.py       offline bootstrap
  market_data/ indicators/ regime/ strategy/ costs/ news/ ai/ risk/
  sizing/ execution/ portfolio/ engine/          implemented (P1–P6)
  notifications/  Telegram alerts + stop-only controls (P7)
  tax/            future-phase package — intentionally empty (P10)
backtesting/    pure-quant backtest engine + metrics/robustness/walk-forward (P7)
dashboard/      read-only FastAPI dashboard + stop-only controls (P7)
scripts/        init_db, run_backtest, run_dashboard, dev scripts
tests/          pytest suite (offline, deterministic)
docs/           architecture, development, security, phase-0..7
data/ logs/     local (git-ignored) runtime artifacts + backtest outputs
```

## Phase roadmap (summary)

P0 Foundation · P1 Market Data · P2 Indicators+Regime · P3 Cost System ·
P4 Strategy+Sizing · P5 News+Claude · P6 Risk+Paper Engine ·
P7 Backtesting+Dashboard · P8 Shadow Mode · P9 Paper Validation ·
P10 Live Readiness · P11 Small Live.

Live trading is gated behind explicit, measurable live-readiness criteria and
remains disabled by default until then. See the Master Plan for full detail.
