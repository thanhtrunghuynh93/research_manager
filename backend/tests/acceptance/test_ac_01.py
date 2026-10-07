"""AC-01 — A student belongs to two projects, one with attached evidence and one without | One
weekly package contains both project entries; two separate assessments use appropriate evidence.

The assessment half arrives with the assessment module; what is provable now is that one package
carries both entries and that they stay separately addressable.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models as identity_models
from tests.factories import make_week, submit

pytestmark = pytest.mark.acceptance


async def test_ac_01_one_package_carries_an_entry_for_each_project(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await make_week(db, prof_scope, [student_a], projects=2)

    version = await submit(db, student_a, week)

    assert {e.project_id for e in version.entries} == {p.id for p in week.projects}
    assert len({e.id for e in version.entries}) == 2, "each project keeps its own entry"
