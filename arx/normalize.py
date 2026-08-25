"""Stage 12 primitives: numbers, units, scales, Indian formats, OCR damage.

Everything an Indian annual report can do to a number, undone here:

* Indian digit grouping          ``1,36,882.10``   -> 136882.10
* Brackets meaning negative      ``(1,234)``       -> -1234
* Currency symbols and words     ``Rs. 12,345 crore`` -> 12345 (crore)
* Scale words                    ``12,345 million``-> 1234.5 (crore)
* Footnote markers glued on      ``1234*``, ``1234^1`` -> 1234
* Decimal comma from OCR         ``3,19``          -> 3.19
* Missing decimal point          ``319`` where 3.19 is expected -> flagged
* En/em dashes used as minus     ``–1,234``   -> -1234
* Nil markers                    ``-``, ``NIL``, ``--`` -> None

The module never *decides* anything: it converts, and it reports what it had to
guess (``scale_inferred``, ``suspect_missing_decimal``).  The courtroom decides.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional, Tuple

# --------------------------------------------------------------------------- #
# Scale table.  All multipliers convert a raw magnitude into Rs. CRORE.
# 1 crore = 1e7 rupees.
# --------------------------------------------------------------------------- #

SCALE_TO_CRORE = {
    "rupee": 1e-7,
    "hundred": 1e-5,
    "thousand": 1e-4,
    "lakh": 1e-2,
    "million": 1e-1,
    "crore": 1.0,
    "billion": 1e2,
    "lakh crore": 1e5,
    "trillion": 1e5,
}

# Ordered longest-first so "lakh crore" wins over "lakh" and over "crore".
_SCALE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("lakh crore", re.compile(r"(?i)\b(?:lakh|lac)s?\s+crores?\b")),
    ("trillion", re.compile(r"(?i)\btrillions?\b|\btn\b")),
    ("billion", re.compile(r"(?i)\bbillions?\b|\bbn\b")),
    ("million", re.compile(r"(?i)\bmillions?\b|\bmn\b|\bmm\b")),
    ("crore", re.compile(r"(?i)\bcrores?\b|\bcr\.?\b|\bcrs\.?\b")),
    ("lakh", re.compile(r"(?i)\b(?:lakh|lac)s?\b")),
    # The apostrophe in "'000" is REQUIRED. A bare \b000\b happily matches the
    # last group of "1,00,000" and silently turns 1,00,000 into 100 -- which is
    # precisely the class of error this system exists to prevent.
    ("thousand", re.compile(r"(?i)\bthousands?\b|'\s?0{3}s?|\bin\s+0{3}s?\b")),
    ("hundred", re.compile(r"(?i)\bhundreds?\b")),
    ("rupee", re.compile(r"(?i)\bin\s+rupees\b|\bin\s+absolute\s+terms\b")),
]

_FOREIGN_CCY = re.compile(
    r"(?i)(\bUSD\b|\bUS\s*\$|\bU\.S\.\s*\$|\$\s*(?:mn|million|bn)|\bEUR\b|\bJPY\b|\bGBP\b|\bSDR\b)"
)

_INR_TOKENS = re.compile(r"(?i)(?:₹|\bRs\.?\b|\bINR\b|\bRupees\b)")

# Footnote markers, superscripts, daggers, carets, hashes, asterisks.
#
# This MUST be applied to the raw string BEFORE NFKC normalisation: NFKC maps
# superscript digits onto ordinary digits, so "1234¹" would silently become
# "12341" -- a footnote marker promoted into the number itself.
_FOOTNOTE = re.compile(r"[\*†‡\^#~º°¹²³⁰-₟]+")

_NIL_TOKENS = {
    "",
    "-",
    "--",
    "---",
    "–",
    "—",
    "nil",
    "n.a.",
    "na",
    "n/a",
    "nd",
    "not applicable",
    "not disclosed",
    "——",
}

_NUM_BODY = re.compile(r"[-+]?\d[\d,\.\s]*")

# A trailing group of exactly two digits after a comma is impossible in Indian
# grouping (which always ends in a 3-digit group), so it must be a decimal comma
# introduced by OCR or by a European-style typesetter.
_DECIMAL_COMMA = re.compile(r"^\d{1,3},\d{1,2}$")


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


@dataclass
class ParsedNumber:
    """Outcome of parsing one cell / token."""

    value: Optional[float] = None
    negative_from_brackets: bool = False
    footnote_stripped: bool = False
    decimal_comma_fixed: bool = False
    is_nil: bool = False
    raw: str = ""


@dataclass
class ScaleInfo:
    """Outcome of scale detection on a caption / header / context string."""

    name: str = "crore"
    multiplier: float = 1.0
    inferred: bool = True  # True => nothing was actually printed; we assumed
    foreign_currency: bool = False
    printed: str = ""
    tokens: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Number parsing
# --------------------------------------------------------------------------- #


def clean_text(text: str) -> str:
    """NFKC-normalise, collapse whitespace, unify dashes."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    s = s.replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def is_nil(text: str) -> bool:
    """True for the many ways an Indian report writes 'nothing here'."""
    return clean_text(text).strip().lower() in _NIL_TOKENS


