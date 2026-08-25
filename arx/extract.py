"""Stages 4-5: candidate generation and evidence collection.

The single most important rule in this file:

    **Extract every possible value. Never pick one here.**

Picking a value at extraction time is how a wrong number gets into a cell: the
extractor has no idea whether the column it grabbed was this year or last year,
whether the caption said crore or lakh, or whether the row label was off by one.
So we emit *candidates*, richly annotated with everything the courtroom will
need in order to convict or acquit them, and we let Stage 8 decide.

Two generators:

* :func:`candidates_from_table` -- the good one. Row label -> metric alias,
  column header -> fiscal year, table caption -> unit scale.
* :func:`candidates_from_text` -- the fallback, for numbers that only ever appear
  in a sentence ("...our CASA ratio stood at 42.3%..."). Scored much lower.

Then :func:`collect_evidence` (Stage 5/7) groups agreeing candidates and attaches
*independent* corroboration -- deduplicated by ``(section, table_id)``, so ten
mentions on one Highlights page count once, not ten times.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rapidfuzz import fuzz

from arx import load_config, load_metrics
from arx.models import Candidate, Document, Evidence, MetricDef, Page, Section, Table
from arx.normalize import (
    ScaleInfo,
    clean_text,
    detect_scale,
    is_nil,
    parse_number_full,
    same_value,
    to_crore,
)
from arx.rank import section_quality

log = logging.getLogger("arx.extract")

_YEARISH = re.compile(r"(?i)(20\d{2}|FY\s?\d{2}|Mar(?:ch)?[\s\-]*\d{2,4}|\d{2}\s*-\s*\d{2})")
_HAS_DIGIT = re.compile(r"\d")
_PURE_LABEL = re.compile(r"[A-Za-z]{3,}")

# A cell that is nothing but a year is a header, not a value.
_ONLY_YEAR = re.compile(r"^\s*(?:FY\s*)?20\d{2}\s*(?:[-/]\s*\d{2,4})?\s*$")


# --------------------------------------------------------------------------- #
# Alias compilation
# --------------------------------------------------------------------------- #


class CompiledMetric:
    """A :class:`MetricDef` with its alias regexes pre-compiled."""

    __slots__ = ("md", "patterns")

    def __init__(self, md: MetricDef) -> None:
        self.md = md
        self.patterns: List[Tuple[str, re.Pattern[str]]] = []
        for alias in md.aliases:
            try:
                self.patterns.append((alias, re.compile(alias, re.IGNORECASE)))
            except re.error as exc:  # pragma: no cover - bad user regex
                log.error("bad alias regex %r for %s: %s", alias, md.key, exc)

    def match_label(self, label: str) -> Tuple[Optional[str], float]:
        """Match a row label against this metric's aliases.

        Returns ``(alias, score)`` where score is 100 for a clean regex hit and a
        rapidfuzz partial ratio (0-100) for a fuzzy fallback.  The fuzzy score is
        what the table-alignment prosecutor uses to decide the row label was
        probably misread or misaligned.
        """
        text = clean_text(label)
        if not text:
            return None, 0.0
        for alias, pat in self.patterns:
            if pat.search(text):
                # Reward a label that is *only* the metric name; punish one that
                # buries it in a longer phrase ("Interest Earned on Investments").
                excess = max(0, len(text) - len(pat.search(text).group(0)))
                score = 100.0 if excess <= 3 else max(70.0, 100.0 - 1.5 * excess)
                return alias, score
        best_alias, best = None, 0.0
        plain = [re.sub(r"[\\^$.|?*+()\[\]{}]", " ", a) for a in self.md.aliases]
        for alias, p in zip(self.md.aliases, plain):
            r = fuzz.partial_ratio(clean_text(p).lower(), text.lower())
            if r > best:
                best_alias, best = alias, float(r)
        if best >= 90.0:
            return best_alias, best
        return None, best


def compile_metrics(metrics: Optional[Sequence[MetricDef]] = None) -> List[CompiledMetric]:
    """Compile the metric dictionary once per process."""
    return [CompiledMetric(m) for m in (metrics or load_metrics())]


def applicable_metrics(
    inst_type: str, metrics: Optional[Sequence[MetricDef]] = None
) -> List[MetricDef]:
    """The metrics that mean anything for this institution type."""
    return [m for m in (metrics or load_metrics()) if m.applies_to(inst_type)]


# --------------------------------------------------------------------------- #
# Table geometry: which column is which year?
# --------------------------------------------------------------------------- #


def _column_year_map(
    table: Table, year_tokens: Dict[str, List[str]]
) -> Tuple[Dict[int, str], Dict[int, str], int]:
    """Map column index -> fiscal-year label, using the table's header rows.

    Returns ``(col_to_fy, col_to_header, header_row_index)``.  Columns whose year
    could not be established are simply absent from ``col_to_fy`` -- the caller
    turns that into a year-mismatch penalty rather than a guess.
    """
    col_to_fy: Dict[int, str] = {}
    col_to_header: Dict[int, str] = {}
    header_row = -1

    norm_tokens = {
        fy: [t.lower().replace(" ", "") for t in toks] for fy, toks in year_tokens.items()
    }

    for r_i, row in enumerate(table.rows[:8]):
        hits = 0
        for c_i, cell in enumerate(row):
            cell_t = clean_text(cell)
            if not cell_t:
                continue
            flat = cell_t.lower().replace(" ", "")
            matched_fy = None
            for fy, toks in norm_tokens.items():
                if any(tok and tok in flat for tok in toks):
                    matched_fy = fy
                    break
            if matched_fy:
                col_to_fy[c_i] = matched_fy
                col_to_header[c_i] = cell_t
                hits += 1
            elif _YEARISH.search(cell_t):
                col_to_header.setdefault(c_i, cell_t)
        if hits:
            header_row = r_i
            break

    return col_to_fy, col_to_header, header_row


def _numeric_columns(table: Table, start_row: int) -> List[int]:
    """Columns that mostly hold numbers -- the value columns of the table."""
    counts: Dict[int, int] = defaultdict(int)
    totals: Dict[int, int] = defaultdict(int)
    for row in table.rows[start_row:]:
        for c_i, cell in enumerate(row):
            t = clean_text(cell)
            if not t:
                continue
            totals[c_i] += 1
            if _HAS_DIGIT.search(t) and not _ONLY_YEAR.match(t):
                counts[c_i] += 1
    return sorted(
        c for c, n in counts.items() if totals[c] and n / totals[c] >= 0.5
    )


def _row_label(row: Sequence[str]) -> Tuple[str, int]:
    """The row's label: the first cell that has letters and no leading number."""
    for c_i, cell in enumerate(row):
        t = clean_text(cell)
        if t and _PURE_LABEL.search(t) and not re.match(r"^[\d,\.\(\)\-]+$", t):
            return t, c_i
    return "", -1


