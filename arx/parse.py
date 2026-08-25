"""Stages 1-2: parse the PDF, OCR only what is needed, identify the report.

Design notes
------------
* **pdfplumber** does the first pass (text, word boxes, tables) because it is
  pure-Python and never crashes the process on a malformed page.
* **camelot** (lattice *and* stream) is a *second* pass, run lazily and only on
  pages the ranking engine cares about.  Running camelot over a 400-page report
  would take minutes and buy nothing on the 350 pages of prose.
* **OCR** is lazier still: a page is only rendered and OCR'd if (a) it looks
  scanned and (b) it survived ranking.  OCR results are cached per
  ``(pdf sha256, page)`` so no page is ever OCR'd twice, across runs.
* The whole parsed :class:`~arx.models.Document` is cached under
  ``.cache/<sha256>/parse.joblib``, so a second run on the same PDF is
  near-instant.

Nothing in this module raises: a page that cannot be parsed becomes an empty
page and the batch continues.  One bad PDF must never kill the run.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import joblib
from rapidfuzz import fuzz

from arx import load_config, load_institutions
from arx.models import Document, InstitutionDef, Page, Section, Table
from arx.normalize import clean_text, normalize_name

log = logging.getLogger("arx.parse")

# --------------------------------------------------------------------------- #
# Fiscal-year regexes.  The Indian FY ending 31 March 2023 is FY22-23.
# --------------------------------------------------------------------------- #

_FY_RANGE = re.compile(
    r"(?i)\b(?:F\.?Y\.?|FY|Financial\s+Year|Fiscal(?:\s+Year)?)\s*[:\-]?\s*"
    r"(20\d{2})\s*[-–/]\s*(\d{2}|20\d{2})\b"
)
_BARE_RANGE = re.compile(r"\b(20\d{2})\s*[-–/]\s*(\d{2})\b")
_YEAR_ENDED = re.compile(
    r"(?i)\b(?:year|period)\s+ended\s+(?:on\s+)?(?:31(?:st)?\s+)?March\s*,?\s*(?:31\s*,?\s*)?(20\d{2})\b"
)
_AS_AT_MARCH = re.compile(
    r"(?i)\bas\s+(?:at|on)\s+(?:31(?:st)?|March\s*31)[\s,]*(?:March)?[\s,]*(20\d{2})\b"
)
_MARCH_31 = re.compile(r"(?i)\bMarch\s*31\s*,?\s*(20\d{2})\b|\b31[./-]03[./-](20\d{2})\b")

# --------------------------------------------------------------------------- #
# Section heading regexes (Stage 3 uses the labels; we detect them here so the
# label travels with the page through the cache).
# --------------------------------------------------------------------------- #

SECTION_PATTERNS: List[Tuple[Section, re.Pattern[str]]] = [
    (
        Section.FINANCIAL_STATEMENTS,
        re.compile(
            r"(?i)\b(balance\s+sheet|profit\s+and\s+loss\s+account|statement\s+of\s+profit"
            r"|schedules?\s+(?:forming\s+part|to\s+the\s+(?:accounts|financial))"
            r"|schedule\s+1[0-8]\b|schedule\s+[1-9]\b|notes?\s+to\s+(?:the\s+)?(?:accounts|financial\s+statements)"
            r"|cash\s+flow\s+statement|independent\s+auditors?.{0,3}\s+report)\b"
        ),
    ),
    (
        Section.FINANCIAL_HIGHLIGHTS,
        re.compile(
            r"(?i)\b(financial\s+highlights|performance\s+at\s+a\s+glance|at\s+a\s+glance"
            r"|key\s+performance\s+indicators|highlights\s+of\s+the\s+year|year\s+in\s+numbers)\b"
        ),
    ),
    (
        Section.MULTI_YEAR_SUMMARY,
        re.compile(
            r"(?i)\b((?:ten|10|five|5)[-\s]?years?\s+(?:financial\s+)?(?:summary|highlights|at\s+a\s+glance)"
            r"|decadal\s+(?:progress|summary)|progress\s+over\s+the\s+years)\b"
        ),
    ),
    (
        Section.KEY_RATIOS,
        re.compile(
            r"(?i)\b(key\s+(?:financial\s+)?ratios|basel\s*(?:iii|3)|pillar\s*[-\s]?3\s+disclosures?"
            r"|capital\s+adequacy|key\s+ratios|financial\s+ratios)\b"
        ),
    ),
    (
        Section.MDNA,
        re.compile(
            r"(?i)\b(management\s+discussion\s+and\s+analysis|md\s*&\s*a|business\s+review"
            r"|directors?.{0,3}\s+report|operational\s+review)\b"
        ),
    ),
    (
        Section.NARRATIVE,
        re.compile(
            r"(?i)\b(chairman.{0,3}s?\s+(?:letter|message|statement)|md\s*&\s*ceo.{0,3}s?\s+(?:letter|message)"
            r"|business\s+responsibility\s+and\s+sustainability|BRSR|corporate\s+social\s+responsibility"
            r"|esg|sustainability\s+report|our\s+people|awards\s+and\s+accolades)\b"
        ),
    ),
]

UNIT_CAPTION = re.compile(
    r"(?i)(?:\((?:\s*(?:₹|Rs\.?|INR)\s*)?(?:in\s+)?(?:crore|crores|lakh|lakhs|million|billion|thousand)s?\s*\)"
    r"|(?:₹|Rs\.?|INR)\s+in\s+(?:crore|lakh|million|billion|thousand)s?)"
)
SCHEDULE_NO = re.compile(r"(?i)\bschedule\s+(\d{1,2})\b")


# --------------------------------------------------------------------------- #
# Hashing / caching
# --------------------------------------------------------------------------- #


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    """Content hash of a file -- the cache key for everything about that PDF."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def cache_dir_for(sha: str, cfg: Optional[dict] = None) -> Path:
    cfg = cfg or load_config()
    d = Path(cfg["runtime"]["cache_dir"]) / sha
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# Stage 1: parsing
# --------------------------------------------------------------------------- #