def parse_number(text: str) -> Optional[float]:
    """Parse one number out of a cell, returning ``None`` if there isn't one.

    Handles Indian grouping, brackets-as-negative, footnote markers, currency
    symbols, scale *words* (which are stripped here, not applied -- see
    :func:`to_crore`), and OCR decimal commas.

    >>> parse_number("1,36,882.10")
    136882.1
    >>> parse_number("(1,234)")
    -1234.0
    >>> parse_number("1234*")
    1234.0
    """
    return parse_number_full(text).value


def parse_number_full(text: str) -> ParsedNumber:
    """Like :func:`parse_number` but reports *how* the number was recovered."""
    out = ParsedNumber(raw="" if text is None else str(text))
    if text is None:
        return out

    # Footnotes first, on the RAW string: NFKC would turn "1234¹" into "12341".
    raw = str(text)
    stripped = _FOOTNOTE.sub("", raw)
    if stripped != raw:
        out.footnote_stripped = True

    s = clean_text(stripped)
    if not s:
        return out
    if is_nil(s):
        out.is_nil = True
        return out

    # Brackets => negative.  Also handles "Rs. (1,234) crore".
    if re.search(r"\(\s*[\d,\.]+\s*\)", s):
        out.negative_from_brackets = True
        s = re.sub(r"\(\s*([\d,\.]+)\s*\)", r"\1", s)

    # Strip currency tokens and scale words -- scale is applied separately.
    s = _INR_TOKENS.sub(" ", s)
    s = _FOREIGN_CCY.sub(" ", s)
    s = re.sub(r"[₹$€£¥]", " ", s)
    for _name, pat in _SCALE_PATTERNS:
        s = pat.sub(" ", s)
    s = s.replace("%", " ")

    s = clean_text(s)
    if not s:
        return out

    negative = out.negative_from_brackets
    m = _NUM_BODY.search(s)
    if not m:
        return out
    body = m.group(0).strip()
    if body.startswith("-"):
        negative = True
    body = body.lstrip("+-").strip()
    body = body.replace(" ", "")

    if _DECIMAL_COMMA.fullmatch(body):
        # "3,19" -> 3.19 ; "12,3" -> 12.3
        body = body.replace(",", ".")
        out.decimal_comma_fixed = True
    else:
        body = body.replace(",", "")

    # Collapse an accidental double dot from OCR ("1..5").
    body = re.sub(r"\.{2,}", ".", body).strip(".")
    if not body or not re.fullmatch(r"\d*\.?\d+", body):
        return out

    try:
        val = float(body)
    except ValueError:
        return out

    out.value = -val if negative else val
    return out


# --------------------------------------------------------------------------- #
# Scale / unit detection
# --------------------------------------------------------------------------- #


def detect_scale(text: str, default: str = "crore") -> ScaleInfo:
    """Detect the printed magnitude of a table caption / column header / line.

    ``inferred=True`` means nothing was printed and ``default`` was assumed --
    the courtroom's unit prosecutor penalises that.

    >>> detect_scale("(Rs. in crore)").name
    'crore'
    >>> detect_scale("(Rs. in million)").multiplier
    0.1
    """
    s = clean_text(text)
    info = ScaleInfo(name=default, multiplier=SCALE_TO_CRORE[default], inferred=True)
    if not s:
        return info

    if _FOREIGN_CCY.search(s):
        info.foreign_currency = True
        info.printed = _FOREIGN_CCY.search(s).group(0)

    for name, pat in _SCALE_PATTERNS:
        m = pat.search(s)
        if m:
            info.name = name
            info.multiplier = SCALE_TO_CRORE[name]
            info.inferred = False
            info.printed = m.group(0)
            info.tokens.append(name)
            break
    return info


