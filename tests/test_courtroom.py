"""Stage 8: given a poisoned candidate pool, the right value must still win."""

from __future__ import annotations

import pytest

from arx import load_config, metrics_by_key
from arx.courtroom import TrialContext, defend, hold_trial
from arx.models import Candidate, Evidence, Section

CFG = load_config()
TARGET = "FY22-23"
PRIOR = "FY21-22"


def ctx(metric: str = "total_assets") -> TrialContext:
    return TrialContext(
        target_fy=TARGET,
        prior_fy=PRIOR,
        metric=metrics_by_key()[metric],
        inst_type="bank",
        cfg=CFG,
    )


def cand(**kw) -> Candidate:
    base = dict(
        metric="total_assets",
        value=1584207.0,
        raw_text="15,84,207.00",
        page=120,
        section=Section.FINANCIAL_STATEMENTS,
        section_score=1.0,
        year_label=TARGET,
        year_resolved=True,
        unit_as_printed="crore",
        scale_multiplier=1.0,
        scale_inferred=False,
        alias_matched=r"Total\s+Assets",
        alias_exact=True,
        row_label="TOTAL ASSETS",
        row_label_score=100.0,
        column_header="As at March 31, 2023",
        column_index=1,
        table_id="p120-plumber-0",
        from_table=True,
    )
    base.update(kw)
    return Candidate(**base)


@pytest.fixture()
def poisoned_pool():
    """The correct value, plus a year mismatch, plus a unit mismatch, plus noise."""
    correct = cand(
        evidence=[
            Evidence(
                page=8,
                section=Section.FINANCIAL_HIGHLIGHTS,
                table_id="p8-plumber-0",
                alias_matched=r"Total\s+Assets",
                value=1584207.0,
            ),
            Evidence(
                page=200,
                section=Section.MULTI_YEAR_SUMMARY,
                table_id="p200-plumber-1",
                alias_matched=r"Balance\s+Sheet\s+Size",
                value=1584207.0,
            ),
        ]
    )
    year_mismatch = cand(
        value=1411297.74,
        raw_text="14,11,297.74",
        year_label=PRIOR,
        is_prior_year_column=True,
        column_header="As at March 31, 2022",
        column_index=2,
    )
    unit_mismatch = cand(
        value=15842070000.0,  # the same table read as if it were in lakhs
        raw_text="15,84,207.00",
        page=121,
        unit_as_printed="",
        scale_inferred=True,
        table_id="p121-camelot-stream-0",
    )
    misaligned = cand(
        value=204000.0,  # actually Net Worth: the row label was off by one
        raw_text="2,04,000.00",
        page=120,
        row_label="Net Worth",
        row_label_score=61.0,
        alias_exact=False,
    )
    narrative = cand(
        value=1600000.0,
        raw_text="about 16 lakh crore",
        page=7,
        section=Section.NARRATIVE,
        section_score=0.30,
        from_table=False,
        table_id=None,
        year_resolved=False,
        column_header="",
    )
    return [year_mismatch, unit_mismatch, misaligned, narrative, correct]


class TestDefence:
    def test_multiple_independent_sections_beat_one(self):
        lonely = cand()
        corroborated = cand(
            evidence=[
                Evidence(page=8, section=Section.FINANCIAL_HIGHLIGHTS, table_id="p8-0"),
                Evidence(page=200, section=Section.MULTI_YEAR_SUMMARY, table_id="p200-0"),
            ]
        )
        assert defend(corroborated, ctx())[0] > defend(lonely, ctx())[0]

    def test_repeats_inside_one_section_and_table_add_nothing(self):
        # Stage 7: independence is deduplicated by (section, table_id) upstream,
        # so a candidate whose "evidence" is the same table cannot inflate itself.
        repeated = cand(
            evidence=[
                Evidence(
                    page=120,
                    section=Section.FINANCIAL_STATEMENTS,
                    table_id="p120-plumber-0",
                )
            ]
        )
        assert repeated.independent_sources == 1


class TestJudge:
    def test_the_correct_candidate_wins(self, poisoned_pool):
        verdicts = hold_trial(poisoned_pool, ctx())
        winner = verdicts[0].candidate
        assert winner.value == pytest.approx(1584207.0)
        assert winner.year_label == TARGET

    def test_year_mismatch_is_charged_and_explained(self, poisoned_pool):
        verdicts = hold_trial(poisoned_pool, ctx())
        v = next(v for v in verdicts if v.candidate.value == pytest.approx(1411297.74))
        hits = [h for h in v.prosecutor_hits if h.prosecutor == "year_mismatch"]
        assert hits, "the prior-year column must be prosecuted"
        assert hits[0].penalty >= 60
        assert "prior-year column" in hits[0].reason
        assert "FY21-22" in hits[0].reason

    def test_a_year_mismatch_alone_can_sink_a_candidate(self):
        """Same provenance, same corroboration -- only the year differs."""
        good = cand()
        bad = cand(value=1411297.74, year_label=PRIOR, is_prior_year_column=True)
        verdicts = hold_trial([bad, good], ctx())
        assert verdicts[0].candidate.value == pytest.approx(1584207.0)
        assert verdicts[-1].candidate.year_label == PRIOR
        assert verdicts[0].court_score - verdicts[-1].court_score >= 60

    def test_unit_mismatch_is_charged_and_explained(self, poisoned_pool):
        verdicts = hold_trial(poisoned_pool, ctx())
        v = next(v for v in verdicts if v.candidate.value > 1e9)
        hits = [h for h in v.prosecutor_hits if h.prosecutor == "unit_mismatch"]
        assert hits
        assert any("scale" in h.reason or "crore assumed" in h.reason for h in hits)

    def test_table_alignment_is_charged_on_a_fuzzy_row_label(self, poisoned_pool):
        verdicts = hold_trial(poisoned_pool, ctx())
        v = next(v for v in verdicts if v.candidate.row_label == "Net Worth")
        hits = [h for h in v.prosecutor_hits if h.prosecutor == "table_alignment"]
        assert hits
        assert "misaligned" in hits[0].reason

    def test_conflicting_values_are_named_in_the_reason(self):
        a = cand(value=70901.0)
        b = cand(
            value=70910.0 * 1.5,  # far enough apart to be a genuine conflict
            page=140,
            table_id="p140-plumber-0",
            section=Section.MDNA,
            section_score=0.6,
        )
        verdicts = hold_trial([a, b], ctx("interest_earned"))
        loser = verdicts[-1]
        hits = [h for h in loser.prosecutor_hits if h.prosecutor == "conflicting_values"]
        assert hits
        assert "conflicting values" in hits[0].reason

    def test_values_within_tolerance_are_not_a_conflict(self):
        # 70,901 vs 70,910 is 0.013% apart -- rounding, not disagreement.
        a = cand(metric="interest_earned", value=70901.0)
        b = cand(metric="interest_earned", value=70910.0, page=140, table_id="p140-0")
        verdicts = hold_trial([a, b], ctx("interest_earned"))
        assert not any(
            h.prosecutor == "conflicting_values"
            for v in verdicts
            for h in v.prosecutor_hits
        )

    def test_every_penalty_carries_a_human_readable_reason(self, poisoned_pool):
        for v in hold_trial(poisoned_pool, ctx()):
            for hit in v.prosecutor_hits:
                assert hit.reason.strip()
                assert hit.penalty > 0

    def test_ordering_is_deterministic(self, poisoned_pool):
        first = [v.candidate.value for v in hold_trial(poisoned_pool, ctx())]
        second = [v.candidate.value for v in hold_trial(list(reversed(poisoned_pool)), ctx())]
        assert first == second