def _dense_rows(rows: Sequence[Sequence[Optional[str]]]) -> List[List[str]]:
    """Normalise a raw extractor table into a dense list-of-lists of strings."""
    out: List[List[str]] = []
    for row in rows or []:
        out.append([clean_text(c) if c is not None else "" for c in row])
    return out


def _page_caption(text: str) -> str:
    """The first unit caption on the page, e.g. ``(Rs. in crore)``."""
    m = UNIT_CAPTION.search(text or "")
    return m.group(0) if m else ""


def _detect_section(text: str) -> Tuple[Section, float]:
    """Label a page by its headings.  Earlier patterns win (they are stronger)."""
    head = "\n".join((text or "").splitlines()[:12])  # headings live at the top
    body = text or ""
    for section, pat in SECTION_PATTERNS:
        if pat.search(head):
            return section, 1.0
    for section, pat in SECTION_PATTERNS:
        if pat.search(body):
            return section, 0.7
    return Section.UNKNOWN, 0.0


def _image_area_ratio(page) -> float:
    """Fraction of the page covered by raster images (0..1)."""
    try:
        page_area = float(page.width) * float(page.height)
        if page_area <= 0:
            return 0.0
        img_area = 0.0
        for im in page.images or []:
            w = abs(float(im.get("x1", 0)) - float(im.get("x0", 0)))
            h = abs(float(im.get("bottom", 0)) - float(im.get("top", 0)))
            img_area += w * h
        return min(1.0, img_area / page_area)
    except Exception:  # pragma: no cover - defensive
        return 0.0


