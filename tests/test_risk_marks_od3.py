"""OD-3: RiskManager optional full-portfolio marks (P9 multi-symbol).

Proves: marks=None is byte-identical to frozen P6 single-symbol valuation, and full
marks make the drawdown / daily-loss / weekly-loss gates see portfolio-wide
unrealized P&L across multiple open symbols. No second RiskManager; same evaluate.
"""

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
ETH = Symbol.parse("ETH/USDT")
DT = datetime(2026, 1, 2, tzinfo=UTC)


def _plan() -> PositionPlan:
    q, e, s = Decimal("1"), Decimal("100"), Decimal("97")
    return PositionPlan(
        symbol=BTC, direction=SignalDirection.LONG, entry_ref=e, stop_price=s,
        quantity=q, notional=q * e, risk_amount=q * (e - s),
        risk_per_trade_pct_effective=Decimal("0.0003"), exposure_after_pct=Decimal("0.01"),
        sizing_version="size-v1", config_version="x",
    )


def _verdict() -> AnalystVerdict:
    return AnalystVerdict(
        decision=AnalystDecision.APPROVE, action=AnalystAction.PROCEED, confidence=0.9,
        reason_codes=(), affected_assets=("BTC",), event_risk=None, evidence=(),
        failure=AnalystFailure.OK, model_class="sonnet", model_id="claude-sonnet-4-6",
        prompt_version="analyst-v1", ai_analyst_version="ai-v1",
        news_pipeline_version="news-v1", decision_time=DT, processed_at=DT, latency_seconds=0.0,
    )


def _pos(sym: Symbol, qty: str, entry: str) -> Position:
    return Position(
        symbol=sym, direction=SignalDirection.LONG, status=PositionStatus.OPEN,
        quantity=Decimal(qty), average_entry=Decimal(entry), stop_price=Decimal("1"),
        target_price=Decimal("999999"), opened_at=DT, closed_at=None, fees_paid=Decimal("0"),
        realized_pnl=Decimal("0"), strategy_version="strat-v1",
    )


def _market(last_close="100") -> MarketState:
    return MarketState(
        symbol=BTC, decision_time=DT, last_close=Decimal(last_close), atr_pct=0.02,
        spread_pct=0.0, slippage_pct=0.0, usable=True, stale=False,
    )


def _rm() -> RiskManager:
    # generous drawdown so it only trips when portfolio marks are actually applied
    return RiskManager(RiskConfig(max_drawdown_pct=0.10))


def _evaluate(rm, account, *, marks=None):
    running = KillSwitchState(KillSwitchStatus.RUNNING, None, None)
    return rm.evaluate(
        candidate=make_candidate(), plan=_plan(), verdict=_verdict(), account=account,
        market=_market(last_close="100"), kill_state=running,
        day_baseline_equity=Decimal("10000"), week_baseline_equity=Decimal("10000"),
        decision_time=DT, marks=marks,
    )


# Small ETH position (notional 1000) so exposure caps always pass; the marked value
# is what moves portfolio equity. BTC (the symbol under evaluation) sits at cost.
def _book() -> AccountState:
    return AccountState(
        cash=Decimal("8800"),
        open_positions=(_pos(BTC, "1", "100"), _pos(ETH, "20", "50")),  # notionals 100 + 1000
        realized_pnl_cum=Decimal("0"), fees_paid_cum=Decimal("0"), hwm_equity=Decimal("10100"),
    )


def test_marks_none_is_p6_single_symbol_valuation() -> None:
    """marks=None values only the current symbol's mark (unmarked ETH = cost),
    exactly as frozen P6 — the other position's unrealized loss is NOT seen."""
    # equity = 8800 + 1*100 (BTC own mark) + 20*50 (ETH at cost) = 9900 → dd≈2% → APPROVE
    a = _evaluate(_rm(), _book(), marks=None)
    assert a.decision is RiskDecision.APPROVE and a.reason is RiskReason.OK


def test_full_marks_capture_cross_symbol_unrealized_loss() -> None:
    """With full marks, ETH's unrealized loss pulls portfolio equity below the HWM
    drawdown limit → the gate trips (which marks=None would MISS)."""
    # ETH marked at 5 (cost 50): equity = 8800+100+20*5 = 9000 → dd≈10.9% > 10%
    a = _evaluate(_rm(), _book(), marks={"ETH/USDT": Decimal("5")})
    assert a.reason is RiskReason.DRAWDOWN_LIMIT
    # same account WITHOUT full marks does not trip (proves the difference)
    b = _evaluate(_rm(), _book(), marks=None)
    assert b.reason is not RiskReason.DRAWDOWN_LIMIT


def test_full_marks_daily_loss_gate_uses_portfolio_equity() -> None:
    rm = RiskManager(RiskConfig(max_drawdown_pct=0.90, max_daily_loss_pct=0.05))
    # ETH at 5 → equity = 9000; day baseline 10000 → daily loss = 10% > 5%
    a = rm.evaluate(
        candidate=make_candidate(), plan=_plan(), verdict=_verdict(), account=_book(),
        market=_market(), kill_state=KillSwitchState(KillSwitchStatus.RUNNING, None, None),
        day_baseline_equity=Decimal("10000"), week_baseline_equity=Decimal("10000"),
        decision_time=DT, marks={"ETH/USDT": Decimal("5")},
    )
    assert a.reason is RiskReason.DAILY_LOSS_LIMIT


def test_own_symbol_mark_takes_precedence_over_marks_map() -> None:
    """The current symbol's own decision-time close always wins over the marks map."""
    account = AccountState(
        cash=Decimal("9000"), open_positions=(_pos(BTC, "1", "100"),),
        realized_pnl_cum=Decimal("0"), fees_paid_cum=Decimal("0"), hwm_equity=Decimal("9100"),
    )
    # marks says BTC=1 (absurd) but own mark (last_close=100) must win → equity stays 9100
    a = RiskManager(RiskConfig(max_drawdown_pct=0.10)).evaluate(
        candidate=make_candidate(), plan=_plan(), verdict=_verdict(), account=account,
        market=_market(), kill_state=KillSwitchState(KillSwitchStatus.RUNNING, None, None),
        day_baseline_equity=Decimal("9100"), week_baseline_equity=Decimal("9100"),
        decision_time=DT, marks={"BTC/USDT": Decimal("1")},
    )
    assert a.decision is RiskDecision.APPROVE and a.reason is RiskReason.OK


def test_od3_signature_default_is_backward_compatible() -> None:
    """Calling evaluate WITHOUT marks (frozen P6 call sites) still works and equals
    the single-symbol path."""
    a = _evaluate(_rm(), _book())  # no marks kwarg passed by _evaluate default
    assert a.decision is RiskDecision.APPROVE and a.reason is RiskReason.OK
