"""Pydantic models shared by every stage of the pipeline.

The models are deliberately *dumb* containers: all behaviour lives in the stage
modules.  This keeps them picklable (needed for ``ProcessPoolExecutor`` and for
the joblib parse cache) and makes them trivial to construct in tests without a
real PDF.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class Section(str, Enum):
    """Report section labels, in descending order of trustworthiness."""

    FINANCIAL_STATEMENTS = "financial_statements"
    FINANCIAL_HIGHLIGHTS = "financial_highlights"
    MULTI_YEAR_SUMMARY = "multi_year_summary"
    KEY_RATIOS = "key_ratios"
    MDNA = "mdna"
    NARRATIVE = "narrative"
    UNKNOWN = "unknown"


class Decision(str, Enum):
    """Final disposition of a cell (Stage 15 bands)."""

    AUTO = "Auto"
    HIGH = "High"
    MANUAL = "Manual"
    REJECT = "Reject"
    NOT_APPLICABLE = "NA"


class UnitType(str, Enum):
    CURRENCY = "currency"
    PERCENT = "percent"
    RATIO = "ratio"
    COUNT = "count"
    TEXT = "text"


# --------------------------------------------------------------------------- #
# Metric dictionary (loaded from metrics.yaml)
# --------------------------------------------------------------------------- #


class MetricDef(BaseModel):
    """One row of ``metrics.yaml``."""

    key: str
    excel_header: str
    column: int
    group: str
    aliases: List[str]
    unit_type: UnitType
    applicable_to: List[str]
    tier: str = "B"
    sane_range: Optional[Tuple[float, float]] = None
    derivable_from: Optional[str] = None
    allow_negative: bool = False

    def applies_to(self, inst_type: str) -> bool:
        """True if this metric is meaningful for the given institution type."""
        return inst_type in self.applicable_to


class BankingRule(BaseModel):
    """One row of ``metrics.yaml: banking_rules`` (Stage 9, Level 2)."""

    id: str
    left: Union[str, List[str]]
    op: str
    right: Union[str, float, None] = None
    tolerance: Optional[float] = None
    message: str
    severity: str = "hard"


# --------------------------------------------------------------------------- #
# Institution dictionary (loaded from institutions.yaml)
# --------------------------------------------------------------------------- #


class InstitutionDef(BaseModel):
    """One row of ``institutions.yaml``."""

    canonical: str
    category: str
    type: str
    aliases: List[str] = Field(default_factory=list)
    cin: Optional[str] = None
    ticker: Optional[str] = None


# --------------------------------------------------------------------------- #
# Parsed document (Stage 1-2)
# --------------------------------------------------------------------------- #


class Table(BaseModel):
    """A single extracted table.

    ``rows`` is a dense list-of-lists of raw cell strings; ``None`` cells from
    the extractor are normalised to ``""`` so downstream code never sees None.
    """

    table_id: str
    page: int
    rows: List[List[str]]
    source: str = "pdfplumber"  # pdfplumber | camelot-lattice | camelot-stream
    caption: str = ""

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)


class Page(BaseModel):
    """A single parsed page."""

    number: int  # 1-based
    text: str = ""
    tables: List[Table] = Field(default_factory=list)
    char_count: int = 0
    image_area_ratio: float = 0.0
    width: float = 0.0
    height: float = 0.0
    ocr_used: bool = False
    section: Section = Section.UNKNOWN
    section_score: float = 0.0
    rank_score: float = 0.0

    @property
    def is_scanned_candidate(self) -> bool:
        """Heuristic: little text but a big image => probably a scanned page."""
        return self.char_count < 50 and self.image_area_ratio > 0.30


class Document(BaseModel):
    """A whole parsed annual report, plus its identification (Stage 2)."""

    path: str
    sha256: str = ""
    pages: List[Page] = Field(default_factory=list)

    institution: Optional[str] = None  # canonical name
    category: Optional[str] = None
    inst_type: str = "bank"
    institution_confidence: float = 0.0

    fiscal_year: Optional[str] = None  # e.g. "FY22-23"
    prior_fiscal_year: Optional[str] = None  # e.g. "FY21-22"
    fy_confidence: float = 0.0

    # Year label -> the strings that identify that year's column in tables.
    year_tokens: Dict[str, List[str]] = Field(default_factory=dict)

    def page(self, number: int) -> Optional[Page]:
        """Return the page with the given 1-based number, or None."""
        for p in self.pages:
            if p.number == number:
                return p
        return None


# --------------------------------------------------------------------------- #
# Extraction (Stage 4-5)
# --------------------------------------------------------------------------- #


class Evidence(BaseModel):
    """One independent corroboration of a candidate's value."""

    page: int
    section: Section
    table_id: Optional[str] = None
    alias_matched: str = ""
    snippet: str = ""
    value: Optional[float] = None

    @property
    def independence_key(self) -> Tuple[str, str]:
        """Repeats within the same (section, table) count once. Stage 7."""
        return (self.section.value, self.table_id or f"text-p{self.page}")


