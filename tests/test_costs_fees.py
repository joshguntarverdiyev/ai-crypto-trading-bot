"""Fee estimation: round-trip math and maker vs taker selection."""

from __future__ import annotations

from app.costs.config import CostConfig
from app.costs.fees import entry_exit_fee_pct, round_trip_fee_pct

CFG = CostConfig(taker_fee_pct=0.001, maker_fee_pct=0.0006)


def test_default_is_taker_both_sides() -> None:
    entry, exit_ = entry_exit_fee_pct(CFG)
    assert (entry, exit_) == (0.001, 0.001)
    assert round_trip_fee_pct(CFG) == 0.002


def test_maker_sides_use_maker_fee() -> None:
    assert entry_exit_fee_pct(CFG, maker_entry=True, maker_exit=True) == (0.0006, 0.0006)
    assert round_trip_fee_pct(CFG, maker_entry=True, maker_exit=True) == 0.0012


def test_mixed_maker_taker() -> None:
    entry, exit_ = entry_exit_fee_pct(CFG, maker_entry=True, maker_exit=False)
    assert (entry, exit_) == (0.0006, 0.001)
