# Phase 0 — Foundation

**Objective:** a clean, deterministic, testable, secure project foundation that
later phases build on without a structural rewrite. Foundation only — no
trading behavior of any kind.

## What Phase 0 delivers

* Python 3.12+ project (`pyproject.toml` authoritative; `requirements.txt` mirrors runtime deps).
* Typed, validated, fail-closed configuration (`app/config.py`).
* SQLAlchemy 2.x database foundation (`app/database.py`) + audit models
  (`app/models/`: `system_events`, `errors`, `config_versions`).
* Structured logging with secret redaction (`app/logging_config.py`).
* Exception hierarchy (`app/exceptions.py`).
* UTC time policy + helpers (`app/time_utils.py`), UUID id strategy (`app/ids.py`).
* Offline bootstrap (`app/main.py`) and `scripts/init_db.py`.
* Deterministic, offline test suite (`tests/`).
* Docs, `README.md`, `CLAUDE.md`, `.gitignore`, `.env.example`, minimal Docker.
* Inert future-phase package boundaries.

## What Phase 0 explicitly does NOT do

No exchange connection, market data, indicators, regime, strategy, cost engine,
news, AI/Claude calls, risk engine, sizing, execution, paper/shadow/live
trading, reconciliation, dashboard, Telegram, tax calculation, or credentials.
The system has **zero ability to place an order**.

## Exit criteria

Repository clean · reproducible project · typed/validated config · safe defaults
· `LIVE_TRADING=false` · no credentials · DB initializes · foundation models
work · UTC policy enforced/documented · logging works (with redaction) · errors
have a consistent foundation · bootstrap runs offline · tests pass and are
deterministic · no test needs a network · README/CLAUDE.md/docs present ·
`.gitignore` protects secrets · no future-phase feature implemented · Master
Plan unchanged.

## Next phase

**P1 — Market Data** (separate, explicitly authorized prompt). Do not begin P1
automatically.
