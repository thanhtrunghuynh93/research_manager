"""Running the evaluation set through a gateway (requirements §13, docs/evaluation/protocol.md).

Two tests, deliberately different in kind.

The first runs every case through the deterministic gateway on each CI pass. It proves the harness
and the pipeline fit together and that the withholding rules hold, and it proves nothing about
rubric quality — the fake has no opinion about research.

The second runs against the real provider and is skipped unless `RM_EVAL=1`, because it costs money
and because agreement is a calibration question rather than a regression. It asserts only the
pass/fail properties. The agreement numbers are printed for the professor to read: asserting a
threshold nobody has agreed to would turn calibration into a test that gets tuned until it passes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.ai.fake import FakeGateway
from app.ai.gateway import build_gateway
from app.core.config import get_settings
from tests.evaluation import harness
from tests.evaluation.runner import run_case


@pytest.mark.evaluation_contract
async def test_every_case_runs_and_the_withholding_rules_hold_on_the_fake_gateway() -> None:
    cases = harness.load_cases()
    outcomes = {case.case_id: [await run_case(case, FakeGateway())] for case in cases}

    report = harness.build_report(cases, outcomes)
    print(report.render())  # noqa: T201 - the report is the point of the test

    assert report.errored_cases == (), f"cases that never ran: {report.errored_cases}"
    assert report.cases == len(cases), "every case is measured, or the rest below means nothing"
    assert report.findings == (), "\n".join(
        f"[{finding.rule}] {finding.case_id}: {finding.detail}" for finding in report.findings
    )
    assert report.uncertainty_cases_passed.startswith("1/") or report.uncertainty_cases_passed == (
        "0/0"
    )


@pytest.mark.evaluation
@pytest.mark.skipif(not harness.enabled(), reason="set RM_EVAL=1 to call the model provider")
async def test_calibration_against_the_configured_provider() -> None:
    gateway = build_gateway(get_settings())
    if gateway is None:
        pytest.skip("RM_OPENAI_API_KEY is not configured")

    cases = harness.load_cases()
    outcomes = {
        case.case_id: [await run_case(case, gateway) for _ in range(harness.repeats())]
        for case in cases
    }
    report = harness.build_report(cases, outcomes)

    print(report.render())  # noqa: T201
    destination = Path(os.environ.get("RM_EVAL_REPORT", "evaluation-report.json"))
    destination.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    print(f"wrote {destination}")  # noqa: T201

    # Only the properties that must never break. Agreement is reported, not gated (protocol §4).
    # The first assertion is what keeps the rest honest: rates computed over nothing read as
    # success, so a run where every call failed must not reach them.
    assert report.errored_cases == (), f"cases that never ran: {report.errored_cases}"
    assert report.findings == (), "\n".join(
        f"[{finding.rule}] {finding.case_id}: {finding.detail}" for finding in report.findings
    )
    assert report.citation_support_rate >= harness.CITATION_SUPPORT_GATE
