# AI Crypto Trading Bot

An AI-assisted cryptocurrency trading **research** system, built in strict,
gated phases. The goal is not "a bot that makes money" — it is to determine,
under realistic costs, execution constraints, and statistical validation,
whether a durable net trading edge exists at all.

> **No profit is claimed or guaranteed. This is not production trading software.**

## Current status: Phase 5 — News Intelligence + Claude Analyst

Phases 0–5 are complete: the software foundation (P0), exchange-agnostic market
data (P1), deterministic indicators + descriptive regime (P2), the trading-cost
model + net-edge gate (P3), the hypothesis-first candidate generator +
risk-budgeting sizing (P4), and now the news-intelligence pipeline + a
strictly-advisory Claude analyst veto (P5). Everything remains **offline,
deterministic, and pre-runtime**: news fetch and the Claude call sit behind
interfaces with offline fixtures (no network, no `anthropic` dependency, no
credentials); there is no RiskManager, paper/live trading, or order execution.
A P4 candidate is a *proposal*, a sized plan is *advisory*, and the analyst is
*advisory only* (APPROVE→proceed, anything else / any failure → HOLD) — none is
authorization to trade. The RiskManager (P6) will be the final authority.

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