def parse_pdf(
    path: str | Path,
    cfg: Optional[dict] = None,
    use_cache: bool = True,
) -> Document:
    """Parse a PDF into a :class:`Document` (text + pdfplumber tables + labels).

    Camelot and OCR are *not* run here -- they are lazy, page-targeted passes.
    """
    import pdfplumber  # imported lazily so the models/tests don't need it

    cfg = cfg or load_config()
    path = Path(path)
    sha = sha256_file(path)
    cache_file = cache_dir_for(sha, cfg) / "parse.joblib"

    if use_cache and cache_file.exists():
        try:
            doc: Document = joblib.load(cache_file)
            log.debug("parse cache hit for %s", path.name)
            return doc
        except Exception as exc:  # pragma: no cover - corrupt cache
            log.warning("parse cache unreadable (%s); reparsing", exc)

    pages: List[Page] = []
    with pdfplumber.open(str(path)) as pdf:
        for idx, pp in enumerate(pdf.pages, start=1):
            try:
                text = pp.extract_text() or ""
            except Exception as exc:
                log.warning("%s p%d: text extraction failed (%s)", path.name, idx, exc)
                text = ""
            try:
                raw_tables = pp.extract_tables() or []
            except Exception as exc:
                log.warning("%s p%d: table extraction failed (%s)", path.name, idx, exc)
                raw_tables = []

            tables = [
                Table(
                    table_id=f"p{idx}-plumber-{t_i}",
                    page=idx,
                    rows=_dense_rows(rows),
                    source="pdfplumber",
                    caption=_page_caption(text),
                )
                for t_i, rows in enumerate(raw_tables)
                if rows
            ]
            section, sscore = _detect_section(text)
            pages.append(
                Page(
                    number=idx,
                    text=text,
                    tables=tables,
                    char_count=len(text.strip()),
                    image_area_ratio=_image_area_ratio(pp),
                    width=float(pp.width or 0),
                    height=float(pp.height or 0),
                    section=section,
                    section_score=sscore,
                )
            )
            pp.flush_cache()

    doc = Document(path=str(path), sha256=sha, pages=pages)
    _propagate_sections(doc)
    identify(doc)

    if use_cache:
        try:
            joblib.dump(doc, cache_file)
        except Exception as exc:  # pragma: no cover
            log.warning("could not write parse cache: %s", exc)
    return doc


def _propagate_sections(doc: Document) -> None:
    """A section heading on page N labels pages N+1... until the next heading.

    Annual reports print the heading once and then run for 30 pages.  Without
    this, page 2 of the Balance Sheet would be scored as ``unknown``.
    """
    current = Section.UNKNOWN
    for page in doc.pages:
        if page.section_score >= 1.0:
            current = page.section
        elif page.section == Section.UNKNOWN and current != Section.UNKNOWN:
            page.section = current
            page.section_score = 0.5


# --------------------------------------------------------------------------- #
# Stage 1b: lazy camelot pass
# --------------------------------------------------------------------------- #


def enrich_tables_with_camelot(
    doc: Document, pages: Iterable[int], cfg: Optional[dict] = None
) -> None:
    """Add camelot lattice + stream tables for the given pages, in place.

    Both flavours are kept -- lattice is right when the table is ruled, stream
    is right when it is whitespace-aligned, and neither is reliably right.  The
    candidates they produce are reconciled by the courtroom, not here.
    """
    try:
        import camelot  # noqa: F401
    except Exception as exc:
        log.info("camelot unavailable (%s); pdfplumber tables only", exc)
        return

    import camelot

    wanted = sorted({int(p) for p in pages})
    if not wanted:
        return
    pages_arg = ",".join(str(p) for p in wanted)

    for flavor in ("lattice", "stream"):
        try:
            kwargs = {"backend": "poppler"} if flavor == "lattice" else {}
            tables = camelot.read_pdf(doc.path, pages=pages_arg, flavor=flavor, **kwargs)
        except Exception as exc:
            log.info("camelot %s failed on %s: %s", flavor, Path(doc.path).name, exc)
            continue
        for t_i, t in enumerate(tables):
            try:
                page_no = int(t.parsing_report.get("page", 0))
            except Exception:
                continue
            page = doc.page(page_no)
            if page is None:
                continue
            rows = _dense_rows(t.df.values.tolist())
            if not rows:
                continue
            page.tables.append(
                Table(
                    table_id=f"p{page_no}-camelot-{flavor}-{t_i}",
                    page=page_no,
                    rows=rows,
                    source=f"camelot-{flavor}",
                    caption=_page_caption(page.text),
                )
            )


