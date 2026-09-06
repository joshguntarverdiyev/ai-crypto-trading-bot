"""Guard: the backtesting package contains NO optimizer / parameter search (§7.1).

P7 builds measurement machinery only. There must be no automated hyperparameter
search or "select the best parameters" routine — calibration is a separate,
protocol-governed research activity, never a code deliverable.
"""

from __future__ import annotations

import re
from pathlib import Path

_BACKTEST_DIR = Path(__file__).resolve().parent.parent / "backtesting"

# Function/def names that would indicate an optimizer/search. ``perturbation`` and
# ``sweep`` are ALLOWED (they only *report* across a fixed, caller-supplied set).
_FORBIDDEN_DEFS = re.compile(
    r"def\s+\w*(optimi[sz]e|hyperparam|grid_search|random_search|bayes|"
    r"auto_?tune|maximi[sz]e|minimi[sz]e|best_param|select_best|curve_fit)\w*",
    re.IGNORECASE,
)


def test_no_optimizer_or_search_entrypoint_exists() -> None:
    for path in _BACKTEST_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        match = _FORBIDDEN_DEFS.search(text)
        assert match is None, f"{path.name} defines a forbidden optimizer: {match.group()!r}"


def test_perturbation_reports_only_fixed_variants() -> None:
    # The perturbation helper takes a caller-supplied fixed list and returns
    # metrics per variant — it does not choose a winner.
    import inspect

    from backtesting.robustness import parameter_perturbation

    sig = inspect.signature(parameter_perturbation)
    assert "strategy_variants" in sig.parameters
    src = inspect.getsource(parameter_perturbation)
    assert "return out" in src and "max(" not in src and "min(" not in src
