"""Stages 11-13: formula validation, numerical sanity, and trend validation.

The formulas are the cheapest and most powerful check in the whole system,
because they are *independent* of how the number was read off the page.  If
``Interest Earned - Interest Expended`` does not equal the NII we extracted, then
one of the three is wrong, no matter how confidently each was printed.

Tolerances (``config.yaml``):
    amounts  -- +/-1% relative
    ratios   -- +/-0.1 percentage points absolute

Derivation (Stage 11, second half): if a metric is *missing* but derivable from
inputs that are themselves high-confidence, we compute it, mark ``derived=True``,
cap its confidence at 90, and write the formula into the audit trail.  We never
derive from inputs that are themselves shaky -- that just launders uncertainty
into a number that looks authoritative.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from arx import load_config, metrics_by_key
from arx.models import CheckResult, MetricDef
from arx.normalize import suspect_missing_decimal

log = logging.getLogger("arx.formulas")


@dataclass(frozen=True)
class Formula:
    """One arithmetic identity between metrics."""

    id: str
    target: str
    inputs: Tuple[str, ...]
    fn: Callable[..., Optional[float]]
    expression: str
    kind: str  # "amount" | "ratio"


def _safe_div(num: float, den: float) -> Optional[float]:
    return None if den in (0, None) else num / den


FORMULAS: Dict[str, Formula] = {
    "nii_identity": Formula(
        id="nii_identity",
        target="nii",
        inputs=("interest_earned", "interest_expended"),
        fn=lambda ie, ix: ie - ix,
        expression="NII = Interest Earned - Interest Expended",
        kind="amount",
    ),
    "crar_identity": Formula(
        id="crar_identity",
        target="crar",
        inputs=("tier1", "tier2"),
        fn=lambda t1, t2: t1 + t2,
        expression="CRAR = Tier 1 + Tier 2",
        kind="ratio",
    ),
    "pcr_identity": Formula(
        id="pcr_identity",
        target="pcr",
        inputs=("gnpa_amount", "nnpa_amount"),
        fn=lambda g, n: _safe_div((g - n) * 100.0, g),
        expression="PCR = (GNPA - NNPA) / GNPA x 100",
        kind="ratio",
    ),
    "roa_identity": Formula(
        id="roa_identity",
        target="roa",
        inputs=("pat", "total_assets"),
        fn=lambda pat, ta: _safe_div(pat * 100.0, ta),
        expression="RoA = PAT / Total Assets x 100",
        kind="ratio",
    ),
    "roe_identity": Formula(
        id="roe_identity",
        target="roe",
        inputs=("pat", "net_worth"),
        fn=lambda pat, nw: _safe_div(pat * 100.0, nw),
        expression="RoE = PAT / Net Worth x 100",
        kind="ratio",
    ),
    "cost_to_income_identity": Formula(
        id="cost_to_income_identity",
        target="cost_to_income",
        inputs=("opex", "nii", "other_income"),
        fn=lambda opex, nii, oi: _safe_div(opex * 100.0, nii + oi),
        expression="Cost-to-Income = Opex / (NII + Other Income) x 100",
        kind="ratio",
    ),
    "gnpa_amount_identity": Formula(
        id="gnpa_amount_identity",
        target="gnpa_amount",
        inputs=("gnpa_ratio", "gross_advances"),
        fn=lambda ratio, adv: ratio * adv / 100.0,
        expression="GNPA Amount = GNPA% x Gross Advances / 100",
        kind="amount",
    ),
    "wholesale_mix_identity": Formula(
        id="wholesale_mix_identity",
        target="wholesale_mix",
        inputs=("retail_mix",),
        fn=lambda retail: 100.0 - retail,
        expression="Retail Mix % + Wholesale Mix % = 100",
        kind="ratio",
    ),
}


# --------------------------------------------------------------------------- #
# Stage 11a: cross-checking
# --------------------------------------------------------------------------- #


def evaluate(formula: Formula, values: Dict[str, float]) -> Optional[float]:
    """Compute a formula's expected value, or None if an input is missing."""
    args = [values.get(k) for k in formula.inputs]
    if any(a is None for a in args):
        return None
    try:
        return formula.fn(*args)
    except (TypeError, ZeroDivisionError):
        return None


