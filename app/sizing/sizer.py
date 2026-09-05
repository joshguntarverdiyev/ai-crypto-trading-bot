"""PositionSizer — risk-budgeting position sizing (Phase 4).

Stateless and deterministic. Given a strategy ``Candidate``, an explicit
``account_equity`` (no fixed-capital assumption, Master Plan §H), and
caller-supplied ``current_exposures`` (per-symbol open notional in quote
currency), compute an advisory ``PositionPlan`` or a ``NO_TRADE`` with a reason.

Money math is ``Decimal`` throughout; the candidate's float prices are converted
once here at the boundary with finite validation. Quantity is floored to
``step_size`` (conservative — never exceeds the risk budget); prices are rounded
to ``tick_size``. Any violated constraint → ``NO_TRADE`` (§13).

**Advisory only (Contract clarification 2):** a ``SIZED`` plan is a pre-runtime
constraint, not an order and not authorization to trade. It never overrides the
future P6 RiskManager (final authority), kill-switch, realized-loss/drawdown
controls, or runtime portfolio state. The sizer holds no state and issues nothing.
No order-book depth is used.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from app.sizing.config import SIZING_VERSION, SizingConfig
from app.sizing.models import PositionPlan, SizingDecision, SizingReason, SizingResult
from app.strategy.models import Candidate


def _round_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    return (price / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick


def _floor_to_step(qty: Decimal, step: Decimal) -> Decimal:
    return (qty / step).quantize(Decimal(1), rounding=ROUND_DOWN) * step


class PositionSizer:
    def __init__(self, config: SizingConfig | None = None) -> None:
        self._cfg = config or SizingConfig()

    def _no_trade(self, reason: SizingReason) -> SizingResult:
        return SizingResult(
            decision=SizingDecision.NO_TRADE,
            reason=reason,
            plan=None,
            sizing_version=SIZING_VERSION,
            config_version=self._cfg.version_tag,
        )

    def plan(
        self,
        candidate: Candidate,
        *,
        account_equity: Decimal,
        current_exposures: Mapping[str, Decimal] | None = None,
    ) -> SizingResult:
        cfg = self._cfg
        cfgv = cfg.version_tag
        exposures = dict(current_exposures or {})

        # --- fail-safe input validation ---
        if not (math.isfinite(candidate.entry_ref) and math.isfinite(candidate.stop_price)):
            return self._no_trade(SizingReason.NON_FINITE)
        if not isinstance(account_equity, Decimal) or account_equity <= 0:
            return self._no_trade(SizingReason.INSUFFICIENT_EQUITY)

        entry = _round_to_tick(Decimal(str(candidate.entry_ref)), cfg.tick_size)
        stop = _round_to_tick(Decimal(str(candidate.stop_price)), cfg.tick_size)
        if entry <= 0 or stop <= 0 or stop >= entry:  # long-only: stop below entry
            return self._no_trade(SizingReason.INVALID_STOP)

        risk_per_unit = entry - stop
        risk_budget = account_equity * Decimal(str(cfg.risk_per_trade_pct))
        if risk_budget <= 0:
            return self._no_trade(SizingReason.RISK_BUDGET_ZERO)

        quantity = _floor_to_step(risk_budget / risk_per_unit, cfg.step_size)
        if quantity <= 0:
            return self._no_trade(SizingReason.BELOW_MIN_NOTIONAL)

        notional = quantity * entry
        if notional < cfg.min_notional:
            return self._no_trade(SizingReason.BELOW_MIN_NOTIONAL)

        # --- structural portfolio caps (pure, over caller-supplied exposures) ---
        equity = account_equity
        symbol_key = str(candidate.symbol)
        existing_symbol = exposures.get(symbol_key, Decimal(0))
        distinct_symbols = {k for k, v in exposures.items() if v > 0}
        is_new_symbol = symbol_key not in distinct_symbols
        if is_new_symbol and len(distinct_symbols) + 1 > cfg.max_simultaneous_positions:
            return self._no_trade(SizingReason.MAX_POSITIONS_REACHED)

        single_cap = equity * Decimal(str(cfg.max_single_asset_exposure_pct))
        if existing_symbol + notional > single_cap:
            return self._no_trade(SizingReason.EXCEEDS_SINGLE_ASSET_CAP)

        group = cfg.correlation_group_for(candidate.symbol.base)
        group_existing = sum(
            (v for k, v in exposures.items() if k.split("/")[0] in group),
            Decimal(0),
        )
        corr_cap = equity * Decimal(str(cfg.correlated_exposure_cap_pct))
        if group_existing + notional > corr_cap:
            return self._no_trade(SizingReason.EXCEEDS_CORRELATED_CAP)

        total_existing = sum(exposures.values(), Decimal(0))
        if total_existing + notional > equity * Decimal(str(cfg.max_total_exposure_pct)):
            return self._no_trade(SizingReason.EXCEEDS_TOTAL_CAP)

        if notional > cfg.liquidity_cap_quote:
            return self._no_trade(SizingReason.LIQUIDITY_CAP)

        risk_amount = quantity * risk_per_unit
        plan = PositionPlan(
            symbol=candidate.symbol,
            direction=candidate.direction,
            entry_ref=entry,
            stop_price=stop,
            quantity=quantity,
            notional=notional,
            risk_amount=risk_amount,
            risk_per_trade_pct_effective=risk_amount / account_equity,
            exposure_after_pct=(total_existing + notional) / account_equity,
            sizing_version=SIZING_VERSION,
            config_version=cfgv,
        )
        return SizingResult(
            decision=SizingDecision.SIZED,
            reason=SizingReason.OK,
            plan=plan,
            sizing_version=SIZING_VERSION,
            config_version=cfgv,
        )
