"""Launch the read-only monitoring dashboard (Phase 7, dev-only).

Binds to loopback by default (never public). Read views + stop-direction-only
controls (pause/halt via the existing KillSwitch); it cannot place a trade. Run
with the project virtualenv active (requires the optional dashboard deps):

    pip install -e ".[dashboard]"
    python -m scripts.run_dashboard
"""

from __future__ import annotations

from app.config import load_settings
from app.database import init_db, make_engine, make_session_factory
from app.logging_config import configure_logging
from app.risk.kill_switch import KillSwitch


def main() -> None:
    settings = load_settings()
    configure_logging(settings)

    from dashboard.config import DashboardConfig

    dash_cfg = DashboardConfig(
        enabled=settings.dashboard_enabled,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        auth_token=settings.dashboard_auth_token,
    )
    if not dash_cfg.enabled:
        print("DASHBOARD_ENABLED is false — refusing to start (set it to true to run).")
        return

    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    from dashboard.app import create_app  # lazy: imports FastAPI only here

    # Authoritative gate config for /api/paper/validation (the same evaluator the
    # runner uses; read-only). Fail-soft: the dashboard never depends on it — if it
    # can't be built, the validation endpoint simply reports PENDING.
    try:
        paper_cfg = settings.paper_validation_config()
    except Exception:  # noqa: BLE001 — dashboard must never crash on config edge cases
        paper_cfg = None

    app = create_app(
        session_factory=session_factory,
        kill_switch=KillSwitch(session_factory),
        config=dash_cfg,
        paper_validation_config=paper_cfg,
    )

    import uvicorn

    print(
        f"Serving read-only dashboard on http://{dash_cfg.host}:{dash_cfg.port} "
        f"(controls_enabled={dash_cfg.controls_enabled})"
    )
    uvicorn.run(app, host=dash_cfg.host, port=dash_cfg.port, log_level="info")


if __name__ == "__main__":
    main()
