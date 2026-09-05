"""RiskManager — deterministic final authority: APPROVE + every control (H6/H8)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.ai.models import (
    AnalystAction,
    AnalystDecision,
    AnalystFailure,
    AnalystVerdict,
)
from app.market_data.models import Symbol
from app.portfolio.models import AccountState, Position, PositionStatus
from app.risk.config import RiskConfig
from app.risk.kill_switch import KillSwitchState, KillSwitchStatus
from app.risk.manager import RiskManager
from app.risk.models import MarketState, RiskDecision, RiskReason
from app.sizing.models import PositionPlan
from app.strategy.models import SignalDirection
from tests._p5_helpers import candidate as make_candidate

BTC = Symbol.parse("BTC/USDT")
DT = datetime(2026, 1, 2, tzinfo=UTC)


def _plan(qty="10", entry="100", stop="97", risk_amount=None) -> PositionPlan:
    q, e, s = Decimal(qty), Decimal(entry), Decimal(stop)
    ra = Decimal(risk_amount) if risk_amount is not None else q * (e - s)
    return PositionPlan(
        symbol=BTC, direction=SignalDirection.LONG, entry_ref=e, stop_price=s,
        quantity=q, notional=q * e, risk_amount=ra,
        risk_per_trade_pct_effective=Decimal("0.003"), exposure_after_pct=Decimal("0.1"),
        sizing_version="size-v1", config_version="x",
    )


def _verdict(action=AnalystAction.PROCEED) -> AnalystVerdict:
    return AnalystVerdict(
        decision=AnalystDecision.APPROVE, action=action, confidence=0.9,
        reason_codes=(), affected_assets=("BTC",), event_risk=None, evidence=(),
        failure=AnalystFailure.OK, model_class="sonnet", model_id="claude-sonnet-4-6",
        prompt_version="analyst-v1", ai_analyst_version="ai-v1",
        news_pipeline_version="news-v1", decision_time=DT, processed_at=DT, latency_seconds=0.0,
    )


def _position(sym: str, qty: str, entry: str) -> Position:
    return Position(
        symbol=Symbol.parse(sym), direction=SignalDirection.LONG, status=PositionStatus.OPEN,
        quantity=Decimal(qty), average_entry=Decimal(entry), stop_price=Decimal("1"),
        target_price=Decimal("999999"), opened_at=DT, closed_at=None, fees_paid=Decimal("0"),
        realized_pnl=Decimal("0"), strategy_version="strat-v1",
    )


def _account(cash="10000", positions=(), hwm="10000") -> AccountState:
    return AccountState(
        cash=Decimal(cash), open_positions=tuple(positions),
        realized_pnl_cum=Decimal("0"), fees_paid_cum=Decimal("0"), hwm_equity=Decimal(hwm),
    )


def _market(
    atr_pct=0.02, spread=0.0, slip=0.0, usable=True, stale=False, last_close="100"
) -> MarketState:
    return MarketState(
        symbol=BTC, decision_time=DT, last_close=Decimal(last_close), atr_pct=atr_pct,
        spread_pct=spread, slippage_pct=slip, usable=usable, stale=stale,
    )


def _eval(*, config=None, candidate="default", plan="default", verdict=None, account=None,
          market=None, kill=None, day="10000", week="10000"):
    rm = RiskManager(config or RiskConfig())
    cand = make_candidate() if candidate == "default" else candidate
    return rm.evaluate(
        candidate=cand, plan=_plan() if plan == "default" else plan,
        verdict=verdict or _verdict(), account=account or _account(),
        market=market or _market(),
        kill_state=kill or KillSwitchState(KillSwitchStatus.RUNNING, None, None),
        day_baseline_equity=Decimal(day), week_baseline_equity=Decimal(week), decision_time=DT,
    )


def test_approve_when_all_pass() -> None:
    a = _eval()
    assert a.decision is RiskDecision.APPROVE
    assert a.reason is RiskReason.OK
    assert a.recomputed_risk_pct is not None


def test_kill_halted_rejects_and_paused_holds() -> None:
    halted = _eval(kill=KillSwitchState(KillSwitchStatus.HALTED, "x", DT))
    assert halted.reason is RiskReason.KILL_SWITCH_HALTED
    paused = _eval(kill=KillSwitchState(KillSwitchStatus.PAUSED, "x", DT))
    assert paused.decision is RiskDecision.HOLD
    assert paused.reason is RiskReason.KILL_SWITCH_PAUSED


def test_fail_closed_inputs() -> None:
    assert _eval(candidate=None).reason is RiskReason.MISSING_CANDIDATE
    assert _eval(plan=None).reason is RiskReason.MISSING_PLAN
    assert _eval(verdict=_verdict(AnalystAction.HOLD)).reason is RiskReason.ANALYST_NOT_PROCEED


def test_market_fail_closed() -> None:
    assert _eval(market=_market(usable=False)).reason is RiskReason.MARKET_INVALID
    assert _eval(market=_market(stale=True)).reason is RiskReason.MARKET_STALE
    assert _eval(market=_market(last_close="0")).reason is RiskReason.NON_FINITE
    assert _eval(market=_market(atr_pct=None)).reason is RiskReason.NON_FINITE


def test_market_precautionary_holds() -> None:
    assert _eval(market=_market(spread=0.02)).reason is RiskReason.ABNORMAL_SPREAD
    assert _eval(market=_market(slip=0.02)).reason is RiskReason.ABNORMAL_SLIPPAGE
    vs = _eval(market=_market(atr_pct=0.2))
    assert vs.decision is RiskDecision.HOLD and vs.reason is RiskReason.VOLATILITY_SHOCK


def test_h6_independent_recompute_rejects_inconsistent_plan() -> None:
    a = _eval(plan=_plan(risk_amount="999"))  # recomputed is 30 → divergence
    assert a.reason is RiskReason.INCONSISTENT_PLAN


def test_per_trade_risk_limit() -> None:
    a = _eval(plan=_plan(qty="40"))  # risk 120 / 10000 = 0.012 > 0.01
    assert a.reason is RiskReason.EXCEEDS_PER_TRADE_RISK


def test_exposure_limits() -> None:
    assert _eval(plan=_plan(qty="25")).reason is RiskReason.EXCEEDS_SINGLE_ASSET  # 2500 > 2000
    corr = _eval(account=_account(positions=[_position("ETH/USDT", "29", "100")]))
    assert corr.reason is RiskReason.EXCEEDS_CORRELATED  # 2900 + 1000 > 3000
    total = _eval(account=_account(positions=[_position("XRP/USDT", "29", "100")]))
    assert total.reason is RiskReason.EXCEEDS_TOTAL  # uncorrelated 2900 + 1000 > 3000


def test_max_positions() -> None:
    acct = _account(
        positions=[_position("ETH/USDT", "1", "100"), _position("XRP/USDT", "1", "100")]
    )
    assert _eval(account=acct).reason is RiskReason.MAX_POSITIONS


def test_insufficient_cash() -> None:
    cfg = RiskConfig(
        max_risk_per_trade_pct=0.99, max_single_asset_exposure_pct=0.99,
        max_total_exposure_pct=0.99, correlated_exposure_cap_pct=0.99,
    )
    a = _eval(config=cfg, plan=_plan(qty="200"))  # notional 20000 > cash 10000
    assert a.reason is RiskReason.INSUFFICIENT_CASH


def test_runtime_loss_and_drawdown_limits() -> None:
    assert _eval(account=_account(cash="9000", hwm="9000"), day="10000", week="9000").reason \
        is RiskReason.DAILY_LOSS_LIMIT
    assert _eval(account=_account(cash="9000", hwm="9000"), day="9000", week="10000").reason \
        is RiskReason.WEEKLY_LOSS_LIMIT
    assert _eval(account=_account(cash="10000", hwm="20000")).reason is RiskReason.DRAWDOWN_LIMIT


def test_claude_cannot_relax_limit() -> None:
    # Even a confident APPROVE verdict cannot rescue a per-trade risk breach.
    a = _eval(plan=_plan(qty="40"), verdict=_verdict(AnalystAction.PROCEED))
    assert a.decision is RiskDecision.REJECT


def test_evaluated_populated_on_approve() -> None:
    ev = _eval().evaluated
    # limits + observed values present and deterministic/serializable (str)
    for key in (
        "max_risk_per_trade_pct", "account_equity", "trade_risk_amount",
        "trade_risk_pct", "single_asset_exposure", "total_exposure",
        "correlated_exposure", "open_positions", "drawdown_pct",
        "daily_loss_pct", "weekly_loss_pct", "atr_pct", "spread_pct",
        "slippage_pct", "hwm_equity", "day_baseline_equity",
    ):
        assert key in ev, key
        assert isinstance(ev[key], str)
    assert ev["max_risk_per_trade_pct"] == "0.01"


def test_evaluated_populated_on_reject() -> None:
    ev = _eval(plan=_plan(qty="40")).evaluated  # per-trade breach
    assert ev["trade_risk_pct"] == str(float(Decimal("120") / Decimal("10000")))
    assert ev["max_risk_per_trade_pct"] == "0.01"


def test_evaluated_populated_on_market_hold() -> None:
    ev = _eval(market=_market(spread=0.02)).evaluated  # abnormal spread HOLD
    assert ev["spread_pct"] == "0.02"
    assert ev["abnormal_spread_pct"] == "0.01"
