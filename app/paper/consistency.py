"""Shadow ↔ Paper consistency report (Phase 9, §35.14).

Guards against P9 silently drifting from the frozen decision pipeline. Two
observations at the same ``(decision_time, symbol)`` are compared ONLY when their
inputs are equivalent — matched on the shared audit rows written identically by
both engines (Claude ``model_id``/``prompt_version`` + verdict, RiskManager
``risk_version``/``config_version`` + ``evaluated`` snapshot). Only when inputs
match does a difference in the pipeline-layer outcome count as **drift** (a bug);
otherwise the pair is **not_comparable** (e.g. Shadow and Paper fetched different
external snapshots at different wall-clock moments) — never mislabelled as drift.

Reads both databases READ-ONLY (Shadow's ``shadow_decisions`` live in the DB where
Shadow ran; Paper's ``paper_decisions`` live in the run DB). No mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.models import (
    ClaudeDecisionRecord,
    PaperDecisionRecord,
    RiskDecisionRecord,
    ShadowDecisionRecord,
)


@dataclass(frozen=True)
class ConsistencyRow:
    decision_time: datetime
    symbol: str
    status: str  # consistent | drift | not_comparable | only_shadow | only_paper
    detail: str


def _claude_keys(session: Session, claude_id: str | None) -> tuple | None:
    if claude_id is None:
        return None
    row = session.get(ClaudeDecisionRecord, claude_id)
    if row is None:
        return None
    return (row.model_id, row.prompt_version, row.action, row.decision)


def _risk_keys(session: Session, risk_id: str | None) -> tuple | None:
    if risk_id is None:
        return None
    row = session.get(RiskDecisionRecord, risk_id)
    if row is None:
        return None
    return (row.risk_version, row.config_version, row.evaluated, row.decision, row.reason)


def _inputs_and_outputs(session: Session, claude_id, risk_id):
    """Return (inputs, outputs) tuples for equivalence gating.

    inputs = pipeline inputs that MUST match to be comparable; outputs = the
    pipeline-layer decisions that, given equal inputs, must also match.
    """
    ck = _claude_keys(session, claude_id)
    rk = _risk_keys(session, risk_id)
    claude_inputs = None if ck is None else (ck[0], ck[1])  # model_id, prompt_version
    claude_output = None if ck is None else (ck[2], ck[3])  # action, decision
    risk_inputs = None if rk is None else (rk[0], rk[1], rk[2])  # version, config, evaluated
    risk_output = None if rk is None else (rk[3], rk[4])  # decision, reason
    return (claude_inputs, risk_inputs), (claude_output, risk_output)


def compare(
    shadow_sf: sessionmaker[Session], paper_sf: sessionmaker[Session]
) -> list[ConsistencyRow]:
    """Compare Shadow and Paper decisions at matching boundaries (input-gated)."""
    out: list[ConsistencyRow] = []
    with session_scope(paper_sf) as p_sess, session_scope(shadow_sf) as s_sess:
        paper_rows = p_sess.scalars(select(PaperDecisionRecord)).all()
        for pr in paper_rows:
            sr = s_sess.scalars(
                select(ShadowDecisionRecord).where(
                    ShadowDecisionRecord.decision_time == pr.decision_time,
                    ShadowDecisionRecord.symbol == pr.symbol,
                )
            ).first()
            if sr is None:
                out.append(ConsistencyRow(pr.decision_time, pr.symbol, "only_paper", ""))
                continue

            p_in, p_out = _inputs_and_outputs(p_sess, pr.claude_decision_id, pr.risk_decision_id)
            s_in, s_out = _inputs_and_outputs(
                s_sess, sr.claude_decision_id, sr.risk_decision_id
            )

            # Need at least the risk-layer inputs on BOTH sides to be comparable.
            if p_in[1] is None or s_in[1] is None:
                out.append(
                    ConsistencyRow(
                        pr.decision_time, pr.symbol, "not_comparable",
                        "risk inputs absent on one side (e.g. early HOLD before risk stage)",
                    )
                )
                continue
            if p_in != s_in:
                out.append(
                    ConsistencyRow(
                        pr.decision_time, pr.symbol, "not_comparable",
                        "inputs differ (different external snapshots) — expected, not drift",
                    )
                )
                continue

            # Inputs are equivalent → pipeline outputs MUST match, else DRIFT.
            if p_out == s_out:
                out.append(ConsistencyRow(pr.decision_time, pr.symbol, "consistent", ""))
            else:
                out.append(
                    ConsistencyRow(
                        pr.decision_time, pr.symbol, "drift",
                        f"equal inputs but pipeline outputs differ: paper={p_out} shadow={s_out}",
                    )
                )
    return out


def summarize(rows: list[ConsistencyRow]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for r in rows:
        summary[r.status] = summary.get(r.status, 0) + 1
    return summary
