"""Stages 6-8: source quality, the defence, four prosecutors, and the judge.

Every candidate gets a trial.

**Defence** argues from provenance: it was in the Financial Statements; it was
*also* in the Highlights and in the Notes; three different aliases produced it;
the table declared its unit; the column header explicitly named the year.

**Prosecutors** argue from doubt.  Four of them, each returning a penalty and a
reason that is written into the audit trail verbatim:

1. ``conflicting_values``  -- something else in this report says otherwise.
2. ``year_mismatch``       -- this looks like last year's column. *Highest
   priority: a year mismatch alone can sink a candidate.*
3. ``unit_mismatch``       -- crore vs lakh vs million vs USD.
4. ``table_alignment``     -- wrong row, wrong column, off-by-one.

**Judge**: ``court_score = defence - Σ penalties``.  The judge ranks; it does not
approve.  Approval is the confidence engine's job (Stage 15), because a candidate
can win its trial and still be unfit to write (e.g. it is the only candidate, it
came from a Chairman's letter, and it fails a banking-logic rule).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from arx import load_config
from arx.models import Candidate, MetricDef, ProsecutorHit, Section, Verdict
from arx.normalize import in_range, same_value, suspect_missing_decimal

log = logging.getLogger("arx.courtroom")


@dataclass
class TrialContext:
    """Everything a prosecutor needs to know beyond the candidate itself."""

    target_fy: str
    prior_fy: Optional[str]
    metric: MetricDef
    inst_type: str
    cfg: dict


# --------------------------------------------------------------------------- #
# Stage 6: source quality
# --------------------------------------------------------------------------- #


def source_score(cand: Candidate, cfg: Optional[dict] = None) -> float:
    """The candidate's section quality, in [0, 1]. Stage 6."""
    cfg = cfg or load_config()
    weights = cfg["section_weights"]
    return float(weights.get(cand.section.value, weights["unknown"]))


# --------------------------------------------------------------------------- #
# Stage 8a: the defence
# --------------------------------------------------------------------------- #


def defend(cand: Candidate, ctx: TrialContext) -> tuple[float, List[str]]:
    """Why is this value correct?  Returns ``(score, reasons)``, score in [0,100]."""
    d = ctx.cfg["defence"]
    score = float(d["base"])
    reasons: List[str] = [f"base {d['base']}"]

    section_bonus = {
        Section.FINANCIAL_STATEMENTS: d["in_financial_statements"],
        Section.FINANCIAL_HIGHLIGHTS: d["in_financial_highlights"],
        Section.MULTI_YEAR_SUMMARY: d["in_multi_year_summary"],
        Section.KEY_RATIOS: d["in_key_ratios"],
        Section.MDNA: d["in_mdna"],
        Section.NARRATIVE: d["in_narrative"],
    }

    # The section the value was found in, plus every *independent* section that
    # agrees with it.
    sections = {cand.section} | {e.section for e in cand.evidence}
    for sec in sections:
        bonus = float(section_bonus.get(sec, 0))
        if bonus:
            score += bonus
            reasons.append(f"found in {sec.value} (+{bonus:g})")

    extra_sections = max(0, cand.distinct_sections - 1)
    if extra_sections:
        bonus = extra_sections * float(d["multi_section_agreement"])
        score += bonus
        reasons.append(f"{extra_sections} independent corroborating section(s) (+{bonus:g})")

    extra_aliases = max(0, cand.distinct_aliases - 1)
    if extra_aliases:
        bonus = extra_aliases * float(d["multi_alias_agreement"])
        score += bonus
        reasons.append(f"{extra_aliases} additional alias(es) agree (+{bonus:g})")

    if not cand.scale_inferred and ctx.metric.unit_type.value == "currency":
        score += float(d["explicit_unit_caption"])
        reasons.append(f"unit printed, not inferred (+{d['explicit_unit_caption']:g})")

    if cand.year_resolved:
        score += float(d["year_column_explicit"])
        reasons.append(f"year column named explicitly (+{d['year_column_explicit']:g})")

    if cand.from_table:
        score += float(d["from_structured_table"])
        reasons.append(f"structured table cell (+{d['from_structured_table']:g})")

    if cand.alias_exact:
        score += float(d["row_label_exact"])
        reasons.append(f"exact row-label match (+{d['row_label_exact']:g})")

    return min(100.0, score), reasons


# --------------------------------------------------------------------------- #
# Stage 8b: the prosecutors
# --------------------------------------------------------------------------- #