def within_tolerance(
    expected: float, actual: float, kind: str, cfg: Optional[dict] = None
) -> bool:
    """+/-1% relative for amounts, +/-0.1 percentage points for ratios."""
    cfg = cfg or load_config()
    f = cfg["formulas"]
    if kind == "ratio":
        return abs(expected - actual) <= float(f["absolute_tolerance_pp"])
    denom = max(abs(expected), abs(actual))
    if denom == 0:
        return True
    return abs(expected - actual) / denom <= float(f["relative_tolerance"])


def check_formulas(
    values: Dict[str, float], cfg: Optional[dict] = None
) -> List[CheckResult]:
    """Cross-check every identity whose inputs *and* target are all present."""
    cfg = cfg or load_config()
    out: List[CheckResult] = []

    for formula in FORMULAS.values():
        actual = values.get(formula.target)
        if actual is None:
            continue
        expected = evaluate(formula, values)
        if expected is None:
            continue
        ok = within_tolerance(expected, actual, formula.kind, cfg)
        out.append(
            CheckResult(
                name=formula.id,
                passed=ok,
                level="formula",
                detail=(
                    f"{formula.expression}: expected {expected:,.2f}, "
                    f"reported {actual:,.2f}"
                    + ("" if ok else " -- outside tolerance")
                ),
            )
        )
    return out


def formulas_touching(metric: str) -> List[Formula]:
    """Every identity in which ``metric`` appears, as target or as an input."""
    return [
        f
        for f in FORMULAS.values()
        if f.target == metric or metric in f.inputs
    ]


def formula_score(
    metric: str, checks: Sequence[CheckResult], cfg: Optional[dict] = None
) -> float:
    """Score in [0, 1] for one metric, from the identities that touch it."""
    cfg = cfg or load_config()
    f = cfg["formulas"]
    relevant_ids = {fm.id for fm in formulas_touching(metric)}
    relevant = [c for c in checks if c.name in relevant_ids]
    if not relevant:
        return float(f["formula_na_score"])
    if all(c.passed for c in relevant):
        return float(f["formula_pass_score"])
    if any(c.passed for c in relevant):
        return (float(f["formula_pass_score"]) + float(f["formula_fail_score"])) / 2.0
    return float(f["formula_fail_score"])


# --------------------------------------------------------------------------- #
# Stage 11b: derivation
# --------------------------------------------------------------------------- #


def derivable(
    metric: str,
    values: Dict[str, float],
    confidences: Dict[str, float],
    cfg: Optional[dict] = None,
) -> Optional[Tuple[float, str]]:
    """If ``metric`` is missing but derivable from confident inputs, derive it.

    Returns ``(value, formula_expression)`` or None.  Every input must clear
    ``formulas.derive_min_input_confidence`` -- deriving from a shaky input would
    manufacture a confident-looking number out of a guess, which is the exact
    failure mode this system exists to prevent.
    """
    cfg = cfg or load_config()
    md = metrics_by_key().get(metric)
    if md is None or md.derivable_from is None:
        return None
    if values.get(metric) is not None:
        return None

    formula = FORMULAS.get(md.derivable_from)
    if formula is None:
        log.warning("metric %s names unknown formula %s", metric, md.derivable_from)
        return None

    floor = float(cfg["formulas"]["derive_min_input_confidence"])
    for key in formula.inputs:
        if values.get(key) is None or confidences.get(key, 0.0) < floor:
            return None

    result = evaluate(formula, values)
    if result is None:
        return None
    if md.sane_range and not (md.sane_range[0] <= result <= md.sane_range[1]):
        log.info(
            "declined to derive %s = %.2f: outside sane range %s",
            metric,
            result,
            md.sane_range,
        )
        return None
    return result, formula.expression


