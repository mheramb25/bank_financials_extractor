"""Stages 9-10: the Financial DNA layer and the reverse validation engine.

A number can be perfectly extracted and still be nonsense.  ``PCR = 140`` is a
clean read of a misaligned row.  ``Net NPA > Gross NPA`` is arithmetically
impossible.  ``RoA = 45`` is not a bank.  These four levels catch that:

* **Level 1 -- Industry ranges.**  Per-metric ``sane_range`` from metrics.yaml.
* **Level 2 -- Banking logic.**  ``GNPA >= NNPA``, ``RoE >= RoA``, ``CAR >= CET1``,
  ``Total Assets > Advances``, ``Tier1 + Tier2 ~ CRAR``, ``Net Worth > 0`` ...
  Rules live in ``metrics.yaml: banking_rules`` and are only evaluated when both
  sides of the comparison actually exist.
* **Level 3 -- Historical DNA.**  Against the same institution's other years,
  already sitting in the workbook.
* **Level 4 -- Peer DNA.**  Against peers of the same category in the same FY.

And then Stage 10, which is the one that catches the errors the others cannot:

* **Reverse validation.**  Do not only ask "what is PAT?"  Also ask, of the number
  you chose, "what else in this report is this exact number?"  If 62,129 is also
  printed as the value of *Other Income*, you have found a column shift.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Dict, List, Optional, Sequence

from arx import load_banking_rules, load_config, metrics_by_key
from arx.models import BankingRule, Candidate, CheckResult, MetricDef, ProsecutorHit
from arx.normalize import in_range, value_signature

log = logging.getLogger("arx.dna")


@dataclass
class DnaContext:
    """The comparative context a value is judged against."""

    inst_type: str
    fiscal_year: str
    # metric -> {fiscal_year: value} for THIS institution (from the workbook)
    history: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # metric -> [values] for peers of the same category in the same FY
    peers: Dict[str, List[float]] = field(default_factory=dict)
    cfg: dict = field(default_factory=load_config)


# --------------------------------------------------------------------------- #
# Level 1 -- industry ranges
# --------------------------------------------------------------------------- #


def level1_range(value: Optional[float], md: MetricDef) -> CheckResult:
    """Is the value physically possible for this metric at all?"""
    if value is None or md.sane_range is None:
        return CheckResult(
            name=f"range:{md.key}", passed=True, level="L1", detail="no range defined"
        )
    lo, hi = md.sane_range
    ok = in_range(value, md.sane_range)
    if not md.allow_negative and value < 0:
        return CheckResult(
            name=f"range:{md.key}",
            passed=False,
            level="L1",
            detail=f"{value:g} is negative and {md.key} cannot be negative",
        )
    return CheckResult(
        name=f"range:{md.key}",
        passed=ok,
        level="L1",
        detail=(
            f"{value:g} within [{lo:g}, {hi:g}]"
            if ok
            else f"{value:g} outside sane range [{lo:g}, {hi:g}]"
        ),
    )


# --------------------------------------------------------------------------- #
# Level 2 -- banking logic
# --------------------------------------------------------------------------- #


def _resolve(operand, values: Dict[str, float]) -> Optional[float]:
    """A rule operand is either a metric key or a literal number."""
    if isinstance(operand, (int, float)):
        return float(operand)
    return values.get(operand)


def level2_rules(
    values: Dict[str, float],
    rules: Optional[Sequence[BankingRule]] = None,
) -> List[CheckResult]:
    """Evaluate the banking-logic rules over a set of chosen values.

    A rule whose operands are not both present is skipped silently -- absence is
    not a violation, and we must never punish a metric for a *missing* peer.
    """
    rules = rules or load_banking_rules()
    out: List[CheckResult] = []

    for rule in rules:
        if rule.op == "approx_sum":
            parts = [values.get(k) for k in rule.left]  # type: ignore[union-attr]
            target = _resolve(rule.right, values)
            if any(p is None for p in parts) or target is None:
                continue
            total = sum(p for p in parts if p is not None)
            tol = float(rule.tolerance or 0.3)
            ok = abs(total - target) <= tol
            out.append(
                CheckResult(
                    name=rule.id,
                    passed=ok,
                    level="L2",
                    detail=(
                        f"{' + '.join(f'{k}={values[k]:g}' for k in rule.left)} "  # type: ignore[union-attr]
                        f"= {total:g} vs {rule.right}={target:g} (tol {tol:g})"
                        + ("" if ok else f" -- {rule.message}")
                    ),
                )
            )
            continue

        left = _resolve(rule.left, values)
        if left is None:
            continue

        if rule.op == "positive":
            ok = left > 0
            out.append(
                CheckResult(
                    name=rule.id,
                    passed=ok,
                    level="L2",
                    detail=f"{rule.left}={left:g}" + ("" if ok else f" -- {rule.message}"),
                )
            )
            continue

        right = _resolve(rule.right, values)
        if right is None:
            continue

        ops = {
            "gt": lambda a, b: a > b,
            "gte": lambda a, b: a >= b,
            "lt": lambda a, b: a < b,
            "lte": lambda a, b: a <= b,
        }
        fn = ops.get(rule.op)
        if fn is None:
            log.warning("unknown banking rule op %r in %s", rule.op, rule.id)
            continue
        ok = fn(left, right)
        out.append(
            CheckResult(
                name=rule.id,
                passed=ok,
                level="L2",
                detail=(
                    f"{rule.left}={left:g} {rule.op} {rule.right}={right:g}"
                    + ("" if ok else f" -- {rule.message}")
                ),
            )
        )
    return out


def metrics_in_rule(rule: BankingRule) -> List[str]:
    """Which metric keys a rule touches -- used to attribute a failure."""
    keys: List[str] = []
    if isinstance(rule.left, list):
        keys.extend(rule.left)
    elif isinstance(rule.left, str):
        keys.append(rule.left)
    if isinstance(rule.right, str):
        keys.append(rule.right)
    return keys


# --------------------------------------------------------------------------- #
# Level 3 -- historical DNA
# --------------------------------------------------------------------------- #


def level3_history(
    metric: str, value: Optional[float], ctx: DnaContext
) -> Optional[CheckResult]:
    """Compare against the same institution's other years.

    A 500% jump is *flagged*, never auto-rejected: a merger (HDFC), a rights
    issue, or a first full year of operations can legitimately do that.  The
    penalty exists to push the cell into Manual Review, not to delete the number.
    """
    if value is None:
        return None
    hist = {
        fy: v
        for fy, v in (ctx.history.get(metric) or {}).items()
        if fy != ctx.fiscal_year and v is not None
    }
    if not hist:
        return None

    prev_fy = sorted(hist)[-1]
    prev = hist[prev_fy]
    if prev == 0:
        return None

    change = abs(value - prev) / abs(prev)
    warn = float(ctx.cfg["dna"]["history_yoy_warn"])
    severe = float(ctx.cfg["dna"]["history_yoy_severe"])

    if change <= warn:
        return CheckResult(
            name=f"history:{metric}",
            passed=True,
            level="L3",
            detail=f"{value:g} vs {prev_fy} {prev:g} ({change:+.0%}) -- normal movement",
        )
    return CheckResult(
        name=f"history:{metric}",
        passed=False,
        level="L3",
        detail=(
            f"{value:g} vs {prev_fy} {prev:g} is a {change:.0%} move"
            + (" -- extreme, investigate (merger? rights issue? unit error?)"
               if change >= severe
               else " -- larger than expected")
        ),
    )


# --------------------------------------------------------------------------- #
# Level 4 -- peer DNA
# --------------------------------------------------------------------------- #


def level4_peers(
    metric: str, value: Optional[float], ctx: DnaContext
) -> Optional[CheckResult]:
    """Compare against peers of the same category in the same FY.

    Only ratios and percentages are peer-comparable; comparing SBI's Total Assets
    to Can Fin Homes' is meaningless, so size metrics are exempt.
    """
    if value is None:
        return None
    md = metrics_by_key().get(metric)
    if md is None or md.unit_type.value not in ("percent", "ratio"):
        return None

    sample = [v for v in (ctx.peers.get(metric) or []) if v is not None]
    if len(sample) < int(ctx.cfg["dna"]["peer_min_sample"]):
        return None

    mu = mean(sample)
    sd = pstdev(sample)
    if sd == 0:
        return None
    z = abs(value - mu) / sd
    limit = float(ctx.cfg["dna"]["peer_zscore_warn"])
    ok = z <= limit
    return CheckResult(
        name=f"peers:{metric}",
        passed=ok,
        level="L4",
        detail=(
            f"{value:g} vs peer mean {mu:.2f} (sd {sd:.2f}, z={z:.1f}, n={len(sample)})"
            + ("" if ok else " -- implausible against peers of the same category")
        ),
    )


# --------------------------------------------------------------------------- #
# Stage 10 -- reverse validation
# --------------------------------------------------------------------------- #


def reverse_validate(
    metric: str,
    cand: Candidate,
    pool: Dict[str, List[Candidate]],
    cfg: Optional[dict] = None,
) -> Optional[ProsecutorHit]:
    """``value -> metric``: is the number we chose *also* some other metric's value?

    This is how column-shift and row-shift errors surface.  If we picked 62,129
    for NII and the report also prints 62,129 as the value of *Other Income* on
    the same page, one of the two reads is a lie, and we do not know which.

    Legitimate collisions are common in the ratio metrics (two ratios can both be
    3.2), so we only fire on currency and count metrics, and only when the other
    metric's occurrence is on the same page (i.e. plausibly the same table row we
    slipped out of).
    """
    cfg = cfg or load_config()
    md = metrics_by_key().get(metric)
    if md is None or cand.value is None:
        return None
    if md.unit_type.value not in ("currency", "count"):
        return None

    sig = value_signature(cand.value)
    collisions: List[str] = []

    for other_key, others in pool.items():
        if other_key == metric:
            continue
        other_md = metrics_by_key().get(other_key)
        if other_md is None or other_md.unit_type.value != md.unit_type.value:
            continue
        for other in others:
            if other.value is None:
                continue
            if value_signature(other.value) != sig:
                continue
            if other.page != cand.page:
                continue  # a coincidence across the report is not evidence of a shift
            if other.table_id and cand.table_id and other.table_id != cand.table_id:
                continue
            collisions.append(f"{other_key} (row {other.row_label!r}, p{other.page})")

    if not collisions:
        return None

    base = float(cfg["dna"]["reverse_validation_penalty"])
    extra = float(cfg["dna"].get("reverse_validation_extra_per_collision", 6.0))
    cap = float(cfg["dna"].get("reverse_validation_max_penalty", 60.0))
    penalty = min(cap, base + extra * max(0, len(set(collisions)) - 1))

    return ProsecutorHit(
        prosecutor="reverse_validation",
        penalty=penalty,
        reason=(
            f"the chosen value {cand.value:g} is ALSO printed as the value of "
            + ", ".join(sorted(set(collisions))[:3])
            + " in the same table -- possible row/column shift"
        ),
    )


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def dna_score(checks: Sequence[CheckResult], cfg: Optional[dict] = None) -> float:
    """Fold the DNA checks into a single score in [0, 1]."""
    cfg = cfg or load_config()
    d = cfg["dna"]
    penalty_by_level = {
        "L1": float(d["level1_range_violation"]),
        "L2": float(d["level2_rule_violation"]),
        "L3": float(d["level3_history_deviation"]),
        "L4": float(d["level4_peer_deviation"]),
    }
    score = 1.0
    for check in checks:
        if not check.passed:
            score -= penalty_by_level.get(check.level, 0.1)
    return max(0.0, min(1.0, score))