def to_crore(value: float, scale: ScaleInfo | str) -> float:
    """Convert ``value``, printed at ``scale``, into Rs. crore.

    >>> to_crore(12345, "million")
    1234.5
    >>> to_crore(12345, "crore")
    12345.0
    """
    if isinstance(scale, str):
        mult = SCALE_TO_CRORE[scale]
    else:
        mult = scale.multiplier
    return float(value) * mult


def normalize_amount(raw_text: str, unit_context: str = "") -> Tuple[Optional[float], ScaleInfo]:
    """Parse an amount and convert it to Rs. crore.

    The scale is taken from the token inside ``raw_text`` if there is one
    (``"Rs. 12,345 crore"``), otherwise from ``unit_context`` (the table caption
    or column header), otherwise assumed to be crore and flagged as inferred.

    >>> normalize_amount("Rs. 12,345 crore")[0]
    12345.0
    >>> normalize_amount("12,345 million")[0]
    1234.5
    """
    inline = detect_scale(raw_text)
    scale = inline if not inline.inferred or inline.foreign_currency else detect_scale(unit_context)
    if inline.foreign_currency or detect_scale(unit_context).foreign_currency:
        scale.foreign_currency = True

    num = parse_number(raw_text)
    if num is None:
        return None, scale
    return to_crore(num, scale), scale


# --------------------------------------------------------------------------- #
# Percent / ratio sanity (Stage 12)
# --------------------------------------------------------------------------- #


def suspect_missing_decimal(
    value: Optional[float], sane_range: Optional[Tuple[float, float]]
) -> bool:
    """True if ``value`` is out of range but ``value / 100`` would be in range.

    This is the ``319`` -> ``3.19`` case (a dropped decimal point, common with
    OCR).  We never silently apply the fix -- we only report the suspicion, so
    the courtroom can penalise the candidate.  Guessing here would be exactly
    the false positive the whole system exists to prevent.

    >>> suspect_missing_decimal(319, (0, 15))
    True
    >>> suspect_missing_decimal(3.19, (0, 15))
    False
    """
    if value is None or not sane_range:
        return False
    lo, hi = sane_range
    if lo <= value <= hi:
        return False
    return lo <= value / 100.0 <= hi


def in_range(value: Optional[float], sane_range: Optional[Tuple[float, float]]) -> bool:
    """True if ``value`` sits inside ``sane_range`` (or no range is defined)."""
    if value is None:
        return False
    if not sane_range:
        return True
    lo, hi = sane_range
    return lo <= value <= hi


def normalize_percent(raw_text: str) -> Optional[float]:
    """Parse a percentage as a plain number: ``"3.19%"`` -> ``3.19``."""
    return parse_number(raw_text)


def digits_only(text: str) -> str:
    """All digits in ``text``, in order -- used by the reverse-validation index."""
    return re.sub(r"\D", "", clean_text(text))


def value_signature(value: float) -> str:
    """A comparison key that survives OCR comma damage.

    ``1,368,821`` and ``1368821`` and ``13,68,821`` all reduce to ``1368821``,
    so the reverse-validation engine (Stage 10) can spot the same printed number
    wherever it appears, however it was grouped.
    """
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(round(value)))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def same_value(a: Optional[float], b: Optional[float], rel_tol: float = 0.005) -> bool:
    """Relative comparison that treats 0 sensibly."""
    if a is None or b is None:
        return False
    if a == b:
        return True
    denom = max(abs(a), abs(b))
    if denom == 0:
        return True
    return abs(a - b) / denom <= rel_tol


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation and corporate suffixes -- for fuzzy matching.

    >>> normalize_name("State Bank of India (SBI)")
    'state bank of india sbi'
    """
    s = clean_text(name).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\b(limited|ltd|private|pvt|company|co|corporation|corp|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()
