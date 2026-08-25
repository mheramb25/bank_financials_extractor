"""Stage 3: the page ranking engine.

A 400-page annual report contains maybe 25 pages that matter.  Scanning all 400
cell-by-cell is slow *and* dangerous -- it is exactly how a number from the
Chairman's letter ends up in a Balance Sheet cell.  So we score every page,
sort, and walk the report in priority order:

    Financial Statements > Financial Highlights > 10-Year Summary
    > Key Ratios / Basel III > MD&A > Narrative

Ranking is deterministic: ties break on page number, never on dict order.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from arx import load_config
from arx.models import Document, Page, Section
from arx.parse import SCHEDULE_NO, UNIT_CAPTION

log = logging.getLogger("arx.rank")

_NUMERIC_LINE = re.compile(r"\d[\d,\.]{2,}")
_MULTI_NUM_LINE = re.compile(r"(\d[\d,\.]{2,}\D+){2,}")


def table_density(page: Page) -> float:
    """Fraction of the page's non-empty lines that look like table rows (0..1).

    Two signals, either of which is sufficient: an actual extracted table, or a
    line carrying two or more separated numbers (the classic
    ``label   1,234.56   1,111.11`` shape of a two-year statement row).
    """
    lines = [l for l in (page.text or "").splitlines() if l.strip()]
    if not lines and not page.tables:
        return 0.0
    tabular = sum(1 for l in lines if _MULTI_NUM_LINE.search(l))
    line_density = tabular / len(lines) if lines else 0.0
    table_bonus = min(1.0, 0.35 * len(page.tables))
    return min(1.0, max(line_density, table_bonus))


def score_page(page: Page, cfg: Optional[dict] = None) -> float:
    """Score one page: section weight, plus table/unit/schedule evidence."""
    cfg = cfg or load_config()
    weights = cfg["section_weights"]
    rcfg = cfg["ranking"]

    base = float(weights.get(page.section.value, weights["unknown"]))
    # A propagated (0.5) label is worth less than a page with the heading on it.
    base *= 0.85 + 0.15 * min(1.0, page.section_score)

    score = base
    score += float(rcfg["table_density_weight"]) * table_density(page)
    if UNIT_CAPTION.search(page.text or ""):
        score += float(rcfg["unit_caption_bonus"])
    if SCHEDULE_NO.search(page.text or ""):
        score += float(rcfg["schedule_number_bonus"])

    # A page with no digits at all cannot contain a metric.
    if not _NUMERIC_LINE.search(page.text or "") and not page.tables:
        score *= 0.25

    return round(score, 6)


def rank_pages(doc: Document, cfg: Optional[dict] = None) -> List[Page]:
    """Score every page and return them in descending priority order.

    Also sets ``page.rank_score`` in place, so the audit trail can explain why a
    page was (or was not) visited.
    """
    cfg = cfg or load_config()
    rcfg = cfg["ranking"]
    for page in doc.pages:
        page.rank_score = score_page(page, cfg)

    ranked = sorted(
        doc.pages,
        key=lambda p: (-p.rank_score, p.number),  # deterministic tie-break
    )
    ranked = [p for p in ranked if p.rank_score >= float(rcfg["min_page_score"])]

    cap = int(rcfg.get("max_pages_visited") or 0)
    if cap:
        ranked = ranked[:cap]

    log.debug(
        "ranked %d/%d pages; top: %s",
        len(ranked),
        len(doc.pages),
        [(p.number, p.section.value, p.rank_score) for p in ranked[:5]],
    )
    return ranked


def scanned_pages_in(ranked: List[Page], cfg: Optional[dict] = None) -> List[int]:
    """The ranked pages that look scanned -- i.e. the only pages worth OCR'ing.

    This is what makes OCR lazy: a scanned page that ranks below the cut is never
    rendered at 300 DPI, and a text page is never OCR'd at all.
    """
    cfg = cfg or load_config()
    ocr_cfg = cfg["ocr"]
    return [
        p.number
        for p in ranked
        if p.char_count < int(ocr_cfg["scanned_char_threshold"])
        and p.image_area_ratio >= float(ocr_cfg["scanned_image_area_ratio"])
    ]


def section_quality(section: Section, cfg: Optional[dict] = None) -> float:
    """Stage 6: source-quality score of a section, in [0, 1]."""
    cfg = cfg or load_config()
    weights = cfg["section_weights"]
    return float(weights.get(section.value, weights["unknown"]))


def pages_by_section(doc: Document) -> Dict[str, List[int]]:
    """Debug helper: ``{section: [page numbers]}``."""
    out: Dict[str, List[int]] = {}
    for page in doc.pages:
        out.setdefault(page.section.value, []).append(page.number)
    return out