def _table_scale(table: Table, page: Page) -> ScaleInfo:
    """Scale for this table: its own caption first, then the page's."""
    for source in (table.caption, "\n".join(" ".join(r) for r in table.rows[:3]), page.text[:600]):
        info = detect_scale(source)
        if not info.inferred or info.foreign_currency:
            return info
    return detect_scale("")


# --------------------------------------------------------------------------- #
# Stage 4a: candidates from tables
# --------------------------------------------------------------------------- #


def candidates_from_table(
    table: Table,
    page: Page,
    doc: Document,
    compiled: Sequence[CompiledMetric],
    cfg: Optional[dict] = None,
) -> List[Candidate]:
    """Every (metric, value) pair this table could possibly be asserting."""
    cfg = cfg or load_config()
    out: List[Candidate] = []
    if not table.rows:
        return out

    col_to_fy, col_to_header, header_row = _column_year_map(table, doc.year_tokens)
    body_start = header_row + 1 if header_row >= 0 else 0
    num_cols = _numeric_columns(table, body_start)
    scale = _table_scale(table, page)
    squality = section_quality(page.section, cfg)

    # Fallback year mapping.  Indian statements are printed current-year-first,
    # so when the header carries no year we *assume* [current, prior] -- but we
    # mark year_resolved=False, and the year prosecutor charges for it.  We do
    # not silently trust the assumption; we make it visible and expensive.
    assumed: Dict[int, str] = {}
    assumed_resolved: set[int] = set()
    if not col_to_fy and doc.fiscal_year and len(num_cols) >= 1:
        assumed[num_cols[0]] = doc.fiscal_year
        # If there is only one numeric column, it is usually a single-year table.
        # Treating it as unresolved creates false ND decisions with no real benefit.
        if len(num_cols) == 1:
            assumed_resolved.add(num_cols[0])
        if len(num_cols) >= 2 and doc.prior_fiscal_year:
            assumed[num_cols[1]] = doc.prior_fiscal_year

    for r_i, row in enumerate(table.rows[body_start:], start=body_start):
        label, label_col = _row_label(row)
        if not label:
            continue
        label_norm = clean_text(label).lower().strip()
        for cm in compiled:
            if not cm.md.applies_to(doc.inst_type):
                continue
            alias, label_score = cm.match_label(label)
            if not alias:
                continue

            # A bare "Total" row is highly ambiguous and often causes row-shift
            # pollution (same number copied into many unrelated metrics).
            if label_norm in {"total", "grand total"} and cm.md.key not in {
                "total_assets",
                "total_deposits",
                "gross_advances",
                "net_worth",
            }:
                continue

            for c_i, cell in enumerate(row):
                if c_i == label_col or not clean_text(cell):
                    continue
                if c_i not in num_cols and c_i not in col_to_fy:
                    continue

                if cm.md.unit_type.value == "text":
                    text_val = clean_text(cell)
                    if not text_val or is_nil(text_val) or _ONLY_YEAR.match(text_val):
                        continue
                    if not _PURE_LABEL.search(text_val):
                        continue
                    value, pnum = None, None
                else:
                    pnum = parse_number_full(cell)
                    if pnum.value is None or pnum.is_nil:
                        continue
                    if _ONLY_YEAR.match(clean_text(cell)):
                        continue
                    value = _apply_scale(pnum.value, cm.md, scale)
                    text_val = None

                fy = col_to_fy.get(c_i) or assumed.get(c_i)
                resolved = c_i in col_to_fy or c_i in assumed_resolved

                out.append(
                    Candidate(
                        metric=cm.md.key,
                        value=value,
                        text_value=text_val,
                        raw_text=clean_text(cell),
                        page=page.number,
                        section=page.section,
                        section_score=squality,
                        year_label=fy,
                        year_resolved=resolved,
                        is_prior_year_column=(fy == doc.prior_fiscal_year),
                        unit_as_printed=scale.printed or ("%" if cm.md.unit_type.value == "percent" else ""),
                        scale_multiplier=scale.multiplier,
                        scale_inferred=scale.inferred and cm.md.unit_type.value == "currency",
                        foreign_currency=scale.foreign_currency,
                        alias_matched=alias,
                        alias_exact=label_score >= 100.0,
                        row_label=label,
                        row_label_score=label_score,
                        column_header=col_to_header.get(c_i, ""),
                        column_index=c_i,
                        table_id=table.table_id,
                        context=_row_context(table, r_i),
                        from_table=True,
                    )
                )
    return out


