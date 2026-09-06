"""ShadowEngine — real-time decision pipeline with ZERO execution (Phase 8).

Runs the *exact, unmodified* P1→P6 decision pipeline for ONE boundary/symbol and
returns a ``ShadowResult``. It mirrors the P6 ``TradingEngine`` ordering but stops
before any execution mutation:

    market data → warm-up gate → usability → features → regime(audit) → candidate
    → news → analyst → sizing (FLAT hypothetical account) → RiskManager (FINAL
    AUTHORITY) → [APPROVE] hypothetical fill (PURE PaperBroker.simulate)

Hard invariants (Master Plan §0.1-4 / plan §3/§9/§15):

* This module imports **no** ``ledger`` / ``PortfolioStore`` writer / operational
  persistence / the P6 ``TradingEngine``. There is no reachable execution path.
* The account is a **flat per-boundary hypothetical** (config starting equity,
  zero open positions) — no evolving book (that is P9).
* The would-be fill uses the *pure* ``PaperBroker.simulate`` (returns a value,
  mutates nothing); it is recorded as HYPOTHETICAL only.
* Kill-switch mutation, persistence, and failure counting live in the RUNNER, not
  here — the engine neither trips the kill switch nor writes rows.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.ai.analyst import ClaudeAnalyst
from app.ai.models import AnalystAction
from app.costs.slippage import slippage_pct as cost_slippage_pct
from app.exceptions import AdapterError, UnsupportedMarketError
from app.execution.models import Intent, OrderSide, OrderState, OrderType
from app.execution.paper_broker import PaperBroker, make_intent_id
from app.indicators.config import IndicatorConfig
from app.indicators.features import FeatureBuilder
from app.market_data.models import Symbol
from app.market_data.service import MarketDataService
from app.portfolio.models import AccountState
from app.regime.classifier import RegimeClassifier
from app.risk.kill_switch import KillSwitchState, KillSwitchStatus
from app.risk.manager import RiskManager
from app.risk.models import MarketState, RiskDecision
from app.shadow.config import ShadowConfig
from app.shadow.models import ShadowOutcome, ShadowResult
from app.sizing.models import SizingDecision
from app.sizing.sizer import PositionSizer
from app.strategy.config import STRATEGY_VERSION
from app.strategy.generator import CandidateGenerator
from app.strategy.models import SignalDecision


class ShadowEngine:
    def __init__(
        self,
        *,
        market_service: MarketDataService,
        market_adapter,
        news_service,
        analyst: ClaudeAnalyst,
        feature_builder: FeatureBuilder,
        candidate_generator: CandidateGenerator,
        sizer: PositionSizer,
        risk_manager: RiskManager,
        paper_broker: PaperBroker,
        regime_classifier: RegimeClassifier,
        shadow_config: ShadowConfig,
        indicator_config: IndicatorConfig,
        cost_config,
        cost_scenario,
        require_confirm_warmup: bool,
    ) -> None:
        self._mds = market_service
        self._adapter = market_adapter
        self._news = news_service
        self._analyst = analyst
        self._fb = feature_builder
        self._gen = candidate_generator
        self._sizer = sizer
        self._risk = risk_manager
        self._broker = paper_broker
        self._regime = regime_classifier
        self._shadow = shadow_config
        self._cost = cost_config
        self._scenario = cost_scenario
        self._warmup_min = shadow_config.warmup_min(indicator_config.min_history)
        self._require_confirm_warmup = require_confirm_warmup
        self._ind_version = indicator_config.version_tag

    # --- helpers --------------------------------------------------------
    def _flat_account(self) -> AccountState:
        eq = self._shadow.starting_equity
        return AccountState(
            cash=eq,
            open_positions=(),
            realized_pnl_cum=Decimal(0),
            fees_paid_cum=Decimal(0),
            hwm_equity=eq,
        )

    def _result(
        self, outcome: ShadowOutcome, stage: str, reason: str, symbol: Symbol,
        decision_time: datetime, **kw,
    ) -> ShadowResult:
        return ShadowResult(
            outcome=outcome, stage=stage, reason=reason, symbol=symbol,
            decision_time=decision_time, indicator_set_version=self._ind_version,
            strategy_version=STRATEGY_VERSION, **kw,
        )

    # --- main boundary --------------------------------------------------
    def process_boundary(
        self,
        *,
        decision_time: datetime,
        now: datetime,
        symbol: Symbol,
        kill_state: KillSwitchState,
    ) -> ShadowResult:
        R = lambda o, st, rs, **kw: self._result(o, st, rs, symbol, decision_time, **kw)  # noqa: E731

        # Time-integrity: audit/ingestion time cannot precede the decision moment.
        if now < decision_time:
            return R(ShadowOutcome.HOLD, "time_integrity", "now_before_decision_time")

        # Kill switch — flat account: no carried positions, so no exit processing.
        if kill_state.status is KillSwitchStatus.HALTED:
            return R(ShadowOutcome.KILL_HALTED, "kill", "halted")
        if kill_state.status is KillSwitchStatus.PAUSED:
            return R(ShadowOutcome.KILL_PAUSED, "kill", "paused")

        # Market snapshot (P1 remains the validation authority). Adapter/infra
        # failure → DATA_FAILURE (the runner counts it; it is NOT a decision row).
        try:
            md1 = self._mds.get_candles(
                self._adapter, symbol, self._shadow.primary_timeframe,
                now=decision_time, persist=True,
            )
            md4 = self._mds.get_candles(
                self._adapter, symbol, self._shadow.confirm_timeframe,
                now=decision_time, persist=True,
            )
        except (AdapterError, UnsupportedMarketError) as exc:
            return R(ShadowOutcome.DATA_FAILURE, "market_data", type(exc).__name__)

        # Warm-up sufficiency (§6.1): require IndicatorConfig.min_history + buffer
        # usable CLOSED candles; else fail closed (never misleading indicators).
        market_summary = {
            "candle_count_1h": str(len(md1.candles)),
            "candle_count_4h": str(len(md4.candles)),
            "warmup_min": str(self._warmup_min),
            "usable": str(md1.result.usable),
            "stale": str(md1.result.quality.stale),
        }
        if len(md1.candles) < self._warmup_min:
            return R(ShadowOutcome.HOLD, "warmup", "insufficient_history",
                     market_summary=market_summary)
        if self._require_confirm_warmup and len(md4.candles) < self._warmup_min:
            return R(ShadowOutcome.HOLD, "warmup", "insufficient_history_4h",
                     market_summary=market_summary)

        f1 = self._fb.build(md1)
        f4 = self._fb.build(md4)

        spread = self._cost.spread_fallback_pct
        slippage = cost_slippage_pct(self._cost, self._scenario)
        last_close = md1.candles[-1].close if md1.candles else Decimal(0)
        atr_pct = f1.snapshots[-1].atr_pct if f1.snapshots else None
        market = MarketState(
            symbol=symbol, decision_time=decision_time, last_close=last_close,
            atr_pct=atr_pct, spread_pct=spread, slippage_pct=slippage,
            usable=md1.result.usable, stale=md1.result.quality.stale,
        )
        market_summary.update(
            last_close=str(last_close), atr_pct=str(atr_pct),
            spread_pct=str(spread), slippage_pct=str(slippage),
        )

        # Regime (descriptive audit only — never a trading signal).
        regime = None
        features_summary: dict[str, str] = {}
        if f1.snapshots:
            s = f1.snapshots[-1]
            features_summary = {
                "close": str(s.close), "ema_short": str(s.ema_short),
                "ema_long": str(s.ema_long), "rsi": str(s.rsi),
                "atr": str(s.atr), "atr_pct": str(s.atr_pct), "warm": str(s.warm),
            }
            reg = self._regime.classify(f1, f4)
            if reg.snapshots:
                rs = reg.snapshots[-1]
                regime = f"{rs.trend.value}/{rs.volatility.value}"

        common = dict(market_summary=market_summary, features_summary=features_summary,
                      regime=regime)

        # Fail-safe: unusable/stale market data → HOLD.
        if not market.usable or market.stale:
            return R(ShadowOutcome.HOLD, "market", "unusable_or_stale", **common)

        # Candidate (embeds the P3 cost gate + reward:risk).
        cand_result = self._gen.generate(f1, f4)
        if not cand_result.evaluations:
            return R(ShadowOutcome.HOLD, "candidate", "no_evaluation", **common)
        evaluation = cand_result.evaluations[-1]
        if evaluation.decision is not SignalDecision.CANDIDATE or evaluation.candidate is None:
            return R(ShadowOutcome.HOLD, "candidate", evaluation.reason.value, **common)
        candidate = evaluation.candidate

        # News + Claude (real forward-only). Any non-PROCEED → HOLD.
        news = self._news.build_context(decision_time=decision_time, now=now)
        verdict = self._analyst.analyze(candidate, news, decision_time=decision_time)
        if verdict.action is not AnalystAction.PROCEED:
            return R(ShadowOutcome.HOLD, "analyst", verdict.failure.value,
                     news_items=news.items, verdict=verdict, **common)

        # FLAT hypothetical account (no evolving book — that is P9).
        account = self._flat_account()
        equity = account.equity({str(symbol): market.last_close})
        sizing = self._sizer.plan(candidate, account_equity=equity, current_exposures={})
        if sizing.decision is not SizingDecision.SIZED or sizing.plan is None:
            return R(ShadowOutcome.HOLD, "sizing", sizing.reason.value,
                     news_items=news.items, verdict=verdict, **common)

        assessment = self._risk.evaluate(
            candidate=candidate, plan=sizing.plan, verdict=verdict, account=account,
            market=market, kill_state=kill_state,
            day_baseline_equity=self._shadow.starting_equity,
            week_baseline_equity=self._shadow.starting_equity,
            decision_time=decision_time,
        )
        if assessment.decision is not RiskDecision.APPROVE:
            outcome = (
                ShadowOutcome.REJECT
                if assessment.decision is RiskDecision.REJECT
                else ShadowOutcome.HOLD
            )
            return R(outcome, "risk", assessment.reason.value,
                     news_items=news.items, verdict=verdict, risk_assessment=assessment,
                     **common)

        # APPROVE → HYPOTHETICAL order + PURE fill (mutates nothing; never persisted
        # to paper_orders/paper_fills; never applied to a ledger).
        plan = sizing.plan
        intent = Intent(
            intent_id=make_intent_id(
                decision_time=decision_time, symbol=symbol, side=OrderSide.BUY,
                order_type=OrderType.MARKET, tag=f"shadow:{candidate.strategy_version}",
            ),
            symbol=symbol, side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=plan.quantity, reference_price=plan.entry_ref, decision_time=decision_time,
        )
        exec_result = self._broker.simulate(
            intent, spread_pct=market.spread_pct, slippage_pct=market.slippage_pct
        )
        hyp_order = dict(
            hyp_side=OrderSide.BUY.value, hyp_quantity=plan.quantity,
            hyp_entry_ref=plan.entry_ref, hyp_stop_price=plan.stop_price,
            hyp_target_price=Decimal(str(candidate.target_price)),
            hyp_fill_state=exec_result.state.value,
        )
        # A rejected/empty hypothetical fill is a HOLD (mirrors P6); a real
        # (FILLED/PARTIAL) hypothetical fill is a WOULD_TRADE — never an execution.
        if exec_result.state in (OrderState.REJECTED, OrderState.UNKNOWN) or not exec_result.fills:
            return R(ShadowOutcome.HOLD, "execution", exec_result.reason.value,
                     news_items=news.items, verdict=verdict, risk_assessment=assessment,
                     **hyp_order, **common)
        fill = exec_result.fills[0]
        return R(
            ShadowOutcome.WOULD_TRADE, "execution", exec_result.reason.value,
            news_items=news.items, verdict=verdict, risk_assessment=assessment,
            hyp_fill_price=fill.fill_price, hyp_fill_fee=fill.fee,
            **hyp_order, **common,
        )
