"""Shared fixtures.

The important one is :func:`icici_document`: a hand-built
:class:`~arx.models.Document` that reproduces the *shape* of ICICI Bank's FY22-23
annual report -- Balance Sheet, P&L, Financial Highlights, Basel III disclosures,
a two-column (current / prior year) layout, Indian digit grouping, a unit caption,
and a narrative page containing a decoy number.

Because ``arx.pipeline.process_document`` takes a Document rather than a path,
the entire Stage 3-16 chain is testable in milliseconds with no PDF, no OCR and
no camelot.  The real-PDF golden test in ``test_end_to_end.py`` runs on top of the
same code path whenever you drop the actual report into ``tests/fixtures/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arx.models import Document, Page, Section, Table
from arx.parse import identify_fiscal_year, identify_institution

FIXTURES = Path(__file__).parent / "fixtures"

# The template's ICICI FY22-23 row -- the regression ground truth.
ICICI_FY2223_TRUTH = {
    "total_assets": 1584207.0,
    "total_deposits": 1180841.0,
    "gross_advances": 1019638.0,
    "interest_earned": 109231.34,
    "interest_expended": 47102.74,
    "nii": 62129.0,
    "pat": 31896.50,
    "gnpa_ratio": 2.81,
    "crar": 18.34,
}


def _table(table_id: str, page: int, rows, caption: str = "(₹ in crore)") -> Table:
    return Table(table_id=table_id, page=page, rows=rows, source="pdfplumber", caption=caption)


def _page(number: int, text: str, tables, section: Section) -> Page:
    return Page(
        number=number,
        text=text,
        tables=tables,
        char_count=len(text.strip()),
        image_area_ratio=0.0,
        width=595.0,
        height=842.0,
        section=section,
        section_score=1.0,
    )


def build_icici_document() -> Document:
    """A synthetic but structurally faithful ICICI Bank FY22-23 report."""
    pages = []

    # ---- p1: cover -------------------------------------------------------- #
    pages.append(
        _page(
            1,
            "ICICI Bank Limited\nAnnual Report 2022-23\nCIN: L65190GJ1994PLC021012\n",
            [],
            Section.NARRATIVE,
        )
    )

    # ---- p2: Balance Sheet ------------------------------------------------ #
    bs_rows = [
        ["Particulars", "As at March 31, 2023", "As at March 31, 2022"],
        ["Capital", "1,396.78", "1,389.97"],
        ["Deposits", "11,80,840.70", "10,64,571.61"],
        ["Advances", "10,19,638.31", "8,59,020.44"],
        ["TOTAL ASSETS", "15,84,206.65", "14,11,297.74"],
        ["Net Worth", "2,04,000.00", "1,73,000.00"],
    ]
    pages.append(
        _page(
            2,
            "Balance Sheet as at March 31, 2023\n(₹ in crore)\n"
            "Schedule 3 Deposits  Schedule 9 Advances\n"
            "Deposits 11,80,840.70 10,64,571.61\n"
            "Advances 10,19,638.31 8,59,020.44\n"
            "TOTAL ASSETS 15,84,206.65 14,11,297.74\n",
            [_table("p2-plumber-0", 2, bs_rows)],
            Section.FINANCIAL_STATEMENTS,
        )
    )

    # ---- p3: Profit & Loss ------------------------------------------------ #
    pl_rows = [
        ["Particulars", "Year ended March 31, 2023", "Year ended March 31, 2022"],
        ["Interest earned", "1,09,231.34", "86,374.55"],
        ["Interest expended", "47,102.74", "41,166.66"],
        ["Other income", "19,883.14", "16,966.11"],
        ["Operating expenses", "32,873.24", "26,733.32"],
        ["Payments to and provisions for employees", "12,376.11", "9,672.87"],
        ["Provisions and contingencies", "16,667.11", "13,974.16"],
        ["Profit after tax", "31,896.50", "23,339.49"],
    ]
    pages.append(
        _page(
            3,
            "Profit and Loss Account for the year ended March 31, 2023\n(₹ in crore)\n"
            "Schedule 13 Interest earned  Schedule 15 Interest expended\n"
            "Interest earned 1,09,231.34 86,374.55\n"
            "Interest expended 47,102.74 41,166.66\n"
            "Profit after tax 31,896.50 23,339.49\n",
            [_table("p3-plumber-0", 3, pl_rows)],
            Section.FINANCIAL_STATEMENTS,
        )
    )

    # ---- p4: Notes (an independent second source for the P&L lines) ------- #
    notes_rows = [
        ["Particulars", "March 31, 2023", "March 31, 2022"],
        ["Net Interest Income", "62,129.00", "47,466.10"],
        ["Interest Earned", "1,09,231.34", "86,374.55"],
        ["Interest Expended", "47,102.74", "41,166.66"],
        ["Gross NPA", "31,183.70", "33,919.52"],
        ["Net NPA", "5,155.07", "6,960.89"],
        ["Provision Coverage Ratio", "82.86", "79.48"],
    ]
    pages.append(
        _page(
            4,
            "Notes to the financial statements as at March 31, 2023\n(₹ in crore)\n"
            "Net Interest Income 62,129.00 47,466.10\n",
            [_table("p4-plumber-0", 4, notes_rows)],
            Section.FINANCIAL_STATEMENTS,
        )
    )

    # ---- p5: Financial Highlights ----------------------------------------- #
    hl_rows = [
        ["Particulars", "FY2023", "FY2022"],
        ["Total Assets", "15,84,206.65", "14,11,297.74"],
        ["Total Deposits", "11,80,840.70", "10,64,571.61"],
        ["Gross Advances", "10,19,638.31", "8,59,020.44"],
        ["Interest Earned", "1,09,231.34", "86,374.55"],
        ["Interest Expended", "47,102.74", "41,166.66"],
        ["Net Interest Income", "62,129.00", "47,466.10"],
        ["Profit After Tax", "31,896.50", "23,339.49"],
        ["Net Worth", "2,04,000.00", "1,73,000.00"],
        ["Gross NPA Ratio", "2.81", "3.60"],
        ["Net NPA Ratio", "0.48", "0.76"],
        ["CASA Ratio", "45.80", "48.70"],
        # Real reports print capital adequacy at a glance AND in Basel III.
        ["Capital Adequacy Ratio", "18.34", "19.16"],
        ["Tier 1 Capital Ratio", "17.60", "17.60"],
        ["Number of Branches", "5900", "5418"],
        ["Number of Employees", "129020", "105844"],
    ]
    pages.append(
        _page(
            5,
            "Financial Highlights\n(₹ in crore)\nPerformance at a glance for the "
            "year ended March 31, 2023\n",
            [_table("p5-plumber-0", 5, hl_rows)],
            Section.FINANCIAL_HIGHLIGHTS,
        )
    )

    # ---- p6: Basel III / Key Ratios --------------------------------------- #
    basel_rows = [
        ["Particulars", "March 31, 2023", "March 31, 2022"],
        ["Common Equity Tier 1 Ratio", "17.60", "17.60"],
        ["Tier 1 Capital Ratio", "17.60", "17.60"],
        ["Tier 2 Capital Ratio", "0.74", "1.55"],
        ["Total Capital Ratio", "18.34", "19.16"],
        ["Gross NPA Ratio", "2.81", "3.60"],
    ]
    pages.append(
        _page(
            6,
            "Basel III Pillar 3 disclosures\nCapital Adequacy as at March 31, 2023\n",
            [_table("p6-plumber-0", 6, basel_rows, caption="")],
            Section.KEY_RATIOS,
        )
    )

    # ---- p7: narrative, with a decoy -------------------------------------- #
    pages.append(
        _page(
            7,
            "Message from the Chairman\n"
            "Our profit after tax crossed 30,000 crore during the year, and the "
            "Bank's CASA ratio stood at 45.8% as at March 31, 2023. We invested "
            "significantly in technology.\n",
            [],
            Section.NARRATIVE,
        )
    )

    doc = Document(path="tests/synthetic/icici_fy2223.pdf", sha256="synthetic", pages=pages)
    identify_institution(doc)
    identify_fiscal_year(doc)
    return doc


@pytest.fixture()
def icici_document() -> Document:
    return build_icici_document()


@pytest.fixture()
def truth() -> dict:
    return dict(ICICI_FY2223_TRUTH)


@pytest.fixture()
def blank_template(tmp_path) -> Path:
    from arx.excel_writer import build_blank_template

    return build_blank_template(tmp_path / "FinancialData_Verified_1.xlsx")
