"""Stage 11-13: the arithmetic identities, derivation, sanity and trend."""

from __future__ import annotations

import pytest

from arx import metrics_by_key
from arx.formulas import (
    FORMULAS,
    check_formulas,
    derivable,
    evaluate,
    formula_score,
    sanity_checks,
    trend_check,
    within_tolerance,
)

# ICICI FY22-23, from the template row.
ICICI = {
    "interest_earned": 109231.34,
    "interest_expended": 47102.74,
    "nii": 62129.0,
    "other_income": 19883.14,
    "opex": 32873.24,
    "pat": 31896.50,
    "total_assets": 1584207.0,
    "net_worth": 204000.0,
    "gnpa_amount": 31183.70,
    "nnpa_amount": 5155.07,
    "gross_advances": 1019638.0,
    "gnpa_ratio": 2.81,
    "tier1": 17.60,
    "tier2": 0.74,
    "crar": 18.34,
    "pcr": 82.86,
}


class TestIdentities:
    def test_nii_identity(self):
        expected = evaluate(FORMULAS["nii_identity"], ICICI)
        assert expected == pytest.approx(62128.60, abs=0.01)
        # 62,129 (as printed) vs 62,128.60 (as computed) is inside +/-1%.
        assert within_tolerance(expected, ICICI["nii"], "amount")

    def test_crar_is_tier1_plus_tier2(self):
        expected = evaluate(FORMULAS["crar_identity"], ICICI)
        assert expected == pytest.approx(18.34, abs=1e-9)
        assert within_tolerance(expected, ICICI["crar"], "ratio")

    def test_pcr_from_gnpa_and_nnpa(self):
        expected = evaluate(FORMULAS["pcr_identity"], ICICI)
        assert expected == pytest.approx(83.47, abs=0.01)

    def test_roa(self):
        expected = evaluate(FORMULAS["roa_identity"], ICICI)
        assert expected == pytest.approx(2.013, abs=0.01)

    def test_roe(self):
        expected = evaluate(FORMULAS["roe_identity"], ICICI)
        assert expected == pytest.approx(15.635, abs=0.01)

    def test_gnpa_amount_from_ratio_and_advances(self):
        expected = evaluate(FORMULAS["gnpa_amount_identity"], ICICI)
        assert expected == pytest.approx(28651.83, rel=0.001)

    def test_cost_to_income(self):
        expected = evaluate(FORMULAS["cost_to_income_identity"], ICICI)
        assert expected == pytest.approx(40.09, abs=0.05)

    def test_wholesale_is_the_complement_of_retail(self):
        assert evaluate(FORMULAS["wholesale_mix_identity"], {"retail_mix": 63.0}) == 37.0

    def test_missing_input_yields_none_not_a_guess(self):
        assert evaluate(FORMULAS["nii_identity"], {"interest_earned": 100.0}) is None


class TestTolerances:
    def test_amounts_use_relative_tolerance(self):
        assert within_tolerance(100000, 100900, "amount") is True   # 0.9%
        assert within_tolerance(100000, 102000, "amount") is False  # 2.0%

    def test_ratios_use_absolute_percentage_points(self):
        assert within_tolerance(18.34, 18.40, "ratio") is True   # 0.06 pp
        assert within_tolerance(18.34, 18.60, "ratio") is False  # 0.26 pp


class TestCrossCheck:
    def test_consistent_report_passes_everything_it_can(self):
        checks = check_formulas(ICICI)
        names = {c.name for c in checks}
        assert "nii_identity" in names
        assert "crar_identity" in names
        assert all(c.passed for c in checks if c.name in ("nii_identity", "crar_identity"))

    def test_a_broken_nii_is_caught(self):
        bad = dict(ICICI, nii=75000.0)
        checks = {c.name: c for c in check_formulas(bad)}
        assert checks["nii_identity"].passed is False
        assert "expected" in checks["nii_identity"].detail

    def test_formula_score_punishes_the_metrics_in_the_broken_identity(self):
        bad = dict(ICICI, nii=75000.0)
        checks = check_formulas(bad)
        assert formula_score("nii", checks) < formula_score("nii", check_formulas(ICICI))

    def test_metric_with_no_applicable_formula_gets_the_neutral_score(self):
        assert formula_score("branches", check_formulas(ICICI)) == pytest.approx(0.60)


class TestDerivation:
    def test_derives_nii_from_confident_inputs(self):
        values = {k: v for k, v in ICICI.items() if k != "nii"}
        confs = {k: 95.0 for k in values}
        got = derivable("nii", values, confs)
        assert got is not None
        value, expression = got
        assert value == pytest.approx(62128.60, abs=0.01)
        assert "Interest Earned" in expression

    def test_refuses_to_derive_from_shaky_inputs(self):
        values = {k: v for k, v in ICICI.items() if k != "nii"}
        confs = {k: 70.0 for k in values}  # below derive_min_input_confidence
        assert derivable("nii", values, confs) is None

    def test_never_derives_over_an_existing_value(self):
        confs = {k: 99.0 for k in ICICI}
        assert derivable("nii", ICICI, confs) is None

    def test_refuses_to_derive_a_value_outside_the_sane_range(self):
        values = {"pat": 31896.5, "net_worth": 1.0}  # RoE would be 3,189,650%
        confs = {"pat": 99.0, "net_worth": 99.0}
        assert derivable("roe", values, confs) is None


class TestSanity:
    def test_negative_where_not_allowed(self):
        md = metrics_by_key()["total_assets"]
        failures = [c for c in sanity_checks(-5.0, md) if not c.passed]
        assert any("negative" in c.name for c in failures)

    def test_negative_is_allowed_for_pat(self):
        md = metrics_by_key()["pat"]
        assert all(c.passed for c in sanity_checks(-500.0, md))

    def test_fractional_headcount_is_flagged(self):
        md = metrics_by_key()["employees"]
        failures = [c for c in sanity_checks(1050.5, md) if not c.passed]
        assert any("integer" in c.name for c in failures)

    def test_dropped_decimal_point_is_flagged(self):
        md = metrics_by_key()["nim"]  # sane range 0..15
        failures = [c for c in sanity_checks(319.0, md, raw_text="319") if not c.passed]
        assert any("missing_decimal" in c.name for c in failures)


class TestTrend:
    def test_normal_growth_is_unremarkable(self):
        score, check = trend_check("total_assets", 1584207, 1411297)
        assert score == 1.0
        assert check.passed is True

    def test_five_hundred_percent_is_flagged_but_not_deleted(self):
        score, check = trend_check("total_assets", 7000000, 1000000)  # +600%
        assert check.passed is False
        assert score < 1.0
        assert score > 0.0  # a merger can genuinely do this: flag, do not reject
        assert "manual review" in check.detail.lower()

    def test_no_prior_year_means_no_opinion(self):
        score, check = trend_check("total_assets", 1584207, None)
        assert score == 1.0
        assert check is None