def prosecute_year_mismatch(
    cand: Candidate, peers: Sequence[Candidate], ctx: TrialContext
) -> List[ProsecutorHit]:
    """The highest-priority prosecutor.

    Every Indian annual report prints two columns: this year and last year.  A
    candidate lifted from the prior-year column is not *wrong on the page* -- it
    is simply the answer to a different question -- and it is the single most
    common way a plausible-looking wrong number gets written.  So it is charged
    at a rate that a single hit can sink a candidate on its own.
    """
    p = ctx.cfg["prosecutors"]["year_mismatch"]
    hits: List[ProsecutorHit] = []

    if cand.year_label and cand.year_label != ctx.target_fy:
        hits.append(
            ProsecutorHit(
                prosecutor="year_mismatch",
                penalty=float(p["penalty"]),
                reason=(
                    f"value belongs to {cand.year_label} "
                    f"(prior-year column) but {ctx.target_fy} was requested"
                    if cand.is_prior_year_column
                    else f"value belongs to {cand.year_label}, not {ctx.target_fy}"
                ),
            )
        )
    elif not cand.year_resolved:
        hits.append(
            ProsecutorHit(
                prosecutor="year_mismatch",
                penalty=float(p["unlabelled_column_penalty"]),
                reason=(
                    "column year could not be read from the header; "
                    f"assumed {ctx.target_fy} from Indian current-year-first convention"
                ),
            )
        )
    return hits


def prosecute_conflicting_values(
    cand: Candidate, peers: Sequence[Candidate], ctx: TrialContext
) -> List[ProsecutorHit]:
    """Something else in the same report asserts a different number."""
    p = ctx.cfg["prosecutors"]["conflicting_values"]
    tol = float(p["relative_tolerance"])
    hits: List[ProsecutorHit] = []

    rivals = [
        c
        for c in peers
        if c is not cand
        and (c.year_label or ctx.target_fy) == (cand.year_label or ctx.target_fy)
        and c.value is not None
        and cand.value is not None
        and not same_value(c.value, cand.value, tol)
    ]
    if not rivals:
        return hits

    strongest = max(rivals, key=lambda c: (c.independent_sources, c.section_score))
    reason = (
        f"conflicting values {_fmt(cand.value)} (p{cand.page}, {cand.section.value}) "
        f"vs {_fmt(strongest.value)} (p{strongest.page}, {strongest.section.value})"
        f"; {len(rivals)} rival value(s) in total"
    )
    penalty = float(p["penalty"])

    # Being outvoted by better-corroborated evidence is worse than merely
    # disagreeing with something.
    if (strongest.independent_sources, strongest.section_score) > (
        cand.independent_sources,
        cand.section_score,
    ):
        penalty += float(p["minority_extra_penalty"])
        reason += " -- this candidate is the minority/weaker-sourced one"

    hits.append(
        ProsecutorHit(prosecutor="conflicting_values", penalty=penalty, reason=reason)
    )
    return hits


def prosecute_unit_mismatch(
    cand: Candidate, peers: Sequence[Candidate], ctx: TrialContext
) -> List[ProsecutorHit]:
    """Crore vs lakh vs million vs USD, and the dropped-decimal-point family."""
    p = ctx.cfg["prosecutors"]["unit_mismatch"]
    hits: List[ProsecutorHit] = []
    md = ctx.metric

    if cand.foreign_currency:
        hits.append(
            ProsecutorHit(
                prosecutor="unit_mismatch",
                penalty=float(p["foreign_currency_penalty"]),
                reason=(
                    f"value read from a foreign-currency table ('{cand.unit_as_printed}'); "
                    "the template is Rs. crore and no FX rate is available offline"
                ),
            )
        )

    if cand.scale_inferred and md.unit_type.value == "currency":
        hits.append(
            ProsecutorHit(
                prosecutor="unit_mismatch",
                penalty=float(p["implied_scale_penalty"]),
                reason="no unit caption near the value; crore assumed rather than read",
            )
        )

    if cand.value is not None and md.sane_range and not in_range(cand.value, md.sane_range):
        lo, hi = md.sane_range
        added_scale_hit = False
        # Is it exactly a scale error?  x1000 (lakh read as crore), /100, etc.
        for factor, label in ((0.01, "100x too large"), (100.0, "100x too small"),
                              (0.001, "1000x too large"), (1000.0, "1000x too small")):
            if in_range(cand.value * factor, md.sane_range):
                hits.append(
                    ProsecutorHit(
                        prosecutor="unit_mismatch",
                        penalty=float(p["penalty"]),
                        reason=(
                            f"{_fmt(cand.value)} is outside the sane range [{lo:g}, {hi:g}] "
                            f"but is exactly {label} -- the scale on this table "
                            f"('{cand.unit_as_printed or 'none printed'}') is probably wrong"
                        ),
                    )
                )
                added_scale_hit = True
                break

        # Even when not an exact scale factor, values outside sane ranges are
        # risky and should be heavily disfavored during ranking.
        if not added_scale_hit:
            hits.append(
                ProsecutorHit(
                    prosecutor="unit_mismatch",
                    penalty=float(p["penalty"]),
                    reason=(
                        f"{_fmt(cand.value)} is outside the sane range [{lo:g}, {hi:g}] "
                        f"for metric {md.key}"
                    ),
                )
            )

    if suspect_missing_decimal(cand.value, md.sane_range):
        hits.append(
            ProsecutorHit(
                prosecutor="unit_mismatch",
                penalty=float(p["penalty"]),
                reason=(
                    f"{_fmt(cand.value)} looks like {_fmt((cand.value or 0) / 100)} with a "
                    "dropped decimal point (OCR damage); not corrected automatically"
                ),
            )
        )
    return hits


