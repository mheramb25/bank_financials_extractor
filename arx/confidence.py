"""Stages 14-15: tier-aware evidence scoring, and the confidence engine.

Stage 14 -- **evidence requirements differ by metric type**, and pretending
otherwise is how good systems throw away good data:

* **Tier A** (PAT, NII, Deposits, Advances, RoA, RoE, Total Assets, GNPA, CRAR):
  these appear in the Highlights *and* the P&L *and* the Notes.  If we only found
  one, something is off, and the score reflects it.
* **Tier B** (CASA, PCR, Employees, Branches, NIM, Cost-to-Income): moderate
  corroboration expected.
* **Tier C** (ESG rating, mobile app users, tech spend, board diversity, CSR):
  these are stated **once**, in one sentence, in one sustainability section, and
  that is completely normal.  A single occurrence earns full evidence marks --
  penalising it would guarantee that the entire ESG block comes out as ND.

Stage 15 -- six components, weighted (``config.yaml``), each normalised to [0,1]:

    court + source + evidence + dna + formula + trend  ->  confidence 0-100

    >= 95  Auto Approve   -> write
    80-94  High           -> write
    65-79  Manual Review  -> write, flag, add a cell comment
    <  65  Reject         -> write ND, log the reason in Missing Cells Report

**The core principle: a false positive is worse than a missing value.** Every
knob above is set so that doubt resolves *downwards*, into ND.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from arx import load_config
from arx.models import Decision, MetricDef, Verdict

log = logging.getLogger("arx.confidence")


# --------------------------------------------------------------------------- #
# Stage 14
# --------------------------------------------------------------------------- #


def evidence_score(verdict: Verdict, md: MetricDef, cfg: Optional[dict] = None) -> float:
    """Independent-corroboration score in [0, 1], scaled by the metric's tier."""
    cfg = cfg or load_config()
    tier_cfg = cfg["tiers"].get(md.tier, cfg["tiers"]["B"])

    sources = verdict.candidate.independent_sources
    full = int(tier_cfg["independent_sources_for_full_marks"])
    minimum = int(tier_cfg["min_independent_sources"])

    single = float(tier_cfg["single_source_evidence_score"])

    if sources >= full:
        score = 1.0
    elif sources >= minimum:
        # Linear from "one source" up to "everything we'd like to see".
        span = (sources - 1) / (full - 1) if full > 1 else 1.0
        score = single + (1.0 - single) * span
    else:
        # Below the tier's minimum: this is exactly the case the tier exists for.
        # A Tier-A number seen once is not a Tier-A number.
        score = single * 0.5

    # A second, differently-named alias agreeing is real independent evidence.
    if verdict.candidate.distinct_aliases > 1:
        score = min(1.0, score + 0.05)

    return round(max(0.0, min(1.0, score)), 4)


# --------------------------------------------------------------------------- #
# Stage 15
# --------------------------------------------------------------------------- #


def _norm_court(court_score: float) -> float:
    """Court score (which can go negative) -> [0, 1]."""
    return max(0.0, min(1.0, court_score / 100.0))


def score_verdict(
    verdict: Verdict,
    md: MetricDef,
    cfg: Optional[dict] = None,
) -> Verdict:
    """Fill in ``confidence``, ``decision`` and ``reason``. Mutates and returns."""
    cfg = cfg or load_config()
    w = cfg["confidence_weights"]

    verdict.evidence_score = evidence_score(verdict, md, cfg)

    components = {
        "court": _norm_court(verdict.court_score),
        "source": verdict.source_score,
        "evidence": verdict.evidence_score,
        "dna": verdict.dna_score,
        "formula": verdict.formula_score,
        "trend": verdict.trend_score,
    }
    confidence = 100.0 * sum(float(w[k]) * v for k, v in components.items())

    # A derived value can never be an Auto Approve: it was never printed.
    if verdict.candidate.derived:
        cap = float(cfg["formulas"]["derived_confidence_cap"])
        confidence = min(confidence, cap)

    verdict.confidence = round(max(0.0, min(100.0, confidence)), 1)
    verdict.decision = decide(verdict.confidence, cfg)
    verdict.reason = explain(verdict, components, md)
    return verdict


