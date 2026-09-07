"""P9 validation-gate completion: regime capture/coverage, rolling stability, top-k."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.database import session_scope
from app.indicators.features import FeatureBuilder
from app.market_data.models import Symbol, Timeframe
from app.market_data.service import MarketDataService
from app.models import PaperDecisionRecord
from app.paper import metrics
from app.paper.metrics import (
    _Trade,
    regime_coverage_status,
    rolling_expectancy_stability,
    top_k_concentration,
)
from app.paper.store import make_run_session_factory
from app.regime.classifier import RegimeClassifier
from tests._p6_helpers import build_1h_raw_with_crash, decision_now
from tests._p9_helpers import APPROVE, build_paper, fixture_adapter


# --- GAP 1: regime captured at decision boundary (temporal integrity) --------
def test_regime_recorded_matches_decision_time_inputs(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    runner.run_once(decision_now())
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    with session_scope(run_sf) as s:
        rec = s.scalars(
            select(PaperDecisionRecord).where(PaperDecisionRecord.symbol == "BTC/USDT")
        ).first()
        recorded = rec.regime

    # Independently recompute the regime from the SAME decision-time candles
    # (get_candles(now=decision_time) only returns close_time <= decision_time).
    adapter = fixture_adapter(build_1h_raw_with_crash())
    mds = MarketDataService()
    md1 = mds.get_candles(adapter, Symbol.parse("BTC/USDT"), Timeframe.H1, now=decision_now())
    md4 = mds.get_candles(adapter, Symbol.parse("BTC/USDT"), Timeframe.H4, now=decision_now())
    fb = FeatureBuilder(settings.indicator_config())
    res = RegimeClassifier(settings.regime_config()).classify(fb.build(md1), fb.build(md4))
    snap = res.snapshots[-1]
    expected = f"{snap.trend.value}/{snap.volatility.value}"

    assert recorded is not None
    assert recorded == expected


def test_regime_coverage_observed_once_never_passes() -> None:
    # "observed once" (or too few) → insufficient_data, never pass.
    assert regime_coverage_status({"up/normal": 1}, min_per_cell=15)[0] == "insufficient_data"
    assert regime_coverage_status({}, min_per_cell=15)[0] == "insufficient_data"


def test_regime_coverage_pass_and_fail() -> None:
    assert regime_coverage_status({"up/normal": 15}, min_per_cell=15)[0] == "pass"
    # enough trades overall, but spread so no single cell reaches the floor → fail
    assert regime_coverage_status(
        {"up/normal": 8, "down/low": 8}, min_per_cell=15
    )[0] == "fail"


def test_trade_regime_counts_attributes_by_entry_boundary(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    runner.run_once(decision_now())
    from tests._p6_helpers import exit_decision_time
    runner.run_once(exit_decision_time())
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    trades = metrics.reconstruct_trades(run_sf)
    counts = metrics.trade_regime_counts(run_sf, trades)
    assert sum(counts.values()) == 1  # the one closed trade attributed to its entry regime


# --- GAP 2: rolling expectancy stability -------------------------------------
def _trades(signs: list[int]):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        _Trade(entry_time=base + timedelta(hours=i), gross_pnl=Decimal(s),
               net_pnl=Decimal(s), symbol="BTC/USDT")
        for i, s in enumerate(signs)
    ]


def test_rolling_stability_stable() -> None:
    t = _trades([1] * 9)  # all positive → sign stable across 3 buckets
    assert rolling_expectancy_stability(t, buckets=3, min_trades=6)[0] == "pass"


def test_rolling_stability_unstable() -> None:
    t = _trades([1, 1, 1, -1, -1, -1, 1, 1, 1])  # middle bucket flips sign
    assert rolling_expectancy_stability(t, buckets=3, min_trades=6)[0] == "fail"


def test_rolling_stability_insufficient() -> None:
    assert rolling_expectancy_stability(_trades([1, 1]), buckets=3, min_trades=6)[0] == (
        "insufficient_data"
    )


def test_rolling_stability_deterministic() -> None:
    t = _trades([1, -1, 1, -1, 1, -1, 1, -1, 1])
    assert rolling_expectancy_stability(t, buckets=3, min_trades=6) == (
        rolling_expectancy_stability(t, buckets=3, min_trades=6)
    )


# --- GAP 3: top-k concentration ----------------------------------------------
def _pnls(xs: list[float]):
    return [Decimal(str(x)) for x in xs]


def test_topk_acceptable() -> None:
    assert top_k_concentration(_pnls([3, 2, 1, 1, 1]), k=1, min_trades=3)[0] == "pass"


def test_topk_excessive() -> None:
    # positive only because of one big trade; removing it turns expectancy negative
    assert top_k_concentration(_pnls([10, -1, -1, -1, -1]), k=1, min_trades=3)[0] == "fail"


def test_topk_insufficient() -> None:
    assert top_k_concentration(_pnls([1, 2]), k=3, min_trades=3)[0] == "insufficient_data"


def test_topk_deterministic() -> None:
    xs = _pnls([5, -1, 2, -1, 3, -1])
    assert top_k_concentration(xs, k=2, min_trades=3) == top_k_concentration(xs, k=2, min_trades=3)


def test_evaluate_wires_all_new_gates(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    from tests._p6_helpers import exit_decision_time
    runner.run_once(decision_now())
    runner.run_once(exit_decision_time())
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    names = {g.name for g in metrics.evaluate(run_sf, cfg, run_id).gates}
    assert {"regime_coverage", "rolling_expectancy_stability", "top_k_concentration"} <= names
