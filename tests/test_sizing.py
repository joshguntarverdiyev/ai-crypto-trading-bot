"""PositionSizer: risk-budget math, rounding, exchange + portfolio caps, fail-safe."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.costs.manager import CostManager
from app.market_data.models import Symbol, Timeframe
from app.sizing.config import SIZING_VERSION, SizingConfig
from app.sizing.models import SizingDecision, SizingReason
from app.sizing.sizer import PositionSizer
from app.strategy.models import Candidate, SignalDirection

BTC = Symbol.parse("BTC/USDT")
BASE = datetime(2026, 1, 1, tzinfo=UTC)
# A real EdgeAssessment (the sizer does not read it, but Candidate requires one).
_EA = CostManager().assess_edge(expected_gross_move_pct=0.06, atr_pct=0.02)


def _cand(entry: float = 100.0, stop: float = 97.0, symbol: Symbol = BTC) -> Candidate:
    return Candidate(
        direction=SignalDirection.LONG, source="fixture", symbol=symbol,
        timeframe=Timeframe.H1, open_time=BASE, close_time=BASE + Timeframe.H1.delta,
        entry_ref=entry, stop_price=stop, target_price=entry + (entry - stop) * 2,
        risk_distance_pct=(entry - stop) / entry, expected_gross_move_pct=0.06,
        reward_risk=2.0, atr=2.0, atr_pct=0.02, confirmed_4h=True,
        governing_4h_open_time=None, edge_assessment=_EA,
        strategy_version="strat-v1", config_version="x",
    )


SIZER = PositionSizer()


def test_basic_sized_within_risk_budget() -> None:
    r = SIZER.plan(_cand(), account_equity=Decimal("10000"))
    assert r.decision is SizingDecision.SIZED
    assert r.reason is SizingReason.OK
    plan = r.plan
    assert plan is not None
    # risk budget = 0.5% of 10000 = 50; never exceeded (quantity floored)
    assert plan.risk_amount <= Decimal("50")
    assert plan.quantity % SizingConfig().step_size == 0  # step-aligned
    assert plan.notional == plan.quantity * plan.entry_ref
    assert plan.sizing_version == SIZING_VERSION


def test_invalid_stop() -> None:
    eq = Decimal("10000")
    assert SIZER.plan(_cand(stop=100.0), account_equity=eq).reason is SizingReason.INVALID_STOP
    assert SIZER.plan(_cand(stop=101.0), account_equity=eq).reason is SizingReason.INVALID_STOP


def test_insufficient_equity() -> None:
    r = SIZER.plan(_cand(), account_equity=Decimal("0"))
    assert r.decision is SizingDecision.NO_TRADE
    assert r.reason is SizingReason.INSUFFICIENT_EQUITY


def test_below_min_notional() -> None:
    r = SIZER.plan(_cand(), account_equity=Decimal("1"))  # budget 0.005 → tiny size
    assert r.reason is SizingReason.BELOW_MIN_NOTIONAL


def test_single_asset_cap() -> None:
    r = SIZER.plan(
        _cand(), account_equity=Decimal("10000"),
        current_exposures={"BTC/USDT": Decimal("1900")},  # +~1666 > 2000 cap
    )
    assert r.reason is SizingReason.EXCEEDS_SINGLE_ASSET_CAP


def test_correlated_cap_btc_eth() -> None:
    eth = Symbol.parse("ETH/USDT")
    r = SIZER.plan(
        _cand(symbol=eth), account_equity=Decimal("10000"),
        current_exposures={"BTC/USDT": Decimal("2000")},  # group {BTC,ETH}: 2000+1666>3000
    )
    assert r.reason is SizingReason.EXCEEDS_CORRELATED_CAP


def test_total_cap_uncorrelated() -> None:
    ltc = Symbol.parse("LTC/USDT")
    r = SIZER.plan(
        _cand(symbol=ltc), account_equity=Decimal("10000"),
        current_exposures={"XRP/USDT": Decimal("2900")},  # different groups; total 4566>3000
    )
    assert r.reason is SizingReason.EXCEEDS_TOTAL_CAP


def test_max_positions_reached() -> None:
    ltc = Symbol.parse("LTC/USDT")
    r = SIZER.plan(
        _cand(symbol=ltc), account_equity=Decimal("1000000"),
        current_exposures={"BTC/USDT": Decimal("1000"), "ETH/USDT": Decimal("1000")},
    )
    assert r.reason is SizingReason.MAX_POSITIONS_REACHED  # 2 existing + 1 new > 2


def test_liquidity_cap() -> None:
    sizer = PositionSizer(SizingConfig(liquidity_cap_quote=Decimal("100")))
    r = sizer.plan(_cand(), account_equity=Decimal("1000000"))
    assert r.reason is SizingReason.LIQUIDITY_CAP


def test_tick_and_step_rounding() -> None:
    r = SIZER.plan(_cand(entry=100.017, stop=97.004), account_equity=Decimal("10000"))
    assert r.plan is not None
    assert r.plan.entry_ref == Decimal("100.02")  # rounded to tick 0.01
    assert r.plan.stop_price == Decimal("97.00")
    assert r.plan.quantity % SizingConfig().step_size == 0


def test_non_finite_candidate_price() -> None:
    r = SIZER.plan(_cand(entry=float("inf")), account_equity=Decimal("10000"))
    assert r.decision is SizingDecision.NO_TRADE
    assert r.reason is SizingReason.NON_FINITE


def test_no_fixed_capital_size_scales_with_equity() -> None:
    small = SIZER.plan(_cand(), account_equity=Decimal("10000")).plan
    big = SIZER.plan(_cand(), account_equity=Decimal("20000")).plan
    assert small is not None and big is not None
    assert big.quantity > small.quantity  # size is driven by supplied equity, not a default


def test_deterministic() -> None:
    a = SIZER.plan(_cand(), account_equity=Decimal("10000"))
    b = SIZER.plan(_cand(), account_equity=Decimal("10000"))
    assert a == b