def _apply_scale(raw: float, md: MetricDef, scale: ScaleInfo) -> float:
    """Currency values are converted to crore; everything else is taken as-is."""
    if md.unit_type.value == "currency":
        return to_crore(raw, scale)
    return raw


def _row_context(table: Table, r_i: int) -> str:
    """The row plus its neighbours -- what a human would look at to check."""
    lo, hi = max(0, r_i - 1), min(len(table.rows), r_i + 2)
    return " | ".join(" ".join(c for c in row if c) for row in table.rows[lo:hi])[:400]


# --------------------------------------------------------------------------- #
# Stage 4b: candidates from prose
# --------------------------------------------------------------------------- #


def candidates_from_text(
    page: Page,
    doc: Document,
    compiled: Sequence[CompiledMetric],
    cfg: Optional[dict] = None,
) -> List[Candidate]:
    """Numbers stated in sentences: the fallback source, deliberately weak.

    Only fires when the number sits within ~90 characters *after* the alias, on
    the same line, which is how these sentences are actually written:
    ``"...CASA ratio stood at 42.3% as at March 31, 2023..."``
    """
    cfg = cfg or load_config()
    out: List[Candidate] = []
    lines = (page.text or "").splitlines()
    squality = section_quality(page.section, cfg)
    page_scale = detect_scale(page.text[:800] if page.text else "")

    for i, line in enumerate(lines):
        line_c = clean_text(line)
        if not line_c or not _HAS_DIGIT.search(line_c):
            continue
        for cm in compiled:
            if not cm.md.applies_to(doc.inst_type):
                continue
            if cm.md.unit_type.value == "text":
                continue
            for alias, pat in cm.patterns:
                m = pat.search(line_c)
                if not m:
                    continue
                tail = line_c[m.end() : m.end() + 90]
                nm = re.search(
                    r"[-(]?\s*\d[\d,\.]*\s*\)?\s*"
                    r"(?:%|per\s*cent|crore|crores|lakh|lakhs|million|billion|bn|mn)?",
                    tail,
                )
                if not nm:
                    continue
                token = nm.group(0)
                pnum = parse_number_full(token)
                if pnum.value is None or pnum.is_nil:
                    continue
                scale = detect_scale(token)
                if scale.inferred:
                    scale = page_scale
                value = _apply_scale(pnum.value, cm.md, scale)

                # Which year is the sentence talking about?  Only trust an
                # explicit statement; otherwise leave it unresolved.
                fy = None
                resolved = False
                for label, toks in doc.year_tokens.items():
                    if any(t.lower() in line_c.lower() for t in toks):
                        fy, resolved = label, True
                        break
                if fy is None:
                    fy = doc.fiscal_year  # assumed, and charged for

                out.append(
                    Candidate(
                        metric=cm.md.key,
                        value=value,
                        raw_text=token.strip(),
                        page=page.number,
                        section=page.section,
                        section_score=squality,
                        year_label=fy,
                        year_resolved=resolved,
                        is_prior_year_column=(fy == doc.prior_fiscal_year),
                        unit_as_printed=scale.printed,
                        scale_multiplier=scale.multiplier,
                        scale_inferred=scale.inferred and cm.md.unit_type.value == "currency",
                        foreign_currency=scale.foreign_currency,
                        alias_matched=alias,
                        alias_exact=True,
                        row_label=m.group(0),
                        row_label_score=100.0,
                        column_header="",
                        table_id=None,
                        context=" ".join(lines[max(0, i - 3) : i + 4])[:400],
                        from_table=False,
                    )
                )
                break  # one candidate per (metric, line)
    return out