# --------------------------------------------------------------------------- #
# Stage 1c: lazy OCR
# --------------------------------------------------------------------------- #


def ocr_pages(
    doc: Document, pages: Iterable[int], cfg: Optional[dict] = None
) -> List[int]:
    """OCR the given pages (only those that look scanned), in place.

    Returns the page numbers that were actually OCR'd.  Per-page OCR text is
    cached on disk under the PDF's sha, so re-runs never repeat the work.
    """
    cfg = cfg or load_config()
    ocr_cfg = cfg["ocr"]
    if not ocr_cfg.get("enabled", True):
        return []

    targets = [
        p
        for p in sorted({int(x) for x in pages})
        if (page := doc.page(p)) is not None
        and page.char_count < int(ocr_cfg["scanned_char_threshold"])
        and page.image_area_ratio >= float(ocr_cfg["scanned_image_area_ratio"])
        and not page.ocr_used
    ][: int(ocr_cfg["max_pages"])]

    if not targets:
        return []

    cache = cache_dir_for(doc.sha256, cfg) / "ocr"
    cache.mkdir(parents=True, exist_ok=True)

    done: List[int] = []
    for page_no in targets:
        page = doc.page(page_no)
        if page is None:
            continue
        cache_file = cache / f"{page_no}.txt"
        if cache_file.exists():
            text = cache_file.read_text(encoding="utf-8")
        else:
            text = _ocr_one_page(doc.path, page_no, ocr_cfg)
            if text is None:
                continue
            try:
                cache_file.write_text(text, encoding="utf-8")
            except Exception:  # pragma: no cover
                pass
        page.text = text
        page.char_count = len(text.strip())
        page.ocr_used = True
        section, sscore = _detect_section(text)
        if sscore > page.section_score:
            page.section, page.section_score = section, sscore
        done.append(page_no)

    if done:
        log.info("OCR'd %d page(s) of %s", len(done), Path(doc.path).name)
    return done


def _ocr_one_page(pdf_path: str, page_no: int, ocr_cfg: dict) -> Optional[str]:
    """Render one page at ``dpi`` and OCR it. Returns None on any failure."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except Exception as exc:
        log.warning("OCR stack unavailable (%s)", exc)
        return None
    try:
        images = convert_from_path(
            pdf_path,
            dpi=int(ocr_cfg["dpi"]),
            first_page=page_no,
            last_page=page_no,
        )
        if not images:
            return None
        # English only: the Devanagari column in a bilingual report is a mirror
        # of the English one, and mixing scripts wrecks digit recognition.
        return pytesseract.image_to_string(images[0], lang=str(ocr_cfg["lang"]))
    except Exception as exc:
        log.warning("OCR failed on p%d of %s: %s", page_no, Path(pdf_path).name, exc)
        return None


# --------------------------------------------------------------------------- #
# Stage 2: identification
# --------------------------------------------------------------------------- #


def identify(doc: Document, cfg: Optional[dict] = None) -> Document:
    """Fill in ``institution``, ``category``, ``inst_type`` and ``fiscal_year``."""
    identify_institution(doc)
    identify_fiscal_year(doc)
    return doc


def _front_matter(doc: Document, n: int = 6) -> str:
    """Cover page + first few pages: where the name is printed largest."""
    return "\n".join(p.text for p in doc.pages[:n])


def _running_headers(doc: Document, sample: int = 40) -> str:
    """First two lines of a sample of pages -- the running header band."""
    lines: List[str] = []
    for page in doc.pages[:sample]:
        lines.extend((page.text or "").splitlines()[:2])
    return "\n".join(lines)


def _auditor_pages(doc: Document) -> str:
    """The auditor's report always names the entity in full, unambiguously."""
    chunks = []
    pat = re.compile(r"(?i)independent\s+auditors?.{0,3}\s+report|to\s+the\s+members\s+of")
    for page in doc.pages:
        if pat.search(page.text or ""):
            chunks.append(page.text)
        if len(chunks) >= 3:
            break
    return "\n".join(chunks)


