# systemd deployment (Phase 9 paper validation)

**Non-active templates.** These `*.service.example` files are NOT installed and start
NO runtime. They document how to run the P9 paper validation on a Linux/systemd VPS as
three coordinated units. Nothing here holds secrets — the app reads credentials from the
git-ignored `.env` in the repo `WorkingDirectory` (never from a unit file).

## Topology

```
ai-paper-bootstrap.service  (Type=oneshot, runs once)
    run_paper --startup-only --emit-run-id-file <REPO>/run/paper-run.env
    → creates the run, freezes the T0 universe, writes PAPER_RUN_ID=<uuid>

ai-paper-runner.service     (Restart=on-failure)
    EnvironmentFile=<REPO>/run/paper-run.env
    run_paper --supervise --run-id ${PAPER_RUN_ID}
    → resumes the SAME run every (re)start; universe never reselected

ai-news-ingest.service      (Restart=on-failure)
    run_news_ingest --supervise --follow-active-run
    → auto-discovers the running+fresh run and binds to its frozen universe;
      no active/ambiguous/stale run ⇒ 0 API calls (fail-closed)
```

## Why this shape

- **No hardcoded run UUID.** The bootstrap publishes the run_id once; the runner reads it
  via `EnvironmentFile`, and the poller discovers it from the `paper_trading_runs` catalog
  (`status='running'` + fresh heartbeat).
- **Explicit identity + fail-closed preserved.** The poller still binds through the
  unchanged `load_frozen_universe`; a missing/invalid/stale/ambiguous identity yields zero
  provider calls before any lock or adapter is created.
- **No universe reselection.** `ConditionPathExists=!…/run/paper-run.env` makes the
  bootstrap idempotent; the runner always resumes (never creates) the run.

## Install

1. Ensure `.env` has `PAPER_VALIDATION_ENABLED=true`, `LIVE_TRADING=false`,
   `PAPER_TRADING=false`, `SHADOW_MODE=false`, and the real source selectors/token.
2. Replace `<ABSOLUTE_REPO_PATH>` and `<RUN_AS_USER>` in the three files.
3. Copy without the `.example` suffix into `/etc/systemd/system/`.
4. `systemctl daemon-reload`
5. `systemctl enable --now ai-paper-bootstrap.service ai-paper-runner.service ai-news-ingest.service`

Verify the poller bound to the run:
`journalctl -u ai-news-ingest -f` → look for `news ingest following active paper_run_id=`.

## Lifecycle notes

- **Graceful stop:** `systemctl stop ai-paper-runner` → run is marked `stopped`; the poller
  then makes zero API calls until the runner is started again.
- **Crash recovery:** after a SIGKILL the runner is resumable once the heartbeat goes stale
  (`PAPER_OWNER_STALE_INTERVALS` × primary timeframe; default 3h at 1h bars). systemd keeps
  retrying in the meantime. Lower `PAPER_OWNER_STALE_INTERVALS` to shorten this (trade-off:
  smaller split-brain guard).
- **Fresh validation run:** stop+disable the units and delete `<REPO>/run/paper-run.env`,
  then re-enable — the bootstrap creates a new run + new frozen universe.

Validate unit syntax before installing: `systemd-analyze verify ./ai-paper-runner.service`
(after substituting the placeholders).
