"""ASSESS-04/05/06: the arithmetic, which happens in Python and never in a language model.

These are the numbers a student sees next to their name, so the rules are literal: an unknown is
not a zero, a missing baseline makes commitment completion unavailable rather than zero, and the
index is withheld entirely unless every applicable dimension could be rated.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.assessment.metrics import (
    NOT_APPLICABLE,
    UNKNOWN,
    Confidence,
    PlanItem,
    SourceStatus,
    confidence,
    coverage_pct,
    plan_completion,
    progress_index,
)

pytestmark = pytest.mark.unit

# ASSESS-03 default weights.
WEIGHTS = {
    "progress": Decimal(30),
    "learning": Decimal(30),
    "rigor": Decimal(25),
    "artifacts": Decimal(15),
}


def test_the_worked_example_from_the_specification() -> None:
    """ASSESS-04: ratings 3, 4, 3, 2 with the default weights give 78.75, displayed as 79."""
    index = progress_index({"progress": 3, "learning": 4, "rigor": 3, "artifacts": 2}, WEIGHTS)

    assert index == 79


def test_every_dimension_at_the_agreed_standard_is_seventy_five() -> None:
    # A 3 means the agreed standard was met, which is deliberately not 100.
    assert progress_index({key: 3 for key in WEIGHTS}, WEIGHTS) == 75


def test_full_marks_and_no_marks() -> None:
    assert progress_index({key: 4 for key in WEIGHTS}, WEIGHTS) == 100
    assert progress_index({key: 0 for key in WEIGHTS}, WEIGHTS) == 0


def test_rounding_is_half_up() -> None:
    # 30x3 + 30x3 + 25x3 + 15x4 over 4 = 78.75 -> 79; the mirror case rounds up too.
    assert progress_index({"progress": 3, "learning": 3, "rigor": 3, "artifacts": 4}, WEIGHTS) == 79
    assert progress_index({"a": 1, "b": 2}, {"a": Decimal(1), "b": Decimal(1)}) == 38  # 37.5


def test_an_unknown_dimension_withholds_the_index() -> None:
    # ASSESS-04: otherwise display "Not rated — insufficient evidence".
    assert (
        progress_index({"progress": 3, "learning": UNKNOWN, "rigor": 3, "artifacts": 2}, WEIGHTS)
        is None
    )


def test_an_unknown_is_not_a_zero() -> None:
    withheld = progress_index(
        {"progress": 3, "learning": UNKNOWN, "rigor": 3, "artifacts": 2}, WEIGHTS
    )
    as_zero = progress_index({"progress": 3, "learning": 0, "rigor": 3, "artifacts": 2}, WEIGHTS)

    assert withheld is None
    assert as_zero == 49, "a zero is a finding; an unknown is an absence of evidence"


def test_a_not_applicable_dimension_renormalises_the_rest() -> None:
    # ASSESS-04: renormalise weights only over dimensions legitimately marked applicable.
    index = progress_index(
        {"progress": 3, "learning": 3, "rigor": 3, "artifacts": NOT_APPLICABLE}, WEIGHTS
    )

    assert index == 75, "the remaining 85 points of weight still average to the standard"


def test_a_not_applicable_dimension_does_not_withhold_the_index() -> None:
    assert (
        progress_index(
            {"progress": 4, "learning": 3, "rigor": 3, "artifacts": NOT_APPLICABLE}, WEIGHTS
        )
        is not None
    )


def test_no_applicable_dimension_means_no_index() -> None:
    assert progress_index({key: NOT_APPLICABLE for key in WEIGHTS}, WEIGHTS) is None


def test_a_rating_outside_the_scale_is_refused() -> None:
    with pytest.raises(ValueError, match="0 and 4"):
        progress_index({"progress": 5}, {"progress": Decimal(30)})


# ------------------------------------------------------------------ commitment completion


def test_commitment_completion_is_weighted_by_the_frozen_plan() -> None:
    # ASSESS-05: 100 x sum(planned_weight x accepted_fraction) / sum(planned_weight).
    items = [
        PlanItem(weight=Decimal(2), accepted_completion=Decimal(1)),
        PlanItem(weight=Decimal(1), accepted_completion=Decimal("0.5")),
    ]

    assert plan_completion(items) == Decimal("83.33")


def test_an_unstarted_commitment_counts_as_nothing_done() -> None:
    items = [
        PlanItem(weight=Decimal(1), accepted_completion=Decimal(1)),
        PlanItem(weight=Decimal(1), accepted_completion=Decimal(0)),
    ]

    assert plan_completion(items) == Decimal("50.00")


def test_completion_is_unavailable_without_a_baseline() -> None:
    # ASSESS-05 / AC-18: a missing or ambiguous baseline makes this unavailable, not zero.
    assert plan_completion(None) is None
    assert plan_completion([]) is None


def test_completion_ignores_a_zero_weight_plan() -> None:
    assert plan_completion([PlanItem(weight=Decimal(0), accepted_completion=Decimal(1))]) is None


def test_a_fraction_outside_the_range_is_refused() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        plan_completion([PlanItem(weight=Decimal(1), accepted_completion=Decimal("1.5"))])


# ------------------------------------------------------------------ coverage and confidence


def test_coverage_is_the_share_of_applicable_weight_that_could_be_rated() -> None:
    # ASSESS-06.
    sufficiency = {"progress": True, "learning": True, "rigor": True, "artifacts": False}

    assert coverage_pct(sufficiency, WEIGHTS) == Decimal("85.00")


def test_coverage_excludes_dimensions_that_do_not_apply() -> None:
    sufficiency = {"progress": True, "learning": True, "rigor": True}

    assert coverage_pct(sufficiency, WEIGHTS) == Decimal("100.00"), "artifacts is not applicable"


def test_coverage_of_nothing_is_zero() -> None:
    assert coverage_pct({}, WEIGHTS) == Decimal("0.00")


def test_full_coverage_with_fresh_sources_is_high_confidence() -> None:
    level, reasons = confidence(
        Decimal("95.00"),
        SourceStatus(report_submitted=True, repository_fresh=True, baseline_available=True),
    )

    assert level is Confidence.HIGH
    assert reasons == []


def test_a_project_without_a_repository_can_still_be_high_confidence() -> None:
    # ASSESS-06: a project without a repository can have full coverage through other artifacts.
    level, _ = confidence(
        Decimal("95.00"),
        SourceStatus(report_submitted=True, repository_fresh=None, baseline_available=True),
    )

    assert level is Confidence.HIGH


def test_a_stale_repository_lowers_confidence_and_says_why() -> None:
    level, reasons = confidence(
        Decimal("95.00"),
        SourceStatus(report_submitted=True, repository_fresh=False, baseline_available=True),
    )

    assert level is Confidence.LOW
    assert any("repository" in reason for reason in reasons)


def test_a_stale_repository_is_never_read_as_zero_work() -> None:
    # AC-04: it reduces confidence; it does not reduce the rating.
    _, reasons = confidence(
        Decimal("95.00"),
        SourceStatus(report_submitted=True, repository_fresh=False, baseline_available=True),
    )

    assert all("no work" not in reason for reason in reasons)


def test_a_missing_baseline_lowers_confidence_and_says_why() -> None:
    level, reasons = confidence(
        Decimal("95.00"),
        SourceStatus(report_submitted=True, repository_fresh=True, baseline_available=False),
    )

    assert level is Confidence.LOW
    assert any("baseline" in reason for reason in reasons)


def test_an_unverifiable_claim_caps_confidence_at_medium() -> None:
    # AC-07: the claim is labelled and the uncertainty is carried into the confidence.
    level, reasons = confidence(
        Decimal("95.00"),
        SourceStatus(
            report_submitted=True,
            repository_fresh=True,
            baseline_available=True,
            unverifiable_claims=1,
        ),
    )

    assert level is Confidence.MEDIUM
    assert any("unverifiable" in reason for reason in reasons)


def test_thin_coverage_is_low_confidence() -> None:
    level, reasons = confidence(
        Decimal("40.00"),
        SourceStatus(report_submitted=True, repository_fresh=True, baseline_available=True),
    )

    assert level is Confidence.LOW
    assert any("coverage" in reason for reason in reasons)


def test_a_missing_report_is_low_confidence() -> None:
    level, reasons = confidence(
        Decimal("60.00"),
        SourceStatus(report_submitted=False, repository_fresh=True, baseline_available=True),
    )

    assert level is Confidence.LOW
    assert any("report" in reason for reason in reasons)


def test_every_reason_is_a_stated_rule_rather_than_a_probability() -> None:
    # ASSESS-06: rule-based reasons rather than an unexplained model probability.
    _, reasons = confidence(
        Decimal("50.00"),
        SourceStatus(
            report_submitted=False,
            repository_fresh=False,
            baseline_available=False,
            unverifiable_claims=2,
            truncated_evidence=True,
        ),
    )

    assert len(reasons) >= 4
    assert all(isinstance(reason, str) and reason for reason in reasons)
