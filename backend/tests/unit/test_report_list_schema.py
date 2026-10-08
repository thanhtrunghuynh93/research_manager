"""The report list spells out assessment statuses that reporting may not import."""

from __future__ import annotations

from typing import get_args

import pytest

from app.assessment.models import ReviewState
from app.reporting.schemas import AssessmentStatus

pytestmark = pytest.mark.unit


def test_the_assessment_status_mirrors_every_review_state() -> None:
    assert set(get_args(AssessmentStatus)) == {state.value for state in ReviewState}
