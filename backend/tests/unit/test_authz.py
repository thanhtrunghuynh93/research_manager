from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import true

from app.core import authz
from app.core.authz import Scope, register_policy, visible_to
from app.core.errors import ForbiddenError
from app.core.types import Role


def _scope(role: Role, project_ids: set | None = None) -> Scope:
    return Scope(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role=role,
        project_ids=frozenset(project_ids or set()),
        access_epoch=1,
    )


@pytest.mark.unit
def test_student_cannot_pass_professor_check() -> None:
    with pytest.raises(ForbiddenError):
        _scope(Role.STUDENT).require_prof()
    _scope(Role.PROF).require_prof()


@pytest.mark.unit
def test_project_membership_check() -> None:
    project = uuid4()
    _scope(Role.STUDENT, {project}).require_project(project)
    with pytest.raises(ForbiddenError):
        _scope(Role.STUDENT).require_project(project)
    _scope(Role.PROF).require_project(project)  # professor sees every project


@pytest.mark.unit
def test_visible_to_fails_closed_without_policy() -> None:
    class Unregistered: ...

    with pytest.raises(RuntimeError):
        visible_to(_scope(Role.PROF), Unregistered)


@pytest.mark.unit
def test_policy_registry_rejects_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(authz, "_POLICIES", {})

    class Thing: ...

    register_policy(Thing)(lambda scope: true())
    with pytest.raises(RuntimeError):
        register_policy(Thing)(lambda scope: true())
    assert Thing in authz.registered_models()
