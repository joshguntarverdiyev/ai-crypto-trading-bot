"""CandidateGenerator — hypothesis-first long candidate generation (Phase 4).

Stateless and deterministic, like ``RegimeClassifier``. Consumes Phase 2
``FeatureResult`` (1h primary + optional 4h) and a Phase 3 ``CostManager``. Per
1h snapshot it applies, in order:

    warm/finite gate → own EMA up-trend → causal 4h confirmation → RSI pullback
    → ATR-based stop/target → reward:risk gate → P3 cost gate  →  CANDIDATE

Any failed step → HOLD with a reason (fail-safe: unknown/missing/degenerate →
HOLD, never a permissive candidate; Master Plan §0.1-3 / rule 7). Long-only:
down/ranging trends never produce a candidate (§3).

Boundary: the strategy computes its OWN EMA trend condition from feature values;
it never consumes ``RegimeClassifier`` labels (regime is descriptive only). It
reuses the pure causal helper ``app.regime.alignment.governing_4h`` for 4h lookup
(alignment, not a regime label).

Nothing here is a prediction or an order. ``expected_gross_move_pct`` is a
provisional model assumption (Contract clarification 1); P7 owns validation.
"""

from __future__ import annotations

import math

from app.costs.manager import CostManager
from app.costs.models import EdgeDecision
from app.indicators.models import FeatureResult, FeatureSnapshot
from app.regime.alignment import governing_4h
from app.strategy.config import STRATEGY_VERSION, StrategyConfig
from app.strategy.models import (
    Candidate,
    CandidateReason,
    CandidateResult,
    SignalDecision,
    SignalDirection,
    SignalEvaluation,
)


class CandidateGenerator:
    def __init__(
        self,
        config: StrategyConfig | None = None,
        cost_manager: CostManager | None = None,
    ) -> None:
        self._cfg = config or StrategyConfig()
        self._cost = cost_manager or CostManager()

    def _is_up_trend(self, ema_short: float | None, ema_long: float | None) -> bool:
        """Strategy's OWN trend condition (not a regime label). Strict >."""
        return ema_short is not None and ema_long is not None and ema_short > ema_long

    def _hold(
        self, s: FeatureSnapshot, reason: CandidateReason, cfgv: str
    ) -> SignalEvaluation:
        return SignalEvaluation(
            source=s.source,
            symbol=s.symbol,
            timeframe=s.timeframe,
            open_time=s.open_time,
            close_time=s.close_time,
            decision=SignalDecision.HOLD,
            reason=reason,
            candidate=None,
            strategy_version=STRATEGY_VERSION,
            config_version=cfgv,
        )

    def _evaluate(
        self, s: FeatureSnapshot, snapshots_4h: list[FeatureSnapshot], cfgv: str
    ) -> SignalEvaluation:
        cfg = self._cfg

        # --- warm / finite gate (fail-safe) ---
        if not s.warm or s.rsi is None or s.atr is None or s.atr_pct is None:
            return self._hold(s, CandidateReason.NOT_WARM, cfgv)
        values = (s.close, s.ema_short, s.ema_long, s.rsi, s.atr, s.atr_pct)
        if any(v is None or not math.isfinite(v) for v in values):
            return self._hold(s, CandidateReason.NON_FINITE, cfgv)
        if s.close <= 0.0 or s.atr <= 0.0 or s.atr_pct <= 0.0:
            # Degenerate: no usable stop/target distance → conservative HOLD.
            return self._hold(s, CandidateReason.NON_FINITE, cfgv)

        # --- own up-trend (long-only) ---
        if not self._is_up_trend(s.ema_short, s.ema_long):
            return self._hold(s, CandidateReason.NO_TREND, cfgv)

        # --- causal 4h confirmation (unknown/absent/disagree → HOLD) ---
        governing = governing_4h(s, snapshots_4h) if snapshots_4h else None
        confirmed_4h = governing is not None and self._is_up_trend(
            governing.ema_short, governing.ema_long
        )
        governing_open = governing.open_time if governing is not None else None
        if cfg.require_4h_confirmation and not confirmed_4h:
            return self._hold(s, CandidateReason.NO_4H_CONFIRMATION, cfgv)

        # --- RSI pullback ---
        if not (s.rsi <= cfg.rsi_pullback_level):
            return self._hold(s, CandidateReason.NO_PULLBACK, cfgv)

        # --- ATR-based stop/target (provisional model assumption, not a prediction) ---
        entry_ref = s.close
        stop_price = entry_ref - cfg.stop_atr_mult * s.atr
        target_price = entry_ref + cfg.target_atr_mult * s.atr
        risk_distance_pct = cfg.stop_atr_mult * s.atr_pct
        expected_gross_move_pct = cfg.target_atr_mult * s.atr_pct
        reward_risk = cfg.target_atr_mult / cfg.stop_atr_mult

        # --- reward:risk gate (the §4 half deferred from P3) ---
        if reward_risk < cfg.rr_threshold:
            return self._hold(s, CandidateReason.RR_TOO_LOW, cfgv)

        # --- P3 cost gate (net-edge; CostManager is the authority) ---
        edge = self._cost.assess_edge(
            expected_gross_move_pct=expected_gross_move_pct,
            atr_pct=s.atr_pct,
            scenario=cfg.cost_scenario,
        )
        if edge.decision is not EdgeDecision.PASS:
            return self._hold(s, CandidateReason.COST_GATE_HOLD, cfgv)

        candidate = Candidate(
            direction=SignalDirection.LONG,
            source=s.source,
            symbol=s.symbol,
            timeframe=s.timeframe,
            open_time=s.open_time,
            close_time=s.close_time,
            entry_ref=entry_ref,
            stop_price=stop_price,
            target_price=target_price,
            risk_distance_pct=risk_distance_pct,
            expected_gross_move_pct=expected_gross_move_pct,
            reward_risk=reward_risk,
            atr=s.atr,
            atr_pct=s.atr_pct,
            confirmed_4h=confirmed_4h,
            governing_4h_open_time=governing_open,
            edge_assessment=edge,
            strategy_version=STRATEGY_VERSION,
            config_version=cfgv,
        )
        return SignalEvaluation(
            source=s.source,
            symbol=s.symbol,
            timeframe=s.timeframe,
            open_time=s.open_time,
            close_time=s.close_time,
            decision=SignalDecision.CANDIDATE,
            reason=CandidateReason.OK,
            candidate=candidate,
            strategy_version=STRATEGY_VERSION,
            config_version=cfgv,
        )

    def generate(
        self, feature_1h: FeatureResult, feature_4h: FeatureResult | None = None
    ) -> CandidateResult:
        cfgv = self._cfg.version_tag
        snapshots_4h = feature_4h.snapshots if feature_4h is not None else []
        evaluations = [
            self._evaluate(s, snapshots_4h, cfgv) for s in feature_1h.snapshots
        ]
        return CandidateResult(
            evaluations=evaluations,
            strategy_version=STRATEGY_VERSION,
            config_version=cfgv,
        )
