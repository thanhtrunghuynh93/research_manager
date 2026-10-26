"""ADR 0026: feedback written through the MCP tools, read by the student through the API."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEvent
from app.core.storage import InMemoryObjectStore, register_store
from app.core.types import Role
from app.feedback.models import FeedbackAttachment, FeedbackRevision
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.oauth import service as oauth_service
from app.reporting import service as reporting_service
from tests.api.test_mcp import _call, _json, _rpc, _token
from tests.factories import Week, login, make_entry, make_user, make_week, make_workspace, submit

pytestmark = pytest.mark.module

ON_TIME = datetime(2026, 9, 18, 3, 0, tzinfo=UTC)
HTML = b"<html><body><h1>Phan hoi MealAgent</h1><script>alert(1)</script></body></html>"


@pytest.fixture(autouse=True)
def store() -> InMemoryObjectStore:
    memory = InMemoryObjectStore()
    register_store(memory)
    return memory


class Setup:
    def __init__(self, minh: identity_models.User, week: Week, reports: list[str]) -> None:
        self.minh = minh
        self.project_id = str(week.project.id)
        self.reports = reports


@pytest.fixture
async def minh(db: AsyncSession, workspace: identity_models.Workspace) -> identity_models.User:
    return await make_user(
        db, workspace, role=Role.STUDENT, email="minh@example.edu", display_name="Minh Dang"
    )


@pytest.fixture
async def setup(
    db: AsyncSession,
    prof_scope,
    minh: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> Setup:
    """Minh Dang on MealAgent with two submitted weekly reports."""
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, [minh], title="MealAgent", through=date(2026, 9, 27))
    periods = await reporting_service.list_periods(db, prof_scope, through=date(2026, 9, 27))
    reports = []
    for period in periods[:2]:
        await reporting_service.ensure_obligations(db, prof_scope, period.id)
        report = await submit(
            db,
            minh,
            Week(period=period, projects=week.projects),
            make_entry(week.project.id, work=f"Work in {period.local_start}"),
        )
        reports.append(str(report.report_id if hasattr(report, "report_id") else report.id))
    return Setup(minh, week, reports)


async def _create(
    client: AsyncClient, token: str, setup: Setup, workspace_id: Any, **extra: Any
) -> dict[str, Any]:
    result = await _call(
        client,
        token,
        "create_feedback",
        workspace_id=str(workspace_id),
        student_id=str(setup.minh.id),
        project_id=setup.project_id,
        report_ids=setup.reports,
        title="Phản hồi MealAgent — các tuần gần đây",
        body_markdown="## Nhận xét\n\nLàm tốt phần loader.",
        **extra,
    )
    assert result["isError"] is False, result
    return dict(_json(result))


async def test_a_draft_is_created_with_two_reports_and_the_backend_names_the_author(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    token = await _token(db, prof_scope)

    feedback = await _create(client, token, setup, prof.workspace_id)

    assert feedback["status"] == "draft"
    assert feedback["version"] == 1
    assert sorted(feedback["report_ids"]) == sorted(setup.reports)
    assert len(feedback["reports"]) == 2
    assert feedback["created_by"] == str(prof.id)
    assert feedback["view_url"].endswith(f"/feedback/{feedback['feedback_id']}")


async def test_a_client_cannot_name_the_author(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    token = await _token(db, prof_scope)

    feedback = await _create(client, token, setup, prof.workspace_id, author_id=str(setup.minh.id))

    assert feedback["created_by"] == str(prof.id)


async def test_the_student_sees_nothing_until_publication_and_then_exactly_what_was_published(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    token = await _token(db, prof_scope)
    ws = str(prof.workspace_id)  # read now: a 404 below rolls the session back and expires `prof`
    created = await _create(client, token, setup, prof.workspace_id)
    fid = created["feedback_id"]

    await login(client, setup.minh)
    assert (await client.get("/api/v1/feedback")).json()["items"] == []
    assert (await client.get(f"/api/v1/feedback/{fid}")).status_code == 404

    published = _json(
        await _call(
            client,
            token,
            "publish_feedback",
            workspace_id=ws,
            feedback_id=fid,
            expected_version=1,
        )
    )
    assert published["status"] == "published"

    items = (await client.get("/api/v1/feedback")).json()["items"]
    assert [item["feedback_id"] for item in items] == [fid]
    seen = (await client.get(f"/api/v1/feedback/{fid}")).json()
    assert seen["body_markdown"] == "## Nhận xét\n\nLàm tốt phần loader."
    assert seen["has_unpublished_changes"] is False


async def test_another_student_never_sees_a_published_feedback(
    client: AsyncClient,
    db: AsyncSession,
    prof,
    prof_scope,
    setup: Setup,
    student_b: identity_models.User,
) -> None:
    token = await _token(db, prof_scope)
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]
    await _call(
        client,
        token,
        "publish_feedback",
        workspace_id=str(prof.workspace_id),
        feedback_id=fid,
        expected_version=1,
    )

    await login(client, student_b)

    assert (await client.get("/api/v1/feedback")).json()["items"] == []
    assert (await client.get(f"/api/v1/feedback/{fid}")).status_code == 404


async def test_an_html_file_round_trips_with_a_matching_sha256_and_is_a_download(
    client: AsyncClient,
    db: AsyncSession,
    prof,
    prof_scope,
    setup: Setup,
    store: InMemoryObjectStore,
) -> None:
    token = await _token(db, prof_scope)
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]

    result = await _call(
        client,
        token,
        "upload_feedback_attachment",
        workspace_id=str(prof.workspace_id),
        feedback_id=fid,
        filename="phan-hoi-mealagent.html",
        content_base64=base64.b64encode(HTML).decode(),
    )

    assert result["isError"] is False, result
    feedback = _json(result)
    [attachment] = feedback["attachments"]
    assert attachment["sha256"] == hashlib.sha256(HTML).hexdigest()
    assert attachment["content_type"] == "text/html"
    assert attachment["byte_size"] == len(HTML)
    assert feedback["version"] == 2
    stored = (
        await db.execute(
            select(FeedbackAttachment.storage_key).where(
                FeedbackAttachment.id == attachment["attachment_id"]
            )
        )
    ).scalar_one()
    assert hashlib.sha256(await store.get_bytes(stored) or b"").hexdigest() == attachment["sha256"]

    again = _json(
        await _call(
            client,
            token,
            "get_feedback",
            workspace_id=str(prof.workspace_id),
            feedback_id=fid,
        )
    )
    assert again["attachments"][0]["download_url"]


async def test_the_student_gets_the_file_only_after_publication(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    token = await _token(db, prof_scope)
    ws = str(prof.workspace_id)  # read now: a 404 below rolls the session back and expires `prof`
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]
    feedback = _json(
        await _call(
            client,
            token,
            "upload_feedback_attachment",
            workspace_id=ws,
            feedback_id=fid,
            filename="phan-hoi-mealagent.html",
            content_base64=base64.b64encode(HTML).decode(),
        )
    )
    attachment_id = feedback["attachments"][0]["attachment_id"]
    link = f"/api/v1/feedback/attachments/{attachment_id}/download"

    await login(client, setup.minh)
    assert (await client.get(link)).status_code == 404

    await _call(
        client,
        token,
        "publish_feedback",
        workspace_id=ws,
        feedback_id=fid,
        expected_version=feedback["version"],
    )
    response = await client.get(link)
    assert response.status_code == 200
    assert response.json()["filename"] == "phan-hoi-mealagent.html"
    seen = (await client.get(f"/api/v1/feedback/{fid}")).json()
    assert [a["sha256"] for a in seen["attachments"]] == [hashlib.sha256(HTML).hexdigest()]


async def test_the_two_step_upload_attaches_only_after_the_bytes_are_verified(
    client: AsyncClient,
    db: AsyncSession,
    prof,
    prof_scope,
    setup: Setup,
    store: InMemoryObjectStore,
) -> None:
    token = await _token(db, prof_scope)
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]
    ws = str(prof.workspace_id)

    grant = _json(
        await _call(
            client,
            token,
            "upload_feedback_attachment",
            workspace_id=ws,
            feedback_id=fid,
            filename="notes.md",
            byte_size=len(b"# hi"),
            sha256=hashlib.sha256(b"# hi").hexdigest(),
        )
    )
    assert grant["state"] == "pending"
    before = _json(await _call(client, token, "get_feedback", workspace_id=ws, feedback_id=fid))
    assert before["attachments"] == []  # granted, not attached

    key = (
        await db.execute(
            select(FeedbackAttachment.storage_key).where(
                FeedbackAttachment.id == grant["attachment_id"]
            )
        )
    ).scalar_one()
    await store.put_bytes(key, b"# hi", content_type="text/markdown")
    confirmed = _json(
        await _call(
            client,
            token,
            "upload_feedback_attachment",
            workspace_id=ws,
            feedback_id=fid,
            attachment_id=grant["attachment_id"],
        )
    )
    assert [a["filename"] for a in confirmed["attachments"]] == ["notes.md"]

    repeated = _json(
        await _call(
            client,
            token,
            "upload_feedback_attachment",
            workspace_id=ws,
            feedback_id=fid,
            attachment_id=grant["attachment_id"],
        )
    )
    assert repeated["version"] == confirmed["version"]  # no second revision, no duplicate


@pytest.mark.parametrize(
    ("bytes_in_store", "declared"),
    [
        (b"", "missing"),  # nothing was ever uploaded
        (b"# other", "wrong-bytes"),  # different content from what was declared
    ],
)
async def test_a_failed_upload_leaves_no_attachment(
    client: AsyncClient,
    db: AsyncSession,
    prof,
    prof_scope,
    setup: Setup,
    store: InMemoryObjectStore,
    bytes_in_store: bytes,
    declared: str,
) -> None:
    token = await _token(db, prof_scope)
    ws = str(prof.workspace_id)
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]
    grant = _json(
        await _call(
            client,
            token,
            "upload_feedback_attachment",
            workspace_id=ws,
            feedback_id=fid,
            filename="notes.md",
            byte_size=4,
            sha256=hashlib.sha256(b"# hi").hexdigest(),
        )
    )
    key = (
        await db.execute(
            select(FeedbackAttachment.storage_key).where(
                FeedbackAttachment.id == grant["attachment_id"]
            )
        )
    ).scalar_one()
    if bytes_in_store:
        await store.put_bytes(key, bytes_in_store, content_type="text/markdown")

    result = await _call(
        client,
        token,
        "upload_feedback_attachment",
        workspace_id=ws,
        feedback_id=fid,
        attachment_id=grant["attachment_id"],
    )

    assert result["isError"] is True, declared
    feedback = _json(await _call(client, token, "get_feedback", workspace_id=ws, feedback_id=fid))
    assert feedback["attachments"] == []
    assert feedback["version"] == 1
    assert await store.exists(key) is False


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("malware.exe", b"MZ"),
        ("fake.pdf", b"not a pdf"),
        ("fake.docx", b"not a zip"),
        ("binary.txt", b"abc\x00def"),
        ("empty.md", b""),
    ],
)
async def test_unsupported_or_mislabelled_files_are_refused(
    client: AsyncClient,
    db: AsyncSession,
    prof,
    prof_scope,
    setup: Setup,
    filename: str,
    content: bytes,
) -> None:
    token = await _token(db, prof_scope)
    ws = str(prof.workspace_id)
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]

    result = await _call(
        client,
        token,
        "upload_feedback_attachment",
        workspace_id=ws,
        feedback_id=fid,
        filename=filename,
        content_base64=base64.b64encode(content).decode(),
    )

    assert result["isError"] is True
    count = (await db.execute(select(func.count()).select_from(FeedbackAttachment))).scalar_one()
    assert count == 0 or all(
        row.state == "pending" for row in (await db.execute(select(FeedbackAttachment))).scalars()
    )
    feedback = _json(await _call(client, token, "get_feedback", workspace_id=ws, feedback_id=fid))
    assert feedback["attachments"] == []


async def test_an_oversized_declaration_is_refused_before_any_grant(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    token = await _token(db, prof_scope)
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]

    result = await _call(
        client,
        token,
        "upload_feedback_attachment",
        workspace_id=str(prof.workspace_id),
        feedback_id=fid,
        filename="big.pdf",
        byte_size=21 * 1024 * 1024,
        sha256="a" * 64,
    )

    assert result["isError"] is True
    assert "20 MB" in result["content"][0]["text"]


async def test_the_same_idempotency_key_does_not_create_or_publish_twice(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    token = await _token(db, prof_scope)
    ws = str(prof.workspace_id)

    first = await _create(client, token, setup, prof.workspace_id, idempotency_key="create-1")
    second = await _create(client, token, setup, prof.workspace_id, idempotency_key="create-1")
    assert first["feedback_id"] == second["feedback_id"]

    for _ in range(2):
        await _call(
            client,
            token,
            "publish_feedback",
            workspace_id=ws,
            feedback_id=first["feedback_id"],
            expected_version=1,
            idempotency_key="publish-1",
        )

    listed = _json(await _call(client, token, "list_feedback", workspace_id=ws))
    assert len(listed["items"]) == 1
    published = (
        (
            await db.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "feedback.published",
                    AuditEvent.target_id == UUID(first["feedback_id"]),
                )
            )
        )
        .scalars()
        .all()
    )
    created = (
        (
            await db.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "feedback.created",
                    AuditEvent.target_id == UUID(first["feedback_id"]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(published) == 1
    assert len(created) == 1


async def test_a_key_reused_for_a_different_request_is_refused(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    token = await _token(db, prof_scope)
    await _create(client, token, setup, prof.workspace_id, idempotency_key="k")

    result = await _call(
        client,
        token,
        "create_feedback",
        workspace_id=str(prof.workspace_id),
        student_id=str(setup.minh.id),
        project_id=setup.project_id,
        report_ids=setup.reports,
        title="A different one",
        body_markdown="other",
        idempotency_key="k",
    )

    assert result["isError"] is True


async def test_a_stale_version_is_a_conflict_on_update_and_on_publish(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    token = await _token(db, prof_scope)
    ws = str(prof.workspace_id)
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]
    updated = _json(
        await _call(
            client,
            token,
            "update_feedback",
            workspace_id=ws,
            feedback_id=fid,
            expected_version=1,
            body_markdown="Edited once",
        )
    )
    assert updated["version"] == 2

    stale_update = await _call(
        client,
        token,
        "update_feedback",
        workspace_id=ws,
        feedback_id=fid,
        expected_version=1,
        body_markdown="Edited by someone who read version 1",
    )
    stale_publish = await _call(
        client, token, "publish_feedback", workspace_id=ws, feedback_id=fid, expected_version=1
    )

    assert stale_update["isError"] is True
    assert "version 2" in stale_update["content"][0]["text"]
    assert stale_publish["isError"] is True
    current = _json(await _call(client, token, "get_feedback", workspace_id=ws, feedback_id=fid))
    assert current["body_markdown"] == "Edited once"
    assert current["status"] == "draft"


async def test_editing_after_publication_keeps_what_the_student_reads_until_republished(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    token = await _token(db, prof_scope)
    ws = str(prof.workspace_id)
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]
    await _call(
        client, token, "publish_feedback", workspace_id=ws, feedback_id=fid, expected_version=1
    )

    edited = _json(
        await _call(
            client,
            token,
            "update_feedback",
            workspace_id=ws,
            feedback_id=fid,
            expected_version=1,
            body_markdown="Second thoughts",
        )
    )
    assert edited["version"] == 2
    assert edited["published_version"] == 1
    assert edited["has_unpublished_changes"] is True

    await login(client, setup.minh)
    assert (await client.get(f"/api/v1/feedback/{fid}")).json()["body_markdown"].startswith("## ")

    # Back as the professor (the session cookie is the student's now; MCP uses the bearer token).
    await _call(
        client, token, "publish_feedback", workspace_id=ws, feedback_id=fid, expected_version=2
    )
    seen = (await client.get(f"/api/v1/feedback/{fid}")).json()
    assert seen["body_markdown"] == "Second thoughts"
    assert seen["version"] == 2

    revisions = (
        (
            await db.execute(
                select(FeedbackRevision.version_no).order_by(FeedbackRevision.version_no)
            )
        )
        .scalars()
        .all()
    )
    assert revisions == [1, 2]


async def test_another_workspaces_feedback_and_students_cannot_be_reached(
    client: AsyncClient,
    db: AsyncSession,
    prof,
    prof_scope,
    setup: Setup,
) -> None:
    token = await _token(db, prof_scope)
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]

    other = await make_workspace(db, name="Elsewhere")
    other_prof = await make_user(db, other, role=Role.PROF)
    other_student = await make_user(db, other, role=Role.STUDENT)
    other_token = await _token(db, await identity_service.scope_for(db, other_prof))
    ows = str(other.id)

    # The other lab's professor cannot read, change, publish or download ours.
    for name, arguments in (
        ("get_feedback", {"feedback_id": fid}),
        ("update_feedback", {"feedback_id": fid, "expected_version": 1, "title": "x"}),
        ("publish_feedback", {"feedback_id": fid, "expected_version": 1}),
        (
            "upload_feedback_attachment",
            {
                "feedback_id": fid,
                "filename": "a.txt",
                "content_base64": base64.b64encode(b"x").decode(),
            },
        ),
    ):
        result = await _call(client, other_token, name, workspace_id=ows, **arguments)
        assert result["isError"] is True, name
    assert _json(await _call(client, other_token, "list_feedback", workspace_id=ows))["items"] == []

    # Nor can they write feedback about our student, project or reports in their own lab.
    mixed = await _call(
        client,
        other_token,
        "create_feedback",
        workspace_id=ows,
        student_id=str(setup.minh.id),
        project_id=setup.project_id,
        report_ids=setup.reports,
        title="t",
        body_markdown="b",
    )
    assert mixed["isError"] is True
    # Our reports are no good for their student, either.
    cross = await _call(
        client,
        other_token,
        "create_feedback",
        workspace_id=ows,
        student_id=str(other_student.id),
        project_id=setup.project_id,
        report_ids=setup.reports,
        title="t",
        body_markdown="b",
    )
    assert cross["isError"] is True

    # And a workspace the professor does not belong to cannot be named at all.
    foreign = await _call(
        client, other_token, "get_feedback", workspace_id=str(prof.workspace_id), feedback_id=fid
    )
    assert foreign["isError"] is True


async def test_reports_must_be_the_students_own_and_on_the_project(
    client: AsyncClient,
    db: AsyncSession,
    prof,
    prof_scope,
    setup: Setup,
    student_b: identity_models.User,
) -> None:
    token = await _token(db, prof_scope)
    ws = str(prof.workspace_id)

    wrong_student = await _call(
        client,
        token,
        "create_feedback",
        workspace_id=ws,
        student_id=str(student_b.id),
        project_id=setup.project_id,
        report_ids=setup.reports,
        title="t",
        body_markdown="b",
    )
    not_a_student = await _call(
        client,
        token,
        "create_feedback",
        workspace_id=ws,
        student_id=str(prof.id),
        project_id=setup.project_id,
        report_ids=setup.reports,
        title="t",
        body_markdown="b",
    )
    other_project = await make_project_for(db, prof_scope)
    wrong_project = await _call(
        client,
        token,
        "create_feedback",
        workspace_id=ws,
        student_id=str(setup.minh.id),
        project_id=str(other_project.id),
        report_ids=setup.reports,
        title="t",
        body_markdown="b",
    )

    assert wrong_student["isError"] is True
    assert not_a_student["isError"] is True
    assert wrong_project["isError"] is True
    assert _json(await _call(client, token, "list_feedback", workspace_id=ws))["items"] == []


async def make_project_for(db: AsyncSession, prof_scope) -> Any:
    from tests.factories import make_project

    return await make_project(db, prof_scope, title="Unrelated")


async def test_notify_student_is_refused_rather_than_ignored(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    token = await _token(db, prof_scope)
    ws = str(prof.workspace_id)
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]

    result = await _call(
        client,
        token,
        "publish_feedback",
        workspace_id=ws,
        feedback_id=fid,
        expected_version=1,
        notify_student=True,
    )

    assert result["isError"] is True
    current = _json(await _call(client, token, "get_feedback", workspace_id=ws, feedback_id=fid))
    assert current["status"] == "draft"


async def test_a_read_only_token_cannot_write_and_the_tools_say_which_write(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    client_row = await oauth_service.register_client(
        db, client_name="Old", redirect_uris=["https://claude.ai/cb"]
    )
    import base64 as b64

    verifier = "r" * 64
    challenge = b64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    request = await oauth_service.validate_authorize_request(
        db,
        client_id=client_row.client_id,
        redirect_uri="https://claude.ai/cb",
        response_type="code",
        code_challenge=challenge.decode(),
        code_challenge_method="S256",
        scope="rms:read",
        resource=None,
        state=None,
    )
    code = await oauth_service.issue_code(db, prof_scope, request)
    grant = await oauth_service.exchange_code(
        db,
        client_id=client_row.client_id,
        code=code,
        redirect_uri="https://claude.ai/cb",
        code_verifier=verifier,
    )

    result = await _call(
        client,
        grant.access_token,
        "create_feedback",
        workspace_id=str(prof.workspace_id),
        student_id=str(setup.minh.id),
        project_id=setup.project_id,
        report_ids=setup.reports,
        title="t",
        body_markdown="b",
    )
    assert result["isError"] is True
    assert "rms:feedback" in result["content"][0]["text"]
    reads = await _call(
        client, grant.access_token, "list_feedback", workspace_id=str(prof.workspace_id)
    )
    assert reads["isError"] is False

    tools = {
        tool["name"]: tool
        for tool in (await _rpc(client, grant.access_token, "tools/list"))["result"]["tools"]
    }
    assert tools["list_reports"]["annotations"]["readOnlyHint"] is True
    for name in ("create_feedback", "update_feedback", "publish_feedback"):
        assert tools[name]["annotations"]["readOnlyHint"] is False
        assert tools[name]["annotations"]["destructiveHint"] is False


async def test_create_update_upload_and_publish_are_audited(
    client: AsyncClient, db: AsyncSession, prof, prof_scope, setup: Setup
) -> None:
    token = await _token(db, prof_scope)
    ws = str(prof.workspace_id)
    fid = (await _create(client, token, setup, prof.workspace_id))["feedback_id"]
    await _call(
        client,
        token,
        "upload_feedback_attachment",
        workspace_id=ws,
        feedback_id=fid,
        filename="a.txt",
        content_base64=base64.b64encode(b"hello").decode(),
    )
    await _call(
        client,
        token,
        "update_feedback",
        workspace_id=ws,
        feedback_id=fid,
        expected_version=2,
        title="Retitled",
    )
    await _call(
        client, token, "publish_feedback", workspace_id=ws, feedback_id=fid, expected_version=3
    )

    actions = set(
        (await db.execute(select(AuditEvent.action).where(AuditEvent.action.like("feedback.%"))))
        .scalars()
        .all()
    )

    assert actions >= {
        "feedback.created",
        "feedback.updated",
        "feedback.upload_requested",
        "feedback.attachment_added",
        "feedback.published",
    }
    actors = set(
        (await db.execute(select(AuditEvent.actor_id).where(AuditEvent.action.like("feedback.%"))))
        .scalars()
        .all()
    )
    assert actors == {prof.id}


async def test_a_student_cannot_reach_the_mcp_write_path(
    client: AsyncClient, db: AsyncSession, setup: Setup
) -> None:
    # A token can only be issued to a professor (oauth_service.issue_code), so a student has no
    # bearer; the REST surface has no write routes either.
    await login(client, setup.minh)

    for verb in (client.post, client.put, client.patch):
        response = await verb("/api/v1/feedback", json={})
        assert response.status_code in (404, 405)