# --------------------------------------------------------------------------- #
# Stage 4: driver
# --------------------------------------------------------------------------- #


def generate_candidates(
    doc: Document,
    pages: Optional[Iterable[Page]] = None,
    compiled: Optional[Sequence[CompiledMetric]] = None,
    cfg: Optional[dict] = None,
) -> Dict[str, List[Candidate]]:
    """Run both generators over the (ranked) pages. ``{metric_key: [Candidate]}``."""
    cfg = cfg or load_config()
    compiled = compiled or compile_metrics()
    pages = list(pages if pages is not None else doc.pages)

    pool: Dict[str, List[Candidate]] = defaultdict(list)
    for page in pages:
        for table in page.tables:
            for cand in candidates_from_table(table, page, doc, compiled, cfg):
                pool[cand.metric].append(cand)
        for cand in candidates_from_text(page, doc, compiled, cfg):
            pool[cand.metric].append(cand)

    for key, cands in pool.items():
        log.debug("%s: %d raw candidates", key, len(cands))
    return dict(pool)


# --------------------------------------------------------------------------- #
# Stage 5 + 7: evidence collection with independence de-duplication
# --------------------------------------------------------------------------- #


def collect_evidence(
    pool: Dict[str, List[Candidate]],
    cfg: Optional[dict] = None,
) -> Dict[str, List[Candidate]]:
    """Attach corroborating evidence to every candidate, then de-duplicate.

    Two candidates corroborate each other when they claim the same metric, the
    same fiscal year, and the same value (within the conflict tolerance).  The
    corroboration is only *worth* something if it is independent -- a different
    ``(section, table_id)``.  Ten repeats of PAT on one Highlights page collapse
    to a single Evidence entry; PAT in Highlights + P&L + Notes gives three.

    Returns a pool in which each (metric, year, value) group is represented by
    its single strongest candidate, carrying all of the group's evidence.
    """
    cfg = cfg or load_config()
    tol = float(cfg["prosecutors"]["conflicting_values"]["relative_tolerance"])
    out: Dict[str, List[Candidate]] = {}

    for metric, cands in pool.items():
        groups: List[List[Candidate]] = []
        for cand in cands:
            for group in groups:
                head = group[0]
                if head.year_label != cand.year_label:
                    continue
                if head.text_value is not None or cand.text_value is not None:
                    if head.text_value == cand.text_value:
                        group.append(cand)
                        break
                    continue
                if same_value(head.value, cand.value, tol):
                    group.append(cand)
                    break
            else:
                groups.append([cand])

        representatives: List[Candidate] = []
        for group in groups:
            # The best-sourced member speaks for the group: highest section
            # quality, then a table over prose, then an exact alias, then the
            # earliest page (deterministic).
            group.sort(
                key=lambda c: (
                    -c.section_score,
                    not c.from_table,
                    not c.year_resolved,
                    not c.alias_exact,
                    c.page,
                )
            )
            rep = group[0].model_copy(deep=True)

            seen = {(rep.section.value, rep.table_id or f"text-p{rep.page}")}
            for other in group[1:]:
                key = (other.section.value, other.table_id or f"text-p{other.page}")
                if key in seen:
                    continue  # Stage 7: repeats inside one section score nothing
                seen.add(key)
                rep.evidence.append(
                    Evidence(
                        page=other.page,
                        section=other.section,
                        table_id=other.table_id,
                        alias_matched=other.alias_matched,
                        snippet=other.context[:180],
                        value=other.value,
                    )
                )
            representatives.append(rep)

        representatives.sort(key=lambda c: (-c.section_score, c.page))
        out[metric] = representatives
        log.debug(
            "%s: %d candidates -> %d distinct values",
            metric,
            len(cands),
            len(representatives),
        )
    return out