def decide(confidence: float, cfg: Optional[dict] = None) -> Decision:
    """Map a confidence to a decision band."""
    cfg = cfg or load_config()
    bands = cfg["decision_bands"]
    if confidence >= float(bands["auto_approve"]):
        return Decision.AUTO
    if confidence >= float(bands["high"]):
        return Decision.HIGH
    if confidence >= float(bands["manual_review"]):
        return Decision.MANUAL
    return Decision.REJECT


def writes_to_excel(decision: Decision) -> bool:
    """Auto, High and Manual are written; Reject becomes ND."""
    return decision in (Decision.AUTO, Decision.HIGH, Decision.MANUAL)


def explain(verdict: Verdict, components: dict, md: MetricDef) -> str:
    """A single sentence a human can act on, written into the audit trail."""
    cand = verdict.candidate
    bits: List[str] = []

    if cand.derived:
        bits.append(f"derived ({cand.derivation})")
    else:
        bits.append(
            f"chosen from {cand.section.value} p{cand.page}"
            + (f" table {cand.table_id}" if cand.table_id else " (prose)")
        )
        bits.append(f"alias {cand.alias_matched!r}")
        bits.append(f"{cand.independent_sources} independent source(s)")

    if verdict.prosecutor_hits:
        top = max(verdict.prosecutor_hits, key=lambda h: h.penalty)
        bits.append(f"top penalty: {top.prosecutor} (-{top.penalty:g}) {top.reason}")
    else:
        bits.append("no prosecutor penalties")

    failed = verdict.checks_failed
    if failed:
        bits.append("failed checks: " + ", ".join(failed[:4]))

    weakest = min(components, key=lambda k: components[k])
    bits.append(f"weakest component: {weakest} ({components[weakest]:.2f})")

    return "; ".join(bits)


def rejection_reason(
    verdict: Optional[Verdict],
    md: MetricDef,
    cfg: Optional[dict] = None,
) -> str:
    """The machine-generated 'Reason data unavailable' for Missing Cells Report."""
    cfg = cfg or load_config()
    threshold = float(cfg["decision_bands"]["manual_review"])

    if verdict is None:
        return f"No candidate value found for {md.excel_header!r} anywhere in the report"

    cand = verdict.candidate
    if verdict.prosecutor_hits:
        worst = max(verdict.prosecutor_hits, key=lambda h: h.penalty)
        return (
            f"{worst.reason} (confidence {verdict.confidence:.0f} < {threshold:.0f} threshold)"
        )
    if verdict.checks_failed:
        detail = next(
            (c.detail for c in verdict.checks if not c.passed), ", ".join(verdict.checks_failed)
        )
        return f"{detail} (confidence {verdict.confidence:.0f} < {threshold:.0f} threshold)"
    if not cand.from_table:
        return (
            f"Found only in narrative text (confidence {verdict.confidence:.0f} "
            f"< {threshold:.0f} threshold)"
        )
    return (
        f"Insufficient corroboration: {cand.independent_sources} independent source(s) "
        f"for a Tier-{md.tier} metric (confidence {verdict.confidence:.0f} "
        f"< {threshold:.0f} threshold)"
    )


def na_reason(md: MetricDef, inst_type: str, category: str) -> str:
    """The reason a metric is NA (not applicable) rather than ND (not disclosed)."""
    label = {
        "bank": "a bank",
        "sfb": "a small finance bank",
        "nbfc": "an NBFC",
        "hfc": "a housing finance company",
        "aifi": "an AIFI",
    }.get(inst_type, inst_type)
    return (
        f"Metric not applicable to {label} ({category}); "
        f"{md.excel_header!r} applies to: {', '.join(md.applicable_to)}"
    )


def summarise(verdicts: Sequence[Verdict]) -> dict:
    """Counts per decision band -- feeds the Confidence Summary sheet."""
    out = {d.value: 0 for d in Decision}
    for v in verdicts:
        out[v.decision.value] = out.get(v.decision.value, 0) + 1
    return out
