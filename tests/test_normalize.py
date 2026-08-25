"""Every way an Indian annual report can mangle a number."""

from __future__ import annotations

import pytest

from arx.normalize import (
    detect_scale,
    is_nil,
    normalize_amount,
    normalize_name,
    parse_number,
    parse_number_full,
    same_value,
    suspect_missing_decimal,
    to_crore,
    value_signature,
)


class TestIndianFormats:
    def test_indian_digit_grouping(self):
        assert parse_number("1,36,882.10") == pytest.approx(136882.10)
        assert parse_number("15,84,206.65") == pytest.approx(1584206.65)
        assert parse_number("1,09,231.34") == pytest.approx(109231.34)

    def test_western_grouping_still_works(self):
        assert parse_number("1,368,821") == pytest.approx(1368821)
        assert parse_number("1368821") == pytest.approx(1368821)

    def test_ocr_comma_damage_produces_the_same_signature(self):
        # This is what lets reverse validation spot the same printed number
        # however it was grouped.
        assert value_signature(parse_number("1,368,821")) == value_signature(
            parse_number("1368821")
        )
        assert value_signature(parse_number("13,68,821")) == value_signature(
            parse_number("1368821")
        )


class TestBracketsAndSigns:
    def test_brackets_mean_negative(self):
        assert parse_number("(1,234)") == pytest.approx(-1234)
        assert parse_number("(1,234.50)") == pytest.approx(-1234.50)

    def test_leading_minus(self):
        assert parse_number("-1,234") == pytest.approx(-1234)

    def test_unicode_minus_and_en_dash(self):
        assert parse_number("−1,234") == pytest.approx(-1234)
        assert parse_number("–1,234") == pytest.approx(-1234)

    def test_brackets_inside_a_currency_phrase(self):
        assert parse_number("₹ (1,234) crore") == pytest.approx(-1234)


class TestFootnotes:
    @pytest.mark.parametrize("raw", ["1234*", "1234#", "1234†", "1234¹", "1234^"])
    def test_footnote_markers_are_stripped(self, raw):
        assert parse_number(raw) == pytest.approx(1234)

    def test_footnote_flag_is_reported(self):
        assert parse_number_full("1234*").footnote_stripped is True
        assert parse_number_full("1234").footnote_stripped is False


class TestCurrencyAndScale:
    def test_rupee_crore(self):
        assert normalize_amount("₹ 12,345 crore")[0] == pytest.approx(12345)
        assert normalize_amount("Rs. 12,345 crore")[0] == pytest.approx(12345)

    def test_million_converts_to_crore(self):
        assert normalize_amount("12,345 million")[0] == pytest.approx(1234.5)

    def test_billion_converts_to_crore(self):
        assert normalize_amount("12 billion")[0] == pytest.approx(1200.0)

    def test_lakh_converts_to_crore(self):
        assert normalize_amount("1,00,000 lakh")[0] == pytest.approx(1000.0)

    def test_lakh_crore_converts_to_crore(self):
        assert normalize_amount("1.5 lakh crore")[0] == pytest.approx(150000.0)

    def test_caption_supplies_the_scale_when_the_cell_does_not(self):
        value, scale = normalize_amount("12,345", unit_context="(₹ in million)")
        assert value == pytest.approx(1234.5)
        assert scale.inferred is False

    def test_missing_scale_is_flagged_as_inferred_not_guessed_silently(self):
        value, scale = normalize_amount("12,345")
        assert value == pytest.approx(12345)  # crore assumed
        assert scale.inferred is True  # ...and the courtroom will charge for it

    def test_foreign_currency_is_detected(self):
        assert detect_scale("(USD million)").foreign_currency is True
        assert detect_scale("(₹ in crore)").foreign_currency is False

    def test_to_crore_table(self):
        assert to_crore(12345, "million") == pytest.approx(1234.5)
        assert to_crore(12345, "crore") == pytest.approx(12345)
        assert to_crore(100, "billion") == pytest.approx(10000)


class TestPercentDetection:
    def test_decimal_comma_from_ocr(self):
        # "3,19" cannot be Indian grouping (a group never ends in 2 digits).
        assert parse_number("3,19") == pytest.approx(3.19)
        assert parse_number_full("3,19").decimal_comma_fixed is True

    def test_missing_decimal_point_is_suspected_not_corrected(self):
        nim_range = (0.0, 15.0)
        assert suspect_missing_decimal(319, nim_range) is True
        assert suspect_missing_decimal(3.19, nim_range) is False
        # We never silently "fix" it -- guessing is the whole failure mode.
        assert parse_number("319") == pytest.approx(319)

    def test_percent_sign_is_stripped(self):
        assert parse_number("3.19%") == pytest.approx(3.19)


class TestNilAndJunk:
    @pytest.mark.parametrize("raw", ["", "-", "--", "NIL", "N/A", "Not disclosed"])
    def test_nil_tokens(self, raw):
        assert is_nil(raw) is True
        assert parse_number(raw) is None

    def test_pure_text_is_not_a_number(self):
        assert parse_number("Particulars") is None
        assert parse_number("CRISIL AAA/Stable") is None


class TestHelpers:
    def test_same_value_tolerance(self):
        assert same_value(70901, 70910, rel_tol=0.005) is True
        assert same_value(70901, 80000, rel_tol=0.005) is False

    def test_normalize_name_strips_corporate_noise(self):
        assert normalize_name("State Bank of India (SBI)") == "state bank of india sbi"
        assert normalize_name("ICICI Bank Limited") == "icici bank"
        assert normalize_name("ICICI Bank Ltd.") == "icici bank"
