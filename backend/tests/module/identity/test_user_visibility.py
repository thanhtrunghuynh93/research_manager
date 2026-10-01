"""AUTH-02: the same visibility predicate decides every read of a user record.

Within a workspace, who sees whom is covered over HTTP in tests/api/test_users.py; these are the
two halves that are not: the workspace boundary, and that the predicate is a plain query filter.

Reading a user through the service, listing users, and (once they land) search, download, export
and AI retrieval all compile the predicate registered in identity/policies.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.core.errors import NotFoundError
from app.identity import models, service
from tests.factories import make_user, make_workspace

pytestmark = pytest.mark.module


async def test_the_professor_does_not_see_another_workspace(
    db: AsyncSession, prof_scope: Scope
) -> None:
    other = await make_workspace(db, name="Another Lab")
    outsider = await make_user(db, other)

    page = await service.list_users(db, prof_scope)

    assert outsider.id not in {user.id for user in page.items}
    with pytest.raises(NotFoundError):
        await service.get_user(db, prof_scope, outsider.id)


async def test_the_predicate_is_the_same_one_any_query_would_use(
    db: AsyncSession, student_a_scope: Scope, student_a: models.User, student_b: models.User
) -> None:
    rows = (
        (await db.execute(select(models.User.id).where(visible_to(student_a_scope, models.User))))
        .scalars()
        .all()
    )

    assert rows == [student_a.id]
    assert student_b.id not in rows