def identify_institution(
    doc: Document,
    institutions: Optional[List[InstitutionDef]] = None,
) -> Tuple[Optional[str], float]:
    """Match the report against the alias table.

    Signals, in descending strength: CIN (exact, unique) > full legal name on
    the cover > alias in the auditor's report > alias in the running headers.
    A short alias like ``SBI`` only counts as a word-boundary match, so it can
    never fire on ``SBICARD``.
    """
    institutions = institutions or load_institutions()
    cover = _front_matter(doc)
    headers = _running_headers(doc)
    auditor = _auditor_pages(doc)
    haystacks = {"cover": cover, "auditor": auditor, "headers": headers}
    weights = {"cover": 1.0, "auditor": 0.9, "headers": 0.7}

    best: Optional[InstitutionDef] = None
    best_score = 0.0

    for inst in institutions:
        score = 0.0
        # CIN is decisive.
        if inst.cin:
            for text in haystacks.values():
                if inst.cin.lower() in (text or "").lower():
                    score = max(score, 100.0)
        for where, text in haystacks.items():
            if not text:
                continue
            norm = normalize_name(text)
            for alias in [inst.canonical] + inst.aliases:
                a = normalize_name(alias)
                if not a:
                    continue
                if re.search(rf"\b{re.escape(a)}\b", norm):
                    # Longer aliases are more specific, hence more trustworthy.
                    specificity = min(1.0, 0.55 + 0.05 * len(a.split()))
                    score = max(score, 90.0 * weights[where] * specificity)
                else:
                    ratio = fuzz.partial_ratio(a, norm[:4000])
                    if ratio >= 95 and len(a) >= 12:
                        score = max(score, 0.75 * ratio * weights[where])
        if inst.ticker and re.search(
            rf"\b{re.escape(inst.ticker)}\b", cover or "", re.IGNORECASE
        ):
            score += 5.0
        if score > best_score:
            best, best_score = inst, score

    if best and best_score >= 45.0:
        doc.institution = best.canonical
        doc.category = best.category
        doc.inst_type = best.type
        doc.institution_confidence = min(100.0, best_score)
    else:
        # Unknown institution: fall back to the PDF's own title text so the run
        # still produces an auditable row, but flag low confidence.
        guess = _guess_name_from_cover(cover) or Path(doc.path).stem
        doc.institution = guess
        doc.category = "NBFC" if re.search(r"(?i)\bfinance\b", guess) else "Private Sector Bank"
        doc.inst_type = "nbfc" if re.search(r"(?i)\bfinance\b", guess) else "bank"
        doc.institution_confidence = float(best_score)
        log.warning(
            "institution not in institutions.yaml; guessed %r (score %.0f) for %s",
            guess,
            best_score,
            Path(doc.path).name,
        )
    return doc.institution, doc.institution_confidence


def _guess_name_from_cover(cover: str) -> Optional[str]:
    """Last resort: the first line that looks like a company name."""
    for line in (cover or "").splitlines():
        line = clean_text(line)
        if 6 <= len(line) <= 70 and re.search(
            r"(?i)\b(bank|finance|financial|corporation|limited|ltd)\b", line
        ):
            return line
    return None


