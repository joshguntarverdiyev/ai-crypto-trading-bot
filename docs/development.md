# Development

## Requirements

* Python **3.12+** (enforced by `pyproject.toml` `requires-python`).

## Environment setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optionally copy `.env.example` to `.env`. Safe defaults work without a `.env`.

## Common commands

```bash
pytest                 # run the offline test suite
ruff check .           # lint
mypy                   # type-check the app package
python -m app.main     # offline bootstrap
python -m scripts.init_db   # create the local database
```

## Conventions

* Type hints everywhere; keep modules small and explicit.
* UTC for all persisted timestamps (`app.time_utils.utc_now`); convert to local
  time only at the presentation layer.
* Never log secrets — redaction is enforced in `app/logging_config.py`, but do
  not rely on it as an excuse to log configuration/environment.
* Do not add future-phase dependencies (ccxt, anthropic, telegram, fastapi,
  pandas) until the phase that uses them.

## Phase discipline

Work only within the current phase (`CLAUDE.md`). A feature request is not
authorization to cross a phase gate. Each phase has explicit exit criteria in
the Master Plan; the next phase starts only after they pass.

## Tests

Tests are deterministic and offline. A `conftest.py` autouse fixture blocks
network access, so no test may reach the internet. Use temporary databases
(`tmp_path`) and isolated settings (`load_settings(_env_file=None, ...)`).
