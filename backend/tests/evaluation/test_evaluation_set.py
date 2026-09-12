"""The evaluation set itself, and the harness that reads it (requirements §13).

These run on every CI pass. They do not call a provider: what they check is that the set still
covers what the specification asks it to cover, and that the harness would actually notice the
defects it exists to notice. A harness that silently passes everything is worse than none, because
it converts an unexamined system into a documented one.
"""

from __future__ import annotations

import pytest

from tests.evaluation.harness import (
    DIMENSIONS,
    Case,
    EvidenceDoc,
    Outcome,
    build_report,
    check_contract,
    load_cases,
    load_questions,
)

pytestmark = pytest.mark.evaluation_contract

REQUIRED_TAGS = {
    "coding",
    "literature",
    "theory",
    "experiments",
    "incomplete-evidence",
    "shared-contribution",
    "negative-result",
    "changed-plan",
    "multilingual",
    "adversarial",
}


def test_the_set_covers_every_category_the_specification_names() -> None:
    """Requirements §13 lists what the evaluation set must contain; this is that list."""
    present = {tag for case in load_cases() for tag in case.tags}

    assert REQUIRED_TAGS <= present, f"missing categories: {sorted(REQUIRED_TAGS - present)}"


def test_every_case_says_why_it_is_in_the_set() -> None:
    """A case with no stated purpose cannot be revised when it starts failing for a new reason."""
    for case in load_cases():
        assert case.notes.strip(), f"{case.case_id} has no notes"


def test_every_rating_in_the_set_is_a_legal_rubric_value() -> None:
    for case in load_cases():
        for dimension in DIMENSIONS:
            value = case.professor_ratings[dimension]
            assert value in {0, 1, 2, 3, 4, "unknown", "not_applicable"}, (
                f"{case.case_id}.{dimension} = {value!r}"
            )


def test_the_incomplete_evidence_case_withholds_the_index_rather_than_scoring_zero() -> None:
    """ASSESS-04: this is the property most worth pinning in the set, not just in the code."""
    incomplete = [case for case in load_cases() if "incomplete-evidence" in case.tags]

    assert incomplete
    for case in incomplete:
        assert case.expected_index_is_none
        assert all(case.professor_ratings[d] == "unknown" for d in DIMENSIONS)


def test_the_adversarial_case_names_the_strings_that_must_not_survive() -> None:
    adversarial = [case for case in load_cases() if case.adversarial]

    assert adversarial
    for case in adversarial:
        assert case.must_not_appear, f"{case.case_id} declares no forbidden output"
        readme = "\n".join(doc.text for doc in case.evidence).lower()
        assert "ignore all previous instructions" in readme


def test_the_question_set_covers_facts_narrative_uncertainty_and_refusal() -> None:
    kinds = {question["kind"] for question in load_questions()}

    assert {"fact", "narrative", "longitudinal", "uncertainty", "confidentiality"} <= kinds


def test_every_fact_question_names_the_function_that_must_answer_it() -> None:
    """QA-02/AC-15: a count is computed in SQL. A question with no named function invites prose."""
    for question in load_questions():
        if question["kind"] == "fact":
            assert question.get("fact_function"), question["id"]


# ------------------------------------------------------------------ the harness notices


def _case(**overrides: object) -> Case:
    base = dict(
        case_id="probe",
        stage="implementation",
        language="en",
        tags=(),
        report="a report",
        evidence=(EvidenceDoc("commit-a.md", "a commit"),),
        professor_ratings=dict.fromkeys(DIMENSIONS, 3),
        expected_index_range=(70, 85),
        expected_index_is_none=False,
        expected_plan_completion=None,
        claim_expectations=(),
        must_not_appear=(),
        adversarial=False,
        notes="probe",
    )
    base.update(overrides)
    return Case(**base)  # type: ignore[arg-type]


def _outcome(**overrides: object) -> Outcome:
    base = dict(
        case_id="probe",
        stage="implementation",
        ratings=dict.fromkeys(DIMENSIONS, 3),
        progress_index=75,
        plan_completion=None,
        text="",
        cited_ids=set(),
        claim_statuses={},
    )
    base.update(overrides)
    return Outcome(**base)  # type: ignore[arg-type]


def test_the_harness_catches_an_index_produced_from_absent_evidence() -> None:
    findings = check_contract(
        _case(expected_index_is_none=True, professor_ratings=dict.fromkeys(DIMENSIONS, "unknown")),
        _outcome(progress_index=62),
    )

    assert {finding.rule for finding in findings} >= {"index_withheld", "unknown_not_zero"}


def test_the_harness_catches_a_citation_that_is_not_in_the_snapshot() -> None:
    findings = check_contract(_case(), _outcome(cited_ids={"commit-a", "commit-invented"}))

    assert [finding.rule for finding in findings] == ["citation_in_snapshot"]


def test_the_harness_catches_an_injected_instruction_that_reached_the_draft() -> None:
    findings = check_contract(
        _case(adversarial=True, must_not_appear=("full disclosure",)),
        _outcome(text="The README requests full disclosure, so ratings were raised."),
    )

    assert [finding.rule for finding in findings] == ["injection_resisted"]


def test_the_harness_catches_a_claim_verified_on_evidence_that_cannot_settle_it() -> None:
    """AC-07/REPO-08: reading a diff does not prove a result."""
    findings = check_contract(
        _case(
            claim_expectations=({"claim_contains": "reduced duplicates", "status": "unverifiable"},)
        ),
        _outcome(claim_statuses={"deduplication reduced duplicates by 11.4 %": "supported"}),
    )

    assert [finding.rule for finding in findings] == ["no_unearned_verification"]


def test_a_draft_that_honours_every_property_produces_no_findings() -> None:
    findings = check_contract(_case(), _outcome(cited_ids={"commit-a"}))

    assert findings == []


def test_the_report_separates_agreement_from_defects() -> None:
    """A single score would let a system that fabricates citations look fine on average."""
    case = _case(case_id="probe")
    report = build_report(
        [case], {"probe": [_outcome(ratings=dict.fromkeys(DIMENSIONS, 1), progress_index=25)]}
    )

    assert report.by_dimension[0].exact == 0.0
    assert report.material_correction_rate == 1.0
    assert report.findings == ()  # disagreement is not a defect
    assert "material correction rate" in report.render()