class Candidate(BaseModel):
    """One possible value for one metric. NOTHING is discarded at this stage."""

    metric: str
    value: Optional[float] = None
    text_value: Optional[str] = None  # for unit_type == text
    raw_text: str = ""

    page: int = 0
    section: Section = Section.UNKNOWN
    section_score: float = 0.0

    year_label: Optional[str] = None  # "FY22-23" if the column year was resolved
    year_resolved: bool = False
    is_prior_year_column: bool = False

    unit_as_printed: str = ""
    scale_multiplier: float = 1.0
    scale_inferred: bool = False
    foreign_currency: bool = False

    alias_matched: str = ""
    alias_exact: bool = False
    row_label: str = ""
    row_label_score: float = 100.0
    column_header: str = ""
    column_index: Optional[int] = None
    table_id: Optional[str] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    context: str = ""
    from_table: bool = False

    evidence: List[Evidence] = Field(default_factory=list)

    derived: bool = False
    derivation: str = ""

    @property
    def independent_sources(self) -> int:
        """Distinct (section, table) pairs supporting this value. Stage 7."""
        keys = {
            (self.section.value, self.table_id or f"text-p{self.page}")
        }
        keys.update(e.independence_key for e in self.evidence)
        return len(keys)

    @property
    def distinct_aliases(self) -> int:
        """How many different aliases produced this same value."""
        aliases = {self.alias_matched} | {
            e.alias_matched for e in self.evidence if e.alias_matched
        }
        aliases.discard("")
        return max(1, len(aliases))

    @property
    def distinct_sections(self) -> int:
        secs = {self.section.value} | {e.section.value for e in self.evidence}
        return len(secs)


# --------------------------------------------------------------------------- #
# Judgement (Stage 8-15)
# --------------------------------------------------------------------------- #


class ProsecutorHit(BaseModel):
    """One penalty raised against a candidate, with a human-readable reason."""

    prosecutor: str
    penalty: float
    reason: str


class CheckResult(BaseModel):
    """A DNA / formula / trend / sanity check outcome."""

    name: str
    passed: bool
    detail: str = ""
    level: str = ""  # dna level, or "formula" / "trend" / "sanity"


class Verdict(BaseModel):
    """The judge's full reasoning for one candidate."""

    candidate: Candidate
    defence_score: float = 0.0
    defence_reasons: List[str] = Field(default_factory=list)
    prosecutor_hits: List[ProsecutorHit] = Field(default_factory=list)
    court_score: float = 0.0

    checks: List[CheckResult] = Field(default_factory=list)
    dna_score: float = 1.0
    formula_score: float = 0.6
    trend_score: float = 1.0
    evidence_score: float = 0.0
    source_score: float = 0.0

    confidence: float = 0.0
    decision: Decision = Decision.REJECT
    reason: str = ""

    @property
    def total_penalty(self) -> float:
        return sum(h.penalty for h in self.prosecutor_hits)

    @property
    def checks_passed(self) -> List[str]:
        return [c.name for c in self.checks if c.passed]

    @property
    def checks_failed(self) -> List[str]:
        return [c.name for c in self.checks if not c.passed]


class CellResult(BaseModel):
    """Everything needed to write one Excel cell and its audit row (Stage 16)."""

    institution: str
    fiscal_year: str
    metric: str
    excel_header: str

    value: Optional[float] = None
    text_value: Optional[str] = None
    sentinel: Optional[str] = None  # "ND" | "NA" | None
    confidence: float = 0.0
    decision: Decision = Decision.REJECT
    reason: str = ""

    pages: List[int] = Field(default_factory=list)
    section: Optional[str] = None
    alias_matched: str = ""
    unit_as_printed: str = ""
    candidate_count: int = 0
    defence_score: float = 0.0
    prosecutor_hits: List[ProsecutorHit] = Field(default_factory=list)
    checks_passed: List[str] = Field(default_factory=list)
    checks_failed: List[str] = Field(default_factory=list)
    formula_notes: List[str] = Field(default_factory=list)
    derived: bool = False
    rejected: List[str] = Field(default_factory=list)  # "value@page"

    @property
    def excel_value(self) -> Any:
        """What actually goes into the numeric cell: a number, or ND / NA."""
        if self.sentinel:
            return self.sentinel
        if self.text_value is not None:
            return self.text_value
        return self.value

    @property
    def is_written_number(self) -> bool:
        return self.sentinel is None and (
            self.value is not None or self.text_value is not None
        )


class DocumentResult(BaseModel):
    """The full result of processing one PDF."""

    path: str
    institution: str
    category: str
    inst_type: str
    fiscal_year: str
    prior_fiscal_year: Optional[str] = None
    cells: List[CellResult] = Field(default_factory=list)
    candidate_pool: Dict[str, List[Candidate]] = Field(default_factory=dict)
    prior_year_values: Dict[str, float] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)

    def cell(self, metric: str) -> Optional[CellResult]:
        for c in self.cells:
            if c.metric == metric:
                return c
        return None

    def values(self) -> Dict[str, float]:
        """metric -> numeric value, for cells that actually hold a number."""
        return {
            c.metric: c.value
            for c in self.cells
            if c.value is not None and c.sentinel is None
        }
