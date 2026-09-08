"""RiskManager — deterministic FINAL AUTHORITY (Phase 6).

Rule-based, fail-closed. Consumes a P4 `Candidate` + advisory `PositionPlan`, the
P5 `AnalystVerdict` (advisory PROCEED precondition only), authoritative
`AccountState`, injected `MarketState` (H8), UTC period baselines, and the
kill-switch state. It **independently recomputes** per-trade risk and exposure
from actual plan fields against authoritative state (H6) — P4's numbers are never
trusted. Claude can never relax any limit. APPROVE / HOLD / REJECT.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from app.ai.models import AnalystAction, AnalystVerdict
from app.portfolio.models import AccountState
from app.risk.config import RISK_VERSION, RiskConfig
from app.risk.kill_switch import KillSwitchState, KillSwitchStatus
from app.risk.models import MarketState, RiskAssessment, RiskDecision, RiskReason
from app.sizing.models import PositionPlan
from app.strategy.models import Candidate

_HOLD = frozenset(
    {
        RiskReason.KILL_SWITCH_PAUSED,
        RiskReason.MISSING_CANDIDATE,
        RiskReason.MISSING_PLAN,
        RiskReason.ANALYST_NOT_PROCEED,
        RiskReason.MARKET_STALE,
        RiskReason.MARKET_INVALID,
        RiskReason.NON_FINITE,
        RiskReason.VOLATILITY_SHOCK,
        RiskReason.ABNORMAL_SPREAD,
        RiskReason.ABNORMAL_SLIPPAGE,
    }
)


class RiskManager:
    def __init__(self, config: RiskConfig | None = None) -> None:
        self._cfg = config or RiskConfig()

    def _assess(
        self,
        reason: RiskReason,
        *,
        symbol,
        decision_time: datetime,
        risk_pct: float | None = None,
        exposure_after_pct: float | None = None,
        evaluated: dict[str, str] | None = None,
    ) -> RiskAssessment:
        if reason is RiskReason.OK:
            decision = RiskDecision.APPROVE
        elif reason in _HOLD:
            decision = RiskDecision.HOLD
        else:
            decision = RiskDecision.REJECT
        return RiskAssessment(
            decision=decision,
            reason=reason,
            symbol=symbol,
            recomputed_risk_pct=risk_pct,
            exposure_after_pct=exposure_after_pct,
            evaluated=evaluated or {},
            risk_version=RISK_VERSION,
            config_version=self._cfg.version_tag,
            decision_time=decision_time,
        )

    def evaluate(
        self,
        *,
        candidate: Candidate | None,
        plan: PositionPlan | None,
        verdict: AnalystVerdict | None,
        account: AccountState,
        market: MarketState,
        kill_state: KillSwitchState,
        day_baseline_equity: Decimal,
        week_baseline_equity: Decimal,
        decision_time: datetime,
        marks: Mapping[str, Decimal] | None = None,
    ) -> RiskAssessment:
        # OD-3 (P9 multi-symbol): ``marks`` is an OPTIONAL full symbol→decision-time-
        # close map so the authoritative equity / drawdown / daily-loss / weekly-loss
        # gates value the WHOLE open book (not just the symbol under evaluation).
        # ``marks=None`` is byte-identical to frozen P6 single-symbol valuation
        # (``{symbol: last_close}``); the current symbol's own mark always takes
        # precedence for consistency. Exposure caps use entry notional (unchanged).
        cfg = self._cfg
        symbol = candidate.symbol if candidate is not None else None

        # Audit snapshot (§16 / J-ev): deterministic, serializable, secret-free.
        # Seeded with all configured limits; observed values are added as computed,
        # so every return (APPROVE/HOLD/REJECT) carries the context available so far.
        ev: dict[str, str] = {
            "max_risk_per_trade_pct": str(cfg.max_risk_per_trade_pct),
            "max_single_asset_exposure_pct": str(cfg.max_single_asset_exposure_pct),
            "max_total_exposure_pct": str(cfg.max_total_exposure_pct),
            "max_simultaneous_positions": str(cfg.max_simultaneous_positions),
            "correlated_exposure_cap_pct": str(cfg.correlated_exposure_cap_pct),
            "max_daily_loss_pct": str(cfg.max_daily_loss_pct),
            "max_weekly_loss_pct": str(cfg.max_weekly_loss_pct),
            "max_drawdown_pct": str(cfg.max_drawdown_pct),
            "vol_shock_atr_pct": str(cfg.vol_shock_atr_pct),
            "abnormal_spread_pct": str(cfg.abnormal_spread_pct),
            "abnormal_slippage_pct": str(cfg.abnormal_slippage_pct),
            "max_staleness_intervals": str(cfg.max_staleness_intervals),
        }

        def R(reason: RiskReason, **kw) -> RiskAssessment:
            return self._assess(
                reason, symbol=symbol, decision_time=decision_time, evaluated=dict(ev), **kw
            )

        # 1. kill switch
        if kill_state.status is KillSwitchStatus.HALTED:
            return R(RiskReason.KILL_SWITCH_HALTED)
        if kill_state.status is KillSwitchStatus.PAUSED:
            return R(RiskReason.KILL_SWITCH_PAUSED)

        # 2. fail-closed inputs
        if candidate is None:
            return R(RiskReason.MISSING_CANDIDATE)
        if plan is None:
            return R(RiskReason.MISSING_PLAN)
        if verdict is None or verdict.action is not AnalystAction.PROCEED:
            return R(RiskReason.ANALYST_NOT_PROCEED)

        # 3. market state fail-closed
        ev["market_usable"] = str(market.usable)
        ev["market_stale"] = str(market.stale)
        if not market.usable:
            return R(RiskReason.MARKET_INVALID)
        if market.stale:
            return R(RiskReason.MARKET_STALE)
        if market.last_close <= 0 or market.atr_pct is None:
            return R(RiskReason.NON_FINITE)

        # 4. market precautionary (runtime-only)
        ev["spread_pct"] = str(market.spread_pct)
        ev["slippage_pct"] = str(market.slippage_pct)
        ev["atr_pct"] = str(market.atr_pct)
        if market.spread_pct > cfg.abnormal_spread_pct:
            return R(RiskReason.ABNORMAL_SPREAD)
        if market.slippage_pct > cfg.abnormal_slippage_pct:
            return R(RiskReason.ABNORMAL_SLIPPAGE)
        if market.atr_pct >= cfg.vol_shock_atr_pct:
            return R(RiskReason.VOLATILITY_SHOCK)

        # 5. authoritative equity (OD-3: full-book when marks supplied; own mark wins)
        own_mark = {str(market.symbol): market.last_close}
        eq_marks = own_mark if marks is None else {**marks, **own_mark}
        equity = account.equity(eq_marks)
        ev["account_equity"] = str(equity)
        ev["hwm_equity"] = str(account.hwm_equity)
        ev["day_baseline_equity"] = str(day_baseline_equity)
        ev["week_baseline_equity"] = str(week_baseline_equity)
        if equity <= 0:
            return R(RiskReason.INSUFFICIENT_CASH)

        # 6. per-trade risk — INDEPENDENTLY recomputed (H6), plan is advisory only
        risk_amount = plan.quantity * (plan.entry_ref - plan.stop_price)
        if risk_amount <= 0:
            return R(RiskReason.NON_FINITE)
        risk_pct = float(risk_amount / equity)
        ev["trade_risk_amount"] = str(risk_amount)
        ev["trade_risk_pct"] = str(risk_pct)
        ev["plan_risk_amount"] = str(plan.risk_amount)
        # H6 consistency: recomputed risk must match the plan's stated amount
        denom = plan.risk_amount if plan.risk_amount > 0 else Decimal(1)
        if abs(risk_amount - plan.risk_amount) / denom > Decimal(str(cfg.plan_risk_tolerance_pct)):
            return R(RiskReason.INCONSISTENT_PLAN, risk_pct=risk_pct)
        if risk_pct > cfg.max_risk_per_trade_pct:
            return R(RiskReason.EXCEEDS_PER_TRADE_RISK, risk_pct=risk_pct)

        # 7. exposure (recomputed from authoritative positions + this plan)
        new_notional = plan.quantity * plan.entry_ref
        ev["new_notional"] = str(new_notional)
        ev["cash"] = str(account.cash)
        if new_notional > account.cash:
            return R(RiskReason.INSUFFICIENT_CASH, risk_pct=risk_pct)
        exposures = account.exposure_by_symbol()
        sym = str(candidate.symbol)
        is_new = account.position_for(candidate.symbol) is None
        single_after = exposures.get(sym, Decimal(0)) + new_notional
        group = cfg.correlation_group_for(candidate.symbol.base)
        group_after = account.group_exposure(group) + new_notional
        total_after = account.total_exposure() + new_notional
        exposure_after_pct = float(total_after / equity)
        ev["open_positions"] = str(account.open_count())
        ev["is_new_symbol"] = str(is_new)
        ev["single_asset_exposure"] = str(single_after)
        ev["correlated_exposure"] = str(group_after)
        ev["total_exposure"] = str(total_after)
        ev["exposure_after_pct"] = str(exposure_after_pct)
        if is_new and account.open_count() + 1 > cfg.max_simultaneous_positions:
            return R(RiskReason.MAX_POSITIONS, risk_pct=risk_pct)
        if single_after > equity * Decimal(str(cfg.max_single_asset_exposure_pct)):
            return R(RiskReason.EXCEEDS_SINGLE_ASSET, risk_pct=risk_pct)
        if group_after > equity * Decimal(str(cfg.correlated_exposure_cap_pct)):
            return R(RiskReason.EXCEEDS_CORRELATED, risk_pct=risk_pct)
        if total_after > equity * Decimal(str(cfg.max_total_exposure_pct)):
            return R(
                RiskReason.EXCEEDS_TOTAL, risk_pct=risk_pct,
                exposure_after_pct=exposure_after_pct,
            )

        # 8. runtime-only loss / drawdown controls (authoritative)
        hwm = max(account.hwm_equity, equity)
        drawdown_pct = float((hwm - equity) / hwm) if hwm > 0 else 0.0
        day_loss = float((day_baseline_equity - equity) / day_baseline_equity) \
            if day_baseline_equity > 0 else 0.0
        week_loss = float((week_baseline_equity - equity) / week_baseline_equity) \
            if week_baseline_equity > 0 else 0.0
        ev["drawdown_pct"] = str(drawdown_pct)
        ev["daily_loss_pct"] = str(day_loss)
        ev["weekly_loss_pct"] = str(week_loss)
        if drawdown_pct > cfg.max_drawdown_pct:
            return R(RiskReason.DRAWDOWN_LIMIT, risk_pct=risk_pct)
        if day_loss > cfg.max_daily_loss_pct:
            return R(RiskReason.DAILY_LOSS_LIMIT, risk_pct=risk_pct)
        if week_loss > cfg.max_weekly_loss_pct:
            return R(RiskReason.WEEKLY_LOSS_LIMIT, risk_pct=risk_pct)

        return R(RiskReason.OK, risk_pct=risk_pct, exposure_after_pct=exposure_after_pct)
