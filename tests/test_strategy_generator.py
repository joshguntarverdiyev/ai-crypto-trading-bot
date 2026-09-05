"""CandidateGenerator: setup detection, gates, look-ahead safety, fail-safe."""

from __future__ import annotations

from datetime import UTC, datetime

from app.costs.config import CostConfig
from app.costs.manager import CostManager
from app.indicators.models import ComputeReason, FeatureResult, FeatureSnapshot
from app.market_data.models import Symbol, Timeframe
from app.regime.classifier import RegimeClassifier
from app.regime.config import RegimeConfig
from app.regime.models import TrendRegime
from app.strategy.config import STRATEGY_VERSION, StrategyConfig
from app.strategy.generator import CandidateGenerator
from app.strategy.models import CandidateReason, SignalDecision, SignalDirection

BTC = Symbol.parse("BTC/USDT")
BASE = datetime(2026, 1, 1, tzinfo=UTC)
H1_CLOSE = BASE + Timeframe.H1.delta


def _snap(
    *,
    tf: Timeframe = Timeframe.H1,
    open_time: datetime = BASE,
    close_time: datetime | None = None,
    close: float = 100.0,
    ema_short: float | None = 102.0,  # up-trend by default
    ema_long: float | None = 100.0,
    rsi: float | None = 35.0,  # pullback by default (<= 40)
    atr: float | None = 2.0,
    atr_pct: float | None = 0.02,
    warm: bool = True,
    source: str = "fixture",
    symbol: Symbol = BTC,
) -> FeatureSnapshot:
    ct = close_time or (open_time + tf.delta)
    return FeatureSnapshot(
        source=source, symbol=symbol, timeframe=tf, open_time=open_time, close_time=ct,
        close=close,
        ema_short=ema_short if warm else None,
        ema_long=ema_long if warm else None,
        rsi=rsi if warm else None,
        atr=atr if warm else None,
        atr_pct=atr_pct if warm else None,
        warm=warm, indicator_set_version="ind-v1",
    )


def _fr(snaps: list[FeatureSnapshot], *, stale: bool = False) -> FeatureResult:
    return FeatureResult(snaps, True, ComputeReason.OK, stale, "cfg")


def _gov_4h(*, ema_short: float = 102.0, ema_long: float = 100.0) -> FeatureResult:
    """A governing 4h feature (close_time == the 1h close_time; eligible)."""
    return _fr(
        [_snap(tf=Timeframe.H4, close_time=H1_CLOSE, ema_short=ema_short, ema_long=ema_long)]
    )


def _one(
    feature_1h_snap: FeatureSnapshot,
    four_h: FeatureResult | None,
    cfg: StrategyConfig | None = None,
):
    gen = CandidateGenerator(cfg)
    return gen.generate(_fr([feature_1h_snap]), four_h).evaluations[0]


def test_happy_path_produces_long_candidate() -> None:
    ev = _one(_snap(), _gov_4h())
    assert ev.decision is SignalDecision.CANDIDATE
    assert ev.reason is CandidateReason.OK
    c = ev.candidate
    assert c is not None
    assert c.direction is SignalDirection.LONG
    assert c.entry_ref == 100.0
    assert c.stop_price == 100.0 - 1.5 * 2.0  # 97.0
    assert c.target_price == 100.0 + 3.0 * 2.0  # 106.0
    assert c.reward_risk == 2.0
    assert c.expected_gross_move_pct == 3.0 * 0.02
    assert c.confirmed_4h is True
    assert c.edge_assessment.decision.value == "pass"
    assert c.strategy_version == STRATEGY_VERSION


def test_no_4h_confirmation_holds() -> None:
    # require_4h_confirmation defaults True: absent 4h → HOLD
    assert _one(_snap(), None).reason is CandidateReason.NO_4H_CONFIRMATION
    # 4h disagrees (down-trend) → HOLD
    ev = _one(_snap(), _gov_4h(ema_short=98.0, ema_long=100.0))
    assert ev.reason is CandidateReason.NO_4H_CONFIRMATION


def test_long_only_down_or_ranging_trend_holds() -> None:
    down = _one(_snap(ema_short=98.0, ema_long=100.0), _gov_4h())
    assert down.reason is CandidateReason.NO_TREND
    # equality is not an up-trend (strict >)
    flat = _one(_snap(ema_short=100.0, ema_long=100.0), _gov_4h())
    assert flat.reason is CandidateReason.NO_TREND


def test_no_pullback_holds() -> None:
    assert _one(_snap(rsi=55.0), _gov_4h()).reason is CandidateReason.NO_PULLBACK


def test_not_warm_holds() -> None:
    assert _one(_snap(warm=False), _gov_4h()).reason is CandidateReason.NOT_WARM


def test_degenerate_atr_holds_non_finite() -> None:
    assert _one(_snap(atr=0.0, atr_pct=0.0), _gov_4h()).reason is CandidateReason.NON_FINITE


def test_reward_risk_gate() -> None:
    # target==stop mult → reward:risk 1.0 < threshold 2.0 → HOLD (isolate: no 4h req)
    cfg = StrategyConfig(stop_atr_mult=1.5, target_atr_mult=1.5, require_4h_confirmation=False)
    assert _one(_snap(), None, cfg).reason is CandidateReason.RR_TOO_LOW


def test_cost_gate_hold() -> None:
    # Inject a CostManager whose min edge exceeds the expected move → COST_GATE_HOLD.
    cfg = StrategyConfig(require_4h_confirmation=False)
    gen = CandidateGenerator(cfg, CostManager(CostConfig(safety_margin_pct=0.1)))
    ev = gen.generate(_fr([_snap()]), None).evaluations[0]
    assert ev.decision is SignalDecision.HOLD
    assert ev.reason is CandidateReason.COST_GATE_HOLD


def test_uses_own_ema_trend_not_regime_label() -> None:
    # sep = 0.001 < default regime trend_band (0.002): RegimeClassifier calls this
    # RANGING, but the strategy uses a strict EMA compare and still sees an up-trend.
    snap = _snap(ema_short=100.1, ema_long=100.0)
    regime = RegimeClassifier(RegimeConfig()).classify(_fr([snap])).snapshots[0]
    assert regime.trend is TrendRegime.RANGING  # descriptive label would say ranging
    gov = _gov_4h(ema_short=100.1, ema_long=100.0)
    assert _one(snap, gov).decision is SignalDecision.CANDIDATE  # strategy still fires


def test_prefix_invariance_no_look_ahead() -> None:
    snaps = [
        _snap(
            open_time=BASE + i * Timeframe.H1.delta,
            close_time=BASE + (i + 1) * Timeframe.H1.delta,
        )
        for i in range(5)
    ]
    gov = _fr([_snap(tf=Timeframe.H4, close_time=BASE + Timeframe.H1.delta)])  # governs all
    gen = CandidateGenerator()
    full = gen.generate(_fr(snaps), gov).evaluations
    prefix = gen.generate(_fr(snaps[:3]), gov).evaluations
    assert prefix == full[:3]  # earlier decisions unaffected by later candles
