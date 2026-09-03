# AI Crypto Trading Bot

An AI-assisted cryptocurrency trading **research** system, built in strict,
gated phases. The goal is not "a bot that makes money" — it is to determine,
under realistic costs, execution constraints, and statistical validation,
whether a durable net trading edge exists at all.

> **No profit is claimed or guaranteed. This is not production trading software.**

## Current status: Phase 0 — Foundation

Phase 0 contains **no trading functionality of any kind**: no exchange
connection, no market data, no indicators, no strategy, no AI calls, no paper
or live trading, no order execution. It establishes only the software
foundation (configuration, database, logging, errors, time/ID utilities, the
offline bootstrap, and the test suite) that later phases build on.

## Source of truth

The authoritative architecture and scope document is the **Master Plan**:

```
/Users/josh/.claude/plans/curious-stargazing-chipmunk.md
```

`CRYPTO_BOT_PLAN.md` in this repo is an **early superseded draft** kept for
history only. Do not treat it as authoritative.

## Safety notice

* `LIVE_TRADING` defaults to `false`; enabling it in Phase 0 fails at startup.
* No credentials are stored in the repository; `.env` is git-ignored.
* Everything runs offline; the test suite makes no network requests.

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
  sizing/ execution/ tax/ portfolio/ engine/ notifications/
                future-phase packages — intentionally empty in Phase 0
backtesting/    future phase (P7)
dashboard/      future phase (P7)
scripts/        init_db and dev scripts
tests/          pytest suite (offline, deterministic)
docs/           architecture, development, security, phase-0
data/ logs/     local (git-ignored) runtime artifacts
```

## Phase roadmap (summary)

P0 Foundation · P1 Market Data · P2 Indicators+Regime · P3 Cost System ·
P4 Strategy+Sizing · P5 News+Claude · P6 Risk+Paper Engine ·
P7 Backtesting+Dashboard · P8 Shadow Mode · P9 Paper Validation ·
P10 Live Readiness · P11 Small Live.

Live trading is gated behind explicit, measurable live-readiness criteria and
remains disabled by default until then. See the Master Plan for full detail.
