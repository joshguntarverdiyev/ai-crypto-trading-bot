"""TradingEngine — deterministic P4→P5→P6 tick orchestration (Phase 6).

`process_tick(decision_time, now, symbol)` runs the full pipeline once, fail-closed
at every stage, with the RiskManager as the sole gate to (paper) execution. No
live path exists. Ordering (Master Plan §D):

    market data → usability → features → candidate (embeds cost gate) → news →
    analyst → sizing (authoritative equity) → RiskManager (FINAL AUTHORITY) →
    plan validation → paper execution → portfolio update → atomic persistence

Open positions are checked for stop/target exits first (exits run even while
PAUSED; new entries do not). Time is injected (H3/§10). Kill-switch HALT/PAUSE is
honored and persisted independently (H9).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.ai.analyst import ClaudeAnalyst
from app.ai.models import AnalystAction
from app.costs.slippage import slippage_pct as cost_slippage_pct
from app.engine.recorder import TickRecorder
from app.execution.models import ExecutionResult, Intent, OrderSide, OrderState, OrderType
from app.execution.paper_broker import PaperBroker, make_intent_id
from app.execution.repository import PaperExecutionRepository
from app.execution.stops import compute_exit_intent
from app.indicators.features import FeatureBuilder
from app.market_data.models import Symbol, Timeframe
from app.market_data.service import MarketDataService
from app.portfolio import ledger
from app.portfolio.store import PortfolioStore, day_start, week_start
from app.risk.kill_switch import KillSwitch, KillSwitchStatus
from app.risk.manager import RiskManager
from app.risk.models import MarketState, RiskDecision, RiskReason
from app.sizing.models import SizingDecision
from app.sizing.sizer import PositionSizer
from app.strategy.generator import CandidateGenerator
from app.strategy.models import SignalDecision

# Risk reasons that trip the kill switch (rather than a plain per-tick HOLD).
_HALT_REASONS = frozenset(
    {RiskReason.DAILY_LOSS_LIMIT, RiskReason.WEEKLY_LOSS_LIMIT, RiskReason.DRAWDOWN_LIMIT}
)
_PAUSE_REASONS = frozenset({RiskReason.ABNORMAL_SPREAD, RiskReason.ABNORMAL_SLIPPAGE})


class TickOutcome(StrEnum):
    TRADE = "trade"  # entry executed
    EXIT = "exit"  # stop/target exit executed
    HOLD = "hold"
    REJECT = "reject"
    KILL_PAUSED = "kill_paused"
    KILL_HALTED = "kill_halted"
    ERROR = "error"  # persistence/unexpected failure → HALT


@dataclass(frozen=True)
class TickResult:
    outcome: TickOutcome
    stage: str
    reason: str
    symbol: Symbol | None = None


class TradingEngine:
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
        portfolio_store: PortfolioStore,
        kill_switch: KillSwitch,
        recorder: TickRecorder,
        exec_repo: PaperExecutionRepository,
        cost_config,
        cost_scenario,
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
        self._pf = portfolio_store
        self._kill = kill_switch
        self._rec = recorder
        self._exec = exec_repo
        self._cost = cost_config
        self._scenario = cost_scenario

    # --- market snapshot -------------------------------------------------
    def _market(self, symbol: Symbol, *, decision_time: datetime):
        # H58 (look-ahead protection): business-time eligibility (candle
        # closed-ness AND staleness) is evaluated as-of DECISION_TIME, never the
        # ingestion wall-clock `now`. A candle that closes after decision_time is
        # not available to the decision.
        md1 = self._mds.get_candles(self._adapter, symbol, Timeframe.H1, now=decision_time)
        md4 = self._mds.get_candles(self._adapter, symbol, Timeframe.H4, now=decision_time)
        f1 = self._fb.build(md1)
        f4 = self._fb.build(md4)
        spread = self._cost.spread_fallback_pct
        slippage = cost_slippage_pct(self._cost, self._scenario)
        last_close = md1.candles[-1].close if md1.candles else Decimal(0)
        atr_pct = f1.snapshots[-1].atr_pct if f1.snapshots else None
        state = MarketState(
            symbol=symbol, decision_time=decision_time, last_close=last_close,
            atr_pct=atr_pct, spread_pct=spread, slippage_pct=slippage,
            usable=md1.result.usable, stale=md1.result.quality.stale,
        )
        return state, md1, f1, f4

    # --- multi-symbol marks (P9 OD-2; default None ⇒ frozen single-symbol behavior)
    @staticmethod
    def _marks_for(
        symbol: Symbol, own_mark: Decimal, marks: Mapping[str, Decimal] | None
    ) -> dict[str, Decimal]:
        """Marks for equity valuation.

        With ``marks=None`` this returns ``{str(symbol): own_mark}`` — byte-identical
        to the frozen P6 single-symbol behavior. With P9 full marks provided, all open
        symbols are valued at their decision-time closes; the current symbol's own
        decision-time close (``own_mark``) always takes precedence for consistency.
        """
        if not marks:
            return {str(symbol): own_mark}
        return {**marks, str(symbol): own_mark}

    # --- exits (run even while PAUSED; and while HALTED via run_protective_exits) ---
    def _try_exit(
        self,
        symbol: Symbol,
        md1,
        *,
        decision_time: datetime,
        now: datetime,
        marks: Mapping[str, Decimal] | None = None,
    ) -> TickResult | None:
        account = self._pf.load_account()
        position = account.position_for(symbol)
        if position is None or not md1.candles:
            return None
        candle = md1.candles[-1]
        intent = compute_exit_intent(position, candle, decision_time=decision_time)
        if intent is None:
            return None
        if self._exec.find_order_state(intent.intent_id) is not None:
            return TickResult(TickOutcome.EXIT, "exit", "duplicate_intent", symbol)
        result = self._broker.simulate(
            intent, spread_pct=self._cost.spread_fallback_pct,
            slippage_pct=cost_slippage_pct(self._cost, self._scenario),
        )
        if not result.fills:
            return TickResult(TickOutcome.HOLD, "exit", result.reason.value, symbol)
        fill = result.fills[0]
        new_account, affected = ledger.apply_exit(
            account, symbol=symbol, exit_qty=fill.fill_qty,
            fill_price=fill.fill_price, fee=fill.fee, at=now,
        )
        marks_after = self._marks_for(symbol, candle.close, marks)
        equity = new_account.equity(marks_after)
        new_account = ledger.with_hwm(new_account, equity)
        self._persist(
            decision_time=decision_time, now=now, symbol=symbol, intent=intent,
            exec_result=result, affected_position=affected, account_after=new_account,
            equity=equity, unrealized=new_account.unrealized_pnl(marks_after),
        )
        return TickResult(TickOutcome.EXIT, "exit", intent.order_type.value, symbol)

    # --- protective exits while HALTED (P9 OD-1) -------------------------
    def run_protective_exits(
        self,
        *,
        decision_time: datetime,
        now: datetime,
        symbol: Symbol,
        marks: Mapping[str, Decimal] | None = None,
    ) -> TickResult:
        """Run ONLY stop/target exits for ``symbol`` regardless of kill state.

        Additive P9 entry point (OD-1): the P9 runner routes to this while the kill
        switch is HALTED so protective exits keep firing (a HALT must never leave an
        open paper position unmanaged), while **new entries are never created**. It
        reuses the exact frozen ``_try_exit`` path — no duplication, no reordering —
        and does not touch ``process_tick``'s behavior. On market-data failure it
        HALTs (already-HALTED is a no-op) and returns ERROR; a persistence failure in
        the exit path rolls back atomically (no phantom fill) and re-raises.
        """
        if now < decision_time:
            return TickResult(
                TickOutcome.HOLD, "time_integrity", "now_before_decision_time", symbol
            )
        try:
            _market, md1, _f1, _f4 = self._market(symbol, decision_time=decision_time)
        except Exception:
            self._kill.halt("market_data_failure", now)
            return TickResult(TickOutcome.ERROR, "market_data", "halted", symbol)
        result = self._try_exit(symbol, md1, decision_time=decision_time, now=now, marks=marks)
        if result is not None:
            return result
        return TickResult(TickOutcome.HOLD, "protective_exit", "no_exit", symbol)

    def _persist(self, *, now: datetime, **kw) -> None:
        try:
            self._rec.record_tick(now=now, **kw)
        except Exception:  # H9: persistence failure → HALT (independent session)
            self._kill.halt("persistence_failure", now)
            raise

    # --- main tick -------------------------------------------------------
    def process_tick(
        self,
        *,
        decision_time: datetime,
        now: datetime,
        symbol: Symbol,
        marks: Mapping[str, Decimal] | None = None,
    ) -> TickResult:
        # H58 invariant: audit/ingestion time cannot precede the decision moment.
        # Violation is a caller/time-integrity error → fail closed (no trade).
        #
        # ``marks`` (P9 OD-2) is an OPTIONAL full symbol→decision-time-close map so
        # equity/unrealized/HWM/drawdown and the RiskManager's drawdown/daily/weekly
        # checks value the WHOLE book. When ``marks=None`` the behavior is
        # byte-identical to the frozen P6 single-symbol valuation.
        if now < decision_time:
            return TickResult(
                TickOutcome.HOLD, "time_integrity", "now_before_decision_time", symbol
            )

        kill = self._kill.current()
        if kill.status is KillSwitchStatus.HALTED:
            return TickResult(TickOutcome.KILL_HALTED, "kill", "halted", symbol)

        try:
            market, md1, f1, f4 = self._market(symbol, decision_time=decision_time)
        except Exception:
            self._kill.halt("market_data_failure", now)
            return TickResult(TickOutcome.ERROR, "market_data", "halted", symbol)

        # Exits first (honored during PAUSE too).
        exit_result = self._try_exit(symbol, md1, decision_time=decision_time, now=now, marks=marks)
        if exit_result is not None:
            return exit_result

        if kill.status is KillSwitchStatus.PAUSED:
            return TickResult(TickOutcome.KILL_PAUSED, "kill", "paused", symbol)

        # Fail-safe: unusable/stale market data → HOLD.
        if not market.usable or market.stale:
            return TickResult(TickOutcome.HOLD, "market", "unusable_or_stale", symbol)

        # Candidate (embeds P3 cost gate + reward:risk).
        cand_result = self._gen.generate(f1, f4)
        if not cand_result.evaluations:
            return TickResult(TickOutcome.HOLD, "candidate", "no_evaluation", symbol)
        evaluation = cand_result.evaluations[-1]
        if evaluation.decision is not SignalDecision.CANDIDATE or evaluation.candidate is None:
            return TickResult(TickOutcome.HOLD, "candidate", evaluation.reason.value, symbol)
        candidate = evaluation.candidate

        news = self._news.build_context(decision_time=decision_time, now=now)
        verdict = self._analyst.analyze(candidate, news, decision_time=decision_time)
        if verdict.action is not AnalystAction.PROCEED:
            self._persist(
                decision_time=decision_time, now=now, symbol=symbol,
                news_items=news.items, verdict=verdict,
            )
            return TickResult(TickOutcome.HOLD, "analyst", verdict.failure.value, symbol)

        account = self._pf.load_account()
        marks_now = self._marks_for(symbol, market.last_close, marks)
        equity = account.equity(marks_now)
        sizing = self._sizer.plan(
            candidate, account_equity=equity, current_exposures=account.exposure_by_symbol()
        )
        if sizing.decision is not SizingDecision.SIZED or sizing.plan is None:
            self._persist(
                decision_time=decision_time, now=now, symbol=symbol,
                news_items=news.items, verdict=verdict,
            )
            return TickResult(TickOutcome.HOLD, "sizing", sizing.reason.value, symbol)

        assessment = self._risk.evaluate(
            candidate=candidate, plan=sizing.plan, verdict=verdict, account=account,
            market=market, kill_state=kill,
            day_baseline_equity=self._pf.baseline_equity(day_start(decision_time)),
            week_baseline_equity=self._pf.baseline_equity(week_start(decision_time)),
            decision_time=decision_time,
        )
        if assessment.decision is not RiskDecision.APPROVE:
            self._persist(
                decision_time=decision_time, now=now, symbol=symbol,
                news_items=news.items, verdict=verdict, risk_assessment=assessment,
            )
            if assessment.reason in _HALT_REASONS:
                self._kill.halt(assessment.reason.value, now)
            elif assessment.reason in _PAUSE_REASONS:
                self._kill.pause(assessment.reason.value, now)
            outcome = (
                TickOutcome.REJECT
                if assessment.decision is RiskDecision.REJECT
                else TickOutcome.HOLD
            )
            return TickResult(outcome, "risk", assessment.reason.value, symbol)

        # APPROVE → paper entry (idempotent, reconcile-before-retry).
        plan = sizing.plan
        intent = Intent(
            intent_id=make_intent_id(
                decision_time=decision_time, symbol=symbol, side=OrderSide.BUY,
                order_type=OrderType.MARKET, tag=candidate.strategy_version,
            ),
            symbol=symbol, side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=plan.quantity, reference_price=plan.entry_ref, decision_time=decision_time,
        )
        if self._exec.find_order_state(intent.intent_id) is not None:
            return TickResult(TickOutcome.TRADE, "execution", "duplicate_intent", symbol)

        result: ExecutionResult = self._broker.simulate(
            intent, spread_pct=market.spread_pct, slippage_pct=market.slippage_pct
        )
        if result.state in (OrderState.REJECTED, OrderState.UNKNOWN) or not result.fills:
            self._persist(
                decision_time=decision_time, now=now, symbol=symbol, news_items=news.items,
                verdict=verdict, risk_assessment=assessment, intent=intent, exec_result=result,
            )
            return TickResult(TickOutcome.HOLD, "execution", result.reason.value, symbol)

        fill = result.fills[0]
        new_account, affected = ledger.apply_entry(
            account, symbol=symbol, direction=candidate.direction,
            fill_qty=fill.fill_qty, fill_price=fill.fill_price, fee=fill.fee,
            stop_price=plan.stop_price, target_price=Decimal(str(candidate.target_price)),
            strategy_version=candidate.strategy_version, at=now,
        )
        equity_after = new_account.equity(marks_now)
        new_account = ledger.with_hwm(new_account, equity_after)
        self._persist(
            decision_time=decision_time, now=now, symbol=symbol, news_items=news.items,
            verdict=verdict, risk_assessment=assessment, intent=intent, exec_result=result,
            affected_position=affected, account_after=new_account, equity=equity_after,
            unrealized=new_account.unrealized_pnl(marks_now),
        )
        return TickResult(TickOutcome.TRADE, "execution", "filled", symbol)