def prosecute_table_alignment(
    cand: Candidate, peers: Sequence[Candidate], ctx: TrialContext
) -> List[ProsecutorHit]:
    """Wrong row, wrong column, off-by-one -- the silent killers."""
    p = ctx.cfg["prosecutors"]["table_alignment"]
    hits: List[ProsecutorHit] = []

    if cand.from_table and cand.row_label_score < float(p["fuzzy_row_label_threshold"]):
        hits.append(
            ProsecutorHit(
                prosecutor="table_alignment",
                penalty=float(p["penalty"]),
                reason=(
                    f"row label {cand.row_label!r} only matched alias "
                    f"{cand.alias_matched!r} at {cand.row_label_score:.0f}%; "
                    "the row may be misaligned or the label may belong to a sub-item"
                ),
            )
        )

    # A value taken from a column whose header we never read, sitting next to a
    # column whose header we *did* read, is the classic column-shift.
    if cand.from_table and not cand.year_resolved and cand.column_header:
        hits.append(
            ProsecutorHit(
                prosecutor="table_alignment",
                penalty=float(p["neighbour_column_penalty"]),
                reason=(
                    f"column header {cand.column_header!r} does not name a fiscal year; "
                    "the value may have come from the neighbouring column"
                ),
            )
        )

    # If most well-sourced candidates for this metric came from column i and this
    # one came from column i±1 of the same table, that is an off-by-one.
    same_table = [
        c
        for c in peers
        if c is not cand
        and c.table_id
        and c.table_id == cand.table_id
        and c.column_index is not None
        and cand.column_index is not None
        and c.year_resolved
        and not cand.year_resolved
        and abs(c.column_index - cand.column_index) == 1
    ]
    if same_table:
        hits.append(
            ProsecutorHit(
                prosecutor="table_alignment",
                penalty=float(p["neighbour_column_penalty"]),
                reason=(
                    f"an adjacent column of table {cand.table_id} has a properly "
                    f"labelled year; this column does not -- likely off-by-one"
                ),
            )
        )
    return hits


PROSECUTORS = (
    prosecute_year_mismatch,       # first: highest priority
    prosecute_conflicting_values,
    prosecute_unit_mismatch,
    prosecute_table_alignment,
)


# --------------------------------------------------------------------------- #
# Stage 8c: the judge
# --------------------------------------------------------------------------- #


def try_candidate(
    cand: Candidate, peers: Sequence[Candidate], ctx: TrialContext
) -> Verdict:
    """Run one candidate's full trial and return its (unscored) verdict."""
    defence, reasons = defend(cand, ctx)
    hits: List[ProsecutorHit] = []
    for prosecutor in PROSECUTORS:
        hits.extend(prosecutor(cand, peers, ctx))

    verdict = Verdict(
        candidate=cand,
        defence_score=defence,
        defence_reasons=reasons,
        prosecutor_hits=hits,
        court_score=defence - sum(h.penalty for h in hits),
        source_score=source_score(cand, ctx.cfg),
    )
    return verdict


def hold_trial(
    candidates: Sequence[Candidate], ctx: TrialContext
) -> List[Verdict]:
    """Try every candidate for one metric; return verdicts, best first.

    Deterministic ordering: court score, then independent sources, then source
    quality, then page number.  Never dict order, never insertion order.
    """
    if not candidates:
        return []
    verdicts = [try_candidate(c, candidates, ctx) for c in candidates]
    verdicts.sort(
        key=lambda v: (
            -v.court_score,
            -v.candidate.independent_sources,
            -v.source_score,
            v.candidate.page,
        )
    )
    if verdicts:
        top = verdicts[0]
        log.debug(
            "%s: winner %s (court %.1f, %d penalties)",
            ctx.metric.key,
            _fmt(top.candidate.value),
            top.court_score,
            len(top.prosecutor_hits),
        )
    return verdicts


def _fmt(value: Optional[float]) -> str:
    """Format a number for a human-readable audit reason."""
    if value is None:
        return "None"
    if float(value).is_integer():
        return f"{int(value)}"
    return f"{value:,.2f}"
