"""Stage 9-10: the four DNA levels, and reverse validation."""

from __future__ import annotations

import pytest

from arx import load_config, metrics_by_key
from arx.dna import (
    DnaContext,
    dna_score,
    level1_range,
    level2_rules,
    level3_history,
    level4_peers,
    reverse_validate,
)
from arx.models import Candidate, Section

CFG = load_config()
MK = metrics_by_key()

SOUND = {
    "gnpa_amount": 31183.70,
    "nnpa_amount": 5155.07,
    "gnpa_ratio": 2.81,
    "nnpa_ratio": 0.48,
    "roe": 15.63,
    "roa": 2.01,
    "crar": 18.34,
    "cet1": 17.60,
    "tier1": 17.60,
    "tier2": 0.74,
    "total_assets": 1584207.0,
    "gross_advances": 1019638.0,
    "total_deposits": 1180841.0,
    "pcr": 82.86,
    "interest_earned": 109231.34,
    "interest_expended": 47102.74,
    "net_worth": 204000.0,
}


class TestLevel1Ranges:
    def test_a_pcr_of_140_is_rejected(self):
        check = level1_range(140.0, MK["pcr"])
        assert check.passed is False
        assert "outside sane range" in check.detail

    def test_a_pcr_of_82_is_fine(self):
        assert level1_range(82.86, MK["pcr"]).passed is True

    @pytest.mark.parametrize(
        "metric,bad",
        [("roa", 45.0), ("roe", 900.0), ("nim", 60.0), ("crar", 95.0), ("casa_ratio", 130.0)],
    )
    def test_impossible_values_are_caught(self, metric, bad):
        assert level1_range(bad, MK[metric]).passed is False

    def test_negative_where_not_allowed(self):
        assert level1_range(-100.0, MK["total_assets"]).passed is False

    def test_negative_pat_is_allowed(self):
        assert level1_range(-5000.0, MK["pat"]).passed is True


class TestLevel2BankingLogic:
    def test_a_sound_set_of_values_breaks_no_rules(self):
        failures = [c for c in level2_rules(SOUND) if not c.passed]
        assert failures == []

    def test_gnpa_less_than_nnpa_is_caught(self):
        bad = dict(SOUND, gnpa_amount=5000.0, nnpa_amount=9000.0)
        failed = {c.name for c in level2_rules(bad) if not c.passed}
        assert "gnpa_gt_nnpa" in failed

    def test_roa_above_roe_is_caught(self):
        bad = dict(SOUND, roa=20.0, roe=5.0)
        failed = {c.name for c in level2_rules(bad) if not c.passed}
        assert "roe_gt_roa" in failed

    def test_cet1_above_car_is_caught(self):
        bad = dict(SOUND, crar=12.0, cet1=17.6)
        failed = {c.name for c in level2_rules(bad) if not c.passed}
        assert "car_gt_cet1" in failed

    def test_advances_above_total_assets_is_caught(self):
        bad = dict(SOUND, gross_advances=2_000_000.0)
        failed = {c.name for c in level2_rules(bad) if not c.passed}
        assert "assets_gt_advances" in failed

    def test_tier1_plus_tier2_must_reconcile_to_crar(self):
        bad = dict(SOUND, tier2=5.0)  # 17.60 + 5.00 = 22.60 != 18.34
        failed = {c.name for c in level2_rules(bad) if not c.passed}
        assert "tier_sum_is_crar" in failed

    def test_a_missing_operand_is_not_a_violation(self):
        partial = {"gnpa_amount": 31183.70}  # no NNPA at all
        assert [c for c in level2_rules(partial) if not c.passed] == []


class TestLevel3History:
    def _ctx(self, history):
        return DnaContext(
            inst_type="bank",
            fiscal_year="FY22-23",
            history=history,
            peers={},
            cfg=CFG,
        )

    def test_normal_growth_passes(self):
        ctx = self._ctx({"total_assets": {"FY21-22": 1411297.0}})
        check = level3_history("total_assets", 1584207.0, ctx)
        assert check.passed is True

    def test_an_absurd_jump_is_flagged(self):
        ctx = self._ctx({"total_assets": {"FY21-22": 1411297.0}})
        check = level3_history("total_assets", 14112970.0, ctx)
        assert check.passed is False
        assert "investigate" in check.detail

    def test_no_history_means_no_opinion(self):
        assert level3_history("total_assets", 1584207.0, self._ctx({})) is None


class TestLevel4Peers:
    def _ctx(self, peers):
        return DnaContext(
            inst_type="bank", fiscal_year="FY22-23", history={}, peers=peers, cfg=CFG
        )

    def test_an_outlier_ratio_is_flagged_against_peers(self):
        ctx = self._ctx({"crar": [16.1, 16.8, 17.2, 17.9, 18.3, 16.5]})
        check = level4_peers("crar", 39.0, ctx)
        assert check is not None and check.passed is False

    def test_an_ordinary_ratio_passes(self):
        ctx = self._ctx({"crar": [16.1, 16.8, 17.2, 17.9, 18.3, 16.5]})
        assert level4_peers("crar", 17.4, ctx).passed is True

    def test_size_metrics_are_not_peer_compared(self):
        # Comparing SBI's balance sheet to Can Fin Homes' is meaningless.
        ctx = self._ctx({"total_assets": [100.0, 200.0, 300.0, 400.0]})
        assert level4_peers("total_assets", 1584207.0, ctx) is None


class TestReverseValidation:
    def _cand(self, metric, value, page, row_label, table_id="p120-plumber-0"):
        return Candidate(
            metric=metric,
            value=value,
            page=page,
            section=Section.FINANCIAL_STATEMENTS,
            section_score=1.0,
            year_label="FY22-23",
            year_resolved=True,
            row_label=row_label,
            table_id=table_id,
            from_table=True,
        )

    def test_the_same_number_being_two_metrics_is_a_column_shift(self):
        chosen = self._cand("nii", 62129.0, 120, "Net Interest Income")
        pool = {
            "nii": [chosen],
            "other_income": [self._cand("other_income", 62129.0, 120, "Other Income")],
        }
        hit = reverse_validate("nii", chosen, pool, CFG)
        assert hit is not None
        assert hit.prosecutor == "reverse_validation"
        assert "row/column shift" in hit.reason

    def test_a_coincidence_on_a_different_page_is_not_evidence(self):
        chosen = self._cand("nii", 62129.0, 120, "Net Interest Income")
        pool = {
            "nii": [chosen],
            "other_income": [
                self._cand("other_income", 62129.0, 55, "Other Income", "p55-plumber-0")
            ],
        }
        assert reverse_validate("nii", chosen, pool, CFG) is None

    def test_ratios_are_not_reverse_validated(self):
        # Two ratios both being 2.81 is completely unremarkable.
        chosen = self._cand("gnpa_ratio", 2.81, 120, "Gross NPA Ratio")
        pool = {
            "gnpa_ratio": [chosen],
            "roa": [self._cand("roa", 2.81, 120, "Return on Assets")],
        }
        assert reverse_validate("gnpa_ratio", chosen, pool, CFG) is None


class TestScoring:
    def test_a_clean_bill_of_health_scores_one(self):
        checks = [level1_range(82.86, MK["pcr"])] + level2_rules(SOUND)
        assert dna_score(checks, CFG) == pytest.approx(1.0)

    def test_a_range_violation_costs_more_than_a_peer_deviation(self):
        bad_range = [level1_range(140.0, MK["pcr"])]
        assert dna_score(bad_range, CFG) < 1.0
        assert dna_score(bad_range, CFG) == pytest.approx(
            1.0 - CFG["dna"]["level1_range_violation"]
        )
