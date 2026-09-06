"""Backtest engine — deterministic global multi-symbol replay (Phase 7).

ONE global chronological event loop across all symbols, ordered by
``(decision_time, canonical_symbol_rank)`` where rank is the index in
``sorted(symbols, key=str)`` (input-order-independent). A single shared in-memory
``AccountState`` spans all symbols. Each boundary runs two ordered phases —
(1) exits + scheduled entry fills, then (2) decisions — so every symbol observes a
deterministic shared state. Same-boundary approved entries are reserved against a
``provisional`` account (via the frozen ``ledger.apply_entry``) so correlated /
total / cash caps cannot be breached by two same-timestamp signals (plan §9.1).

The engine REUSES the unmodified P2→P6 pure contracts (FeatureBuilder →
CandidateGenerator[+CostManager] → PositionSizer → RiskManager → PaperBroker →
stops → ledger). It writes NO operational tables, instantiates NO real
KillSwitch/DB, and does NOT import the P6 runtime engine or the news/Claude
runtime. The advisory veto is excluded (Master Plan §8): the RiskManager is fed a
STRUCTURAL SENTINEL verdict (never persisted; unmistakable sentinel model_id) —
because the veto is HOLD-only, the pure-quant result is an upper bound on trade
frequency (plan §21). No optimizer / no edge claim.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from app.ai.models import AnalystAction, AnalystFailure, AnalystVerdict
from app.costs.config import CostConfig, CostScenario
from app.execution.config import PaperConfig
from app.execution.models import Intent, OrderSide, OrderState, OrderType
from app.execution.paper_broker import PaperBroker, make_intent_id
from app.execution.stops import compute_exit_intent
from app.indicators.config import INDICATOR_SET_VERSION, IndicatorConfig
from app.indicators.features import FeatureBuilder
from app.market_data.models import Candle, Symbol, Timeframe
from app.portfolio import ledger
from app.portfolio.models import AccountState, Position
from app.portfolio.store import day_start, week_start
from app.risk.config import RiskConfig
from app.risk.kill_switch import KillSwitchState, KillSwitchStatus
from app.risk.manager import RiskManager
from app.risk.models import MarketState, RiskDecision, RiskReason
from app.sizing.config import SizingConfig
from app.sizing.models import PositionPlan, SizingDecision
from app.sizing.sizer import PositionSizer
from app.strategy.config import StrategyConfig
from app.strategy.generator import CandidateGenerator
from app.strategy.models import Candidate, SignalDecision
from app.time_utils import utc_now
from backtesting.config import BacktestConfig, EntryFillRule, HaltPolicy
from backtesting.costs import scenario_market_costs
from backtesting.dataset import Dataset
from backtesting.models import (
    BacktestEvent,
    BacktestResult,
    BacktestTrade,
    EquityPoint,
    RunManifest,
)
from backtesting.version import BACKTEST_ENGINE_VERSION

# Sentinel identity for the excluded advisory veto (§21). Unmistakable; never
# persisted as a real Claude decision.
_SENTINEL_MODEL_ID = "__backtest_quant_only__"
_SENTINEL_MODEL_CLASS = "__none__"

_HALT_REASONS = frozenset(
    {RiskReason.DAILY_LOSS_LIMIT, RiskReason.WEEKLY_LOSS_LIMIT, RiskReason.DRAWDOWN_LIMIT}
)
_PAUSE_REASONS = frozenset({RiskReason.ABNORMAL_SPREAD, RiskReason.ABNORMAL_SLIPPAGE})


def sentinel_verdict(decision_time: datetime) -> AnalystVerdict:
    """A structural PROCEED verdict for the pure-quant backtest (never persisted).

    The RiskManager requires ``verdict.action is PROCEED``; the pure-quant
    backtest excludes the advisory Claude veto (§8). This carries an unmistakable
    sentinel ``model_id`` so no artifact can be mistaken for a real Claude
    decision.
    """
    return AnalystVerdict(
        decision=None,
        action=AnalystAction.PROCEED,
        confidence=None,
        reason_codes=(),
        affected_assets=(),
        event_risk=None,
        evidence=(),
        failure=AnalystFailure.OK,
        model_class=_SENTINEL_MODEL_CLASS,
        model_id=_SENTINEL_MODEL_ID,
        prompt_version="__none__",
        ai_analyst_version="__none__",
        news_pipeline_version=None,
        decision_time=decision_time,
        processed_at=decision_time,
        latency_seconds=0.0,
    )


@dataclass
class _ScheduledEntry:
    fill_boundary: datetime
    reference_price: Decimal
    plan: PositionPlan
    candidate: Candidate
    decision_time: datetime


@dataclass
class _OpenTrade:
    entry_time: datetime
    entry_price: Decimal
    quantity: Decimal
    entry_fee: Decimal


@dataclass
class _SymbolSeries:
    symbol: Symbol
    candles_1h: list[Candle]
    by_close: dict[datetime, int]  # close_time -> index
    evaluations: list  # SignalEvaluation aligned 1:1 with candles_1h
    snapshots: list  # FeatureSnapshot aligned 1:1 with candles_1h


class _BaselineTracker:
    """In-memory carry-forward equity baselines (mirrors PortfolioStore semantics)."""

    def __init__(self, starting_equity: Decimal) -> None:
        self._start = starting_equity
        self._points: list[tuple[datetime, Decimal]] = []

    def record(self, at: datetime, equity: Decimal) -> None:
        self._points.append((at, equity))

    def baseline(self, period_start: datetime) -> Decimal:
        best: Decimal | None = None
        for t, eq in self._points:
            if t < period_start:
                best = eq  # points are appended in ascending time order
            else:
                break
        return best if best is not None else self._start


def _build_symbol_series(
    dataset: Dataset,
    symbol: Symbol,
    *,
    feature_builder: FeatureBuilder,
    generator: CandidateGenerator,
) -> _SymbolSeries | None:
    candles_1h = dataset.candles(symbol, Timeframe.H1)
    if not candles_1h:
        return None
    md1 = dataset.market_result(symbol, Timeframe.H1)
    md4 = dataset.market_result(symbol, Timeframe.H4)
    feat_1h = feature_builder.build(md1)
    feat_4h = feature_builder.build(md4)
    cand = generator.generate(feat_1h, feat_4h)
    # Feature/candidate causality: snapshots[i]/evaluations[i] use only candles
    # with close_time <= candles_1h[i].close_time (P2 causal recursions +
    # causal governing_4h). Alignment is 1:1 with candles_1h.
    if len(feat_1h.snapshots) != len(candles_1h) or len(cand.evaluations) != len(candles_1h):
        # Non-contiguous/uncomputed series: treated as no signals (fail-safe HOLD).
        return _SymbolSeries(
            symbol=symbol,
            candles_1h=candles_1h,
            by_close={c.close_time: i for i, c in enumerate(candles_1h)},
            evaluations=[None] * len(candles_1h),
            snapshots=[None] * len(candles_1h),
        )
    return _SymbolSeries(
        symbol=symbol,
        candles_1h=candles_1h,
        by_close={c.close_time: i for i, c in enumerate(candles_1h)},
        evaluations=list(cand.evaluations),
        snapshots=list(feat_1h.snapshots),
    )


def run_backtest(
    dataset: Dataset,
    *,
    backtest_config: BacktestConfig,
    indicator_config: IndicatorConfig,
    strategy_config: StrategyConfig,
    cost_config: CostConfig,
    sizing_config: SizingConfig,
    risk_config: RiskConfig,
    paper_config: PaperConfig,
    symbols: list[Symbol] | None = None,
    run_time: datetime | None = None,
) -> BacktestResult:
    """Run a deterministic pure-quant backtest over ``dataset`` (offline)."""
    scenario: CostScenario = backtest_config.cost_scenario
    # Force the strategy's cost gate to the backtest scenario so the gate and the
    # fill use the SAME scenario (no divergence, no new cost math).
    eff_strategy = replace(strategy_config, cost_scenario=scenario)
    from app.costs.manager import CostManager  # local import: pure P3 reuse

    feature_builder = FeatureBuilder(indicator_config)
    generator = CandidateGenerator(eff_strategy, CostManager(cost_config))
    sizer = PositionSizer(sizing_config)
    risk = RiskManager(risk_config)
    broker = PaperBroker(paper_config)
    spread_pct, slippage_pct = scenario_market_costs(cost_config, scenario)

    # Canonical, input-order-independent symbol ordering (§9.1).
    present = [s for s in dataset.symbols]  # symbol strings actually in the dataset
    requested = {str(s) for s in symbols} if symbols is not None else None
    canonical = sorted(
        (Symbol.parse(s) for s in present if requested is None or s in requested),
        key=str,
    )

    series: dict[str, _SymbolSeries] = {}
    for sym in canonical:
        built = _build_symbol_series(
            dataset, sym, feature_builder=feature_builder, generator=generator
        )
        if built is not None:
            series[str(sym)] = built
    canonical = [s for s in canonical if str(s) in series]

    # Global boundary set: union of all 1h close_times, ascending.
    boundaries = sorted(
        {c.close_time for s in series.values() for c in s.candles_1h}
    )

    starting_equity = backtest_config.starting_equity
    account = AccountState(
        cash=starting_equity,
        open_positions=(),
        realized_pnl_cum=Decimal(0),
        fees_paid_cum=Decimal(0),
        hwm_equity=starting_equity,
    )
    baselines = _BaselineTracker(starting_equity)
    scheduled: dict[str, _ScheduledEntry] = {}
    open_trades: dict[str, _OpenTrade] = {}
    seen_intents: set[str] = set()
    trades: list[BacktestTrade] = []
    equity_curve: list[EquityPoint] = []
    events: list[BacktestEvent] = []
    kill_status = KillSwitchStatus.RUNNING
    halted_day: datetime | None = None

    fee_rate = Decimal(str(paper_config.taker_fee_pct))

    def boundary_marks(t: datetime) -> dict[str, Decimal]:
        marks: dict[str, Decimal] = {}
        for sym_str, s in series.items():
            idx = s.by_close.get(t)
            if idx is not None:
                marks[sym_str] = s.candles_1h[idx].close
        return marks

    for t in boundaries:
        # reset_next_period: resume at the next UTC day after a HALT.
        if (
            kill_status is KillSwitchStatus.HALTED
            and backtest_config.halt_policy is HaltPolicy.RESET_NEXT_PERIOD
            and halted_day is not None
            and day_start(t) > halted_day
        ):
            kill_status = KillSwitchStatus.RUNNING
            halted_day = None
            events.append(BacktestEvent(t, "kill_reset", None, "reset_next_period"))

        # A HALT freezes paper state (matches the P6 paper policy): skip exits and
        # decisions while HALTED. With end_run we stop the whole replay.
        if kill_status is KillSwitchStatus.HALTED:
            if backtest_config.halt_policy is HaltPolicy.END_RUN:
                break
            # reset policy: still record an equity point (state frozen).
            marks = boundary_marks(t)
            eq = account.equity(marks)
            account = ledger.with_hwm(account, eq)
            equity_curve.append(EquityPoint(t, eq, account.cash, account.open_count()))
            baselines.record(t, eq)
            continue

        # ---- Phase 1a: EXITS (canonical order; run even while PAUSED) ----
        for sym in canonical:
            sym_str = str(sym)
            position = account.position_for(sym)
            if position is None:
                continue
            s = series[sym_str]
            idx = s.by_close.get(t)
            if idx is None:
                continue
            if not position.opened_at < t:  # never exit on the entry bar (§10.3)
                continue
            candle = s.candles_1h[idx]
            intent = compute_exit_intent(position, candle, decision_time=t)
            if intent is None:
                continue
            if intent.intent_id in seen_intents:
                continue
            seen_intents.add(intent.intent_id)
            result = broker.simulate(intent, spread_pct=spread_pct, slippage_pct=slippage_pct)
            if not result.fills:
                events.append(BacktestEvent(t, "exit_no_fill", sym_str, result.reason.value))
                continue
            fill = result.fills[0]
            account, affected = ledger.apply_exit(
                account, symbol=sym, exit_qty=fill.fill_qty,
                fill_price=fill.fill_price, fee=fill.fee, at=t,
            )
            _finalize_trade(
                trades, open_trades, sym_str, position, affected,
                exit_time=t, exit_price=fill.fill_price, exit_fee=fill.fee,
                exit_reason=intent.order_type.value,
            )
            account = ledger.with_hwm(account, account.equity(boundary_marks(t)))

        # ---- Phase 1b: SCHEDULED ENTRY FILLS (only while RUNNING) ----
        if kill_status is KillSwitchStatus.RUNNING:
            for sym in canonical:
                sym_str = str(sym)
                entry = scheduled.get(sym_str)
                if entry is None or entry.fill_boundary != t:
                    continue
                del scheduled[sym_str]
                plan = entry.plan
                intent = Intent(
                    intent_id=make_intent_id(
                        decision_time=entry.decision_time, symbol=sym,
                        side=OrderSide.BUY, order_type=OrderType.MARKET,
                        tag=entry.candidate.strategy_version,
                    ),
                    symbol=sym, side=OrderSide.BUY, order_type=OrderType.MARKET,
                    quantity=plan.quantity, reference_price=entry.reference_price,
                    decision_time=entry.decision_time,
                )
                if intent.intent_id in seen_intents:
                    continue
                seen_intents.add(intent.intent_id)
                result = broker.simulate(
                    intent, spread_pct=spread_pct, slippage_pct=slippage_pct
                )
                if result.state in (OrderState.REJECTED, OrderState.UNKNOWN) or not result.fills:
                    events.append(BacktestEvent(t, "entry_no_fill", sym_str, result.reason.value))
                    continue
                fill = result.fills[0]
                account, _ = ledger.apply_entry(
                    account, symbol=sym, direction=entry.candidate.direction,
                    fill_qty=fill.fill_qty, fill_price=fill.fill_price, fee=fill.fee,
                    stop_price=plan.stop_price,
                    target_price=Decimal(str(entry.candidate.target_price)),
                    strategy_version=entry.candidate.strategy_version, at=t,
                )
                open_trades[sym_str] = _OpenTrade(
                    entry_time=t, entry_price=fill.fill_price,
                    quantity=fill.fill_qty, entry_fee=fill.fee,
                )
                account = ledger.with_hwm(account, account.equity(boundary_marks(t)))
        else:
            # Pause/halt cancels any pending entries (stop-direction; conservative).
            for sym_str, entry in list(scheduled.items()):
                if entry.fill_boundary == t:
                    del scheduled[sym_str]
                    events.append(BacktestEvent(t, "entry_cancelled", sym_str, kill_status.value))

        # ---- Phase 2: DECISIONS (canonical order; only while RUNNING) ----
        if kill_status is KillSwitchStatus.RUNNING:
            provisional = account
            for sym in canonical:
                sym_str = str(sym)
                if account.position_for(sym) is not None or sym_str in scheduled:
                    continue  # one open position + one pending entry per symbol
                s = series[sym_str]
                idx = s.by_close.get(t)
                if idx is None:
                    continue
                evaluation = s.evaluations[idx]
                snapshot = s.snapshots[idx]
                if (
                    evaluation is None
                    or evaluation.decision is not SignalDecision.CANDIDATE
                    or evaluation.candidate is None
                ):
                    continue
                candidate = evaluation.candidate
                if idx + 1 >= len(s.candles_1h):
                    events.append(BacktestEvent(t, "entry_dropped_eod", sym_str, "no_next_bar"))
                    continue
                next_candle = s.candles_1h[idx + 1]
                candle = s.candles_1h[idx]

                market = MarketState(
                    symbol=sym, decision_time=t, last_close=candle.close,
                    atr_pct=snapshot.atr_pct, spread_pct=spread_pct,
                    slippage_pct=slippage_pct, usable=True, stale=False,
                )
                equity = provisional.equity({sym_str: candle.close})
                sizing = sizer.plan(
                    candidate, account_equity=equity,
                    current_exposures=provisional.exposure_by_symbol(),
                )
                if sizing.decision is not SizingDecision.SIZED or sizing.plan is None:
                    events.append(BacktestEvent(t, "sizing_hold", sym_str, sizing.reason.value))
                    continue
                plan = sizing.plan
                assessment = risk.evaluate(
                    candidate=candidate, plan=plan, verdict=sentinel_verdict(t),
                    account=provisional, market=market,
                    kill_state=KillSwitchState(KillSwitchStatus.RUNNING, None, None),
                    day_baseline_equity=baselines.baseline(day_start(t)),
                    week_baseline_equity=baselines.baseline(week_start(t)),
                    decision_time=t,
                )
                if assessment.decision is not RiskDecision.APPROVE:
                    events.append(
                        BacktestEvent(t, f"risk_{assessment.decision.value}", sym_str,
                                      assessment.reason.value)
                    )
                    if assessment.reason in _HALT_REASONS:
                        kill_status = KillSwitchStatus.HALTED
                        halted_day = day_start(t)
                        break
                    if assessment.reason in _PAUSE_REASONS:
                        kill_status = KillSwitchStatus.PAUSED
                        break
                    continue

                # APPROVE → schedule entry for the NEXT boundary (fill rule §10).
                if backtest_config.entry_fill_rule is EntryFillRule.NEXT_OPEN:
                    ref_price = next_candle.open
                else:  # signal_close: bar i close (== plan.entry_ref, tick-rounded)
                    ref_price = plan.entry_ref
                scheduled[sym_str] = _ScheduledEntry(
                    fill_boundary=next_candle.close_time, reference_price=ref_price,
                    plan=plan, candidate=candidate, decision_time=t,
                )
                # Same-boundary reservation: reserve exposure + cash at the
                # decision-time reference (plan.entry_ref), via the frozen ledger.
                est_fee = (plan.quantity * plan.entry_ref) * fee_rate
                provisional, _ = ledger.apply_entry(
                    provisional, symbol=sym, direction=candidate.direction,
                    fill_qty=plan.quantity, fill_price=plan.entry_ref, fee=est_fee,
                    stop_price=plan.stop_price,
                    target_price=Decimal(str(candidate.target_price)),
                    strategy_version=candidate.strategy_version, at=t,
                )

        # ---- Phase 3: equity snapshot ----
        marks = boundary_marks(t)
        eq = account.equity(marks)
        account = ledger.with_hwm(account, eq)
        equity_curve.append(EquityPoint(t, eq, account.cash, account.open_count()))
        baselines.record(t, eq)

        if (
            kill_status is KillSwitchStatus.HALTED
            and backtest_config.halt_policy is HaltPolicy.END_RUN
        ):
            break

    ending_equity = equity_curve[-1].equity if equity_curve else starting_equity
    manifest = _build_manifest(
        dataset, backtest_config=backtest_config, cost_config=cost_config,
        sizing_config=sizing_config, risk_config=risk_config, paper_config=paper_config,
        strategy_config=eff_strategy, symbols=canonical,
        run_time=run_time or utc_now(),
    )
    return BacktestResult(
        manifest=manifest, starting_equity=starting_equity, ending_equity=ending_equity,
        trades=trades, equity_curve=equity_curve, events=events,
        final_kill_status=kill_status.value,
    )


def _finalize_trade(
    trades: list[BacktestTrade],
    open_trades: dict[str, _OpenTrade],
    sym_str: str,
    position_before: Position,
    position_after: Position,
    *,
    exit_time: datetime,
    exit_price: Decimal,
    exit_fee: Decimal,
    exit_reason: str,
) -> None:
    ot = open_trades.pop(sym_str, None)
    if ot is None:
        # Defensive: an exit without a tracked entry (should not happen).
        return
    gross = ot.quantity * (exit_price - ot.entry_price)
    net = gross - ot.entry_fee - exit_fee  # equity-consistent per-trade net
    bars = int((exit_time - ot.entry_time).total_seconds() // Timeframe.H1.seconds)
    trades.append(
        BacktestTrade(
            symbol=sym_str, direction=position_before.direction.value,
            entry_time=ot.entry_time, entry_price=ot.entry_price, quantity=ot.quantity,
            entry_fee=ot.entry_fee, exit_time=exit_time, exit_price=exit_price,
            exit_fee=exit_fee, exit_reason=exit_reason, gross_pnl=gross, net_pnl=net,
            bars_held=bars,
        )
    )


def _build_manifest(
    dataset: Dataset,
    *,
    backtest_config: BacktestConfig,
    cost_config: CostConfig,
    sizing_config: SizingConfig,
    risk_config: RiskConfig,
    paper_config: PaperConfig,
    strategy_config: StrategyConfig,
    symbols: list[Symbol],
    run_time: datetime,
) -> RunManifest:
    return RunManifest(
        dataset_name=dataset.name,
        dataset_hash=dataset.content_hash,
        symbols=tuple(str(s) for s in symbols),
        timeframes=dataset.timeframes,
        range_start=dataset.range_start,
        range_end=dataset.range_end,
        seed=backtest_config.seed,
        cost_scenario=backtest_config.cost_scenario.value,
        entry_fill_rule=backtest_config.entry_fill_rule.value,
        halt_policy=backtest_config.halt_policy.value,
        engine_version=BACKTEST_ENGINE_VERSION,
        indicator_set_version=INDICATOR_SET_VERSION,
        cost_model_version=cost_config.version_tag,
        strategy_version=strategy_config.version_tag,
        sizing_version=sizing_config.version_tag,
        risk_version=risk_config.version_tag,
        paper_version=paper_config.version_tag,
        config_snapshot={
            "backtest": backtest_config.version_tag,
            "indicators": INDICATOR_SET_VERSION,
            "cost": cost_config.version_tag,
            "strategy": strategy_config.version_tag,
            "sizing": sizing_config.version_tag,
            "risk": risk_config.version_tag,
            "paper": paper_config.version_tag,
        },
        run_time=run_time,
    )


__all__ = ["run_backtest", "sentinel_verdict", "BACKTEST_ENGINE_VERSION"]