def fy_label(end_year: int) -> str:
    """FY ending 31 March ``end_year`` -> the template sheet name.

    >>> fy_label(2023)
    'FY22-23'
    """
    return f"FY{str(end_year - 1)[2:]}-{str(end_year)[2:]}"


def fy_end_year(label: str) -> Optional[int]:
    """``'FY22-23'`` -> ``2023``."""
    m = re.fullmatch(r"(?i)FY\s*(\d{2})\s*-\s*(\d{2})", (label or "").strip())
    if not m:
        return None
    return 2000 + int(m.group(2))


def year_tokens_for(end_year: int) -> List[str]:
    """Every string a table column header might use for this fiscal year."""
    start = end_year - 1
    y2 = str(end_year)[2:]
    s2 = str(start)[2:]
    return [
        str(end_year),
        f"{start}-{y2}",
        f"{start}-{end_year}",
        f"{start}/{y2}",
        f"FY{y2}",
        f"FY {start}-{y2}",
        f"FY{start}-{y2}",
        f"31.03.{end_year}",
        f"31/03/{end_year}",
        f"31-03-{end_year}",
        f"March 31, {end_year}",
        f"March {end_year}",
        f"31st March {end_year}",
        f"31 March {end_year}",
        f"Mar-{y2}",
        f"Mar {y2}",
    ]


def _candidate_end_years(text: str) -> List[int]:
    """All fiscal-year end-years asserted anywhere in ``text``."""
    years: List[int] = []
    for m in _FY_RANGE.finditer(text):
        tail = m.group(2)
        years.append(int(tail) if len(tail) == 4 else 2000 + int(tail))
    for m in _YEAR_ENDED.finditer(text):
        years.append(int(m.group(1)))
    for m in _AS_AT_MARCH.finditer(text):
        years.append(int(m.group(1)))
    for m in _MARCH_31.finditer(text):
        years.append(int(m.group(1) or m.group(2)))
    for m in _BARE_RANGE.finditer(text):
        years.append(2000 + int(m.group(2)))
    return [y for y in years if 1990 <= y <= 2100]


def identify_fiscal_year(doc: Document) -> Tuple[Optional[str], float]:
    """Resolve the report's fiscal year, preferring the *statements* over the art.

    The cover of an FY22-23 report frequently shouts "2023" in a logo, and some
    covers shout the *publication* year (2023-24) instead.  So the balance sheet
    heading -- ``as at March 31, 2023`` -- is the arbiter, and the cover is only
    a tie-breaker.  ``prior_fiscal_year`` is the previous year, always present as
    the second column of every statement.
    """
    stmt_text = "\n".join(
        p.text
        for p in doc.pages
        if p.section
        in (Section.FINANCIAL_STATEMENTS, Section.FINANCIAL_HIGHLIGHTS, Section.KEY_RATIOS)
    )
    votes: Dict[int, float] = {}

    for year in _candidate_end_years(stmt_text):
        votes[year] = votes.get(year, 0.0) + 3.0  # statements: heavy weight
    for year in _candidate_end_years(_front_matter(doc)):
        votes[year] = votes.get(year, 0.0) + 1.0  # cover: light weight
    for year in _candidate_end_years(_running_headers(doc)):
        votes[year] = votes.get(year, 0.0) + 0.5

    if not votes:
        doc.fy_confidence = 0.0
        return None, 0.0

    total = sum(votes.values())
    end_year = max(votes, key=lambda y: (votes[y], y))
    confidence = 100.0 * votes[end_year] / total

    doc.fiscal_year = fy_label(end_year)
    doc.prior_fiscal_year = fy_label(end_year - 1)
    doc.fy_confidence = confidence
    doc.year_tokens = {
        doc.fiscal_year: year_tokens_for(end_year),
        doc.prior_fiscal_year: year_tokens_for(end_year - 1),
    }
    return doc.fiscal_year, confidence