def derive_all(
    values: Dict[str, float],
    confidences: Dict[str, float],
    cfg: Optional[dict] = None,
) -> Dict[str, Tuple[float, str]]:
    """Every metric that can be safely derived from what we already trust."""
    out: Dict[str, Tuple[float, str]] = {}
    for metric in metrics_by_key():
        got = derivable(metric, values, confidences, cfg)
        if got:
            out[metric] = got
    return out


# --------------------------------------------------------------------------- #
# Stage 12: numerical sanity
# --------------------------------------------------------------------------- #


def sanity_checks(
    value: Optional[float], md: MetricDef, raw_text: str = ""
) -> List[CheckResult]:
    """The numerical-hygiene checks that do not need any other metric."""
    out: List[CheckResult] = []
    if value is None:
        return out

    if md.unit_type.value == "percent":
        ok = -100.0 <= value <= 1000.0
        out.append(
            CheckResult(
                name=f"sanity:percent_range:{md.key}",
                passed=ok,
                level="sanity",
                detail=f"{value:g}% " + ("is a plausible percentage" if ok else "is not a percentage"),
            )
        )

    if not md.allow_negative and value < 0:
        out.append(
            CheckResult(
                name=f"sanity:negative:{md.key}",
                passed=False,
                level="sanity",
                detail=f"{value:g} is negative but {md.key} cannot be",
            )
        )

    if md.unit_type.value == "count" and abs(value - round(value)) > 1e-6:
        out.append(
            CheckResult(
                name=f"sanity:integer:{md.key}",
                passed=False,
                level="sanity",
                detail=f"{value:g} is not a whole number but {md.key} counts things",
            )
        )

    if suspect_missing_decimal(value, md.sane_range):
        out.append(
            CheckResult(
                name=f"sanity:missing_decimal:{md.key}",
                passed=False,
                level="sanity",
                detail=(
                    f"{value:g} is out of range but {value / 100:g} would be in range "
                    f"-- probable dropped decimal point in {raw_text!r}"
                ),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Stage 13: trend validation
# --------------------------------------------------------------------------- #


def trend_check(
    metric: str,
    value: Optional[float],
    prior_value: Optional[float],
    cfg: Optional[dict] = None,
) -> Tuple[float, Optional[CheckResult]]:
    """YoY plausibility.  Returns ``(trend_score in [0,1], CheckResult|None)``.

    20-30% is normal.  ~500% is *investigated*, never auto-rejected: a merger or
    a rights issue genuinely does that, and silently deleting a real number is
    also a failure.  The penalty is calibrated to drop the cell into Manual
    Review, where a human can look at it.
    """
    cfg = cfg or load_config()
    t = cfg["trend"]
    if value is None or prior_value in (None, 0):
        return 1.0, None

    change = abs(value - prior_value) / abs(prior_value) * 100.0

    if change <= float(t["normal_change_pct"]):
        return 1.0, CheckResult(
            name=f"trend:{metric}",
            passed=True,
            level="trend",
            detail=f"{change:.1f}% YoY -- normal",
        )
    if change <= float(t["investigate_change_pct"]):
        score = 1.0 - float(t["investigate_penalty"]) / 2.0
        return score, CheckResult(
            name=f"trend:{metric}",
            passed=True,
            level="trend",
            detail=f"{change:.1f}% YoY -- larger than typical but plausible",
        )
    if change <= float(t["severe_change_pct"]):
        score = 1.0 - float(t["investigate_penalty"])
        return score, CheckResult(
            name=f"trend:{metric}",
            passed=False,
            level="trend",
            detail=f"{change:.1f}% YoY -- investigate (prior year {prior_value:g})",
        )
    score = 1.0 - float(t["severe_penalty"])
    return score, CheckResult(
        name=f"trend:{metric}",
        passed=False,
        level="trend",
        detail=(
            f"{change:.1f}% YoY vs prior year {prior_value:g} -- extreme. "
            "Flagged for manual review, NOT auto-rejected (a merger or rights "
            "issue can legitimately do this)."
        ),
    )
