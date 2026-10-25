"""ADR 0025: the /mcp endpoint, over HTTP with a bearer token."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEvent
from app.core.authz import Scope
from app.core.types import Role
from app.identity import models as identity_models
from app.mcp.server import STUDENT_TEXT_NOTICE
from app.oauth import service as oauth_service
from tests.factories import make_entry, make_user, make_week, make_workspace, submit

pytestmark = pytest.mark.module

ON_TIME = datetime(2026, 9, 18, 3, 0, tzinfo=UTC)
VERIFIER = "m" * 64


async def _token(db: AsyncSession, scope: Scope) -> str:
    """A bearer token for `scope`'s professor, made the way the consent page makes one."""
    client = await oauth_service.register_client(
        db, client_name="Claude", redirect_uris=["https://claude.ai/cb"]
    )
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
    )
    request = await oauth_service.validate_authorize_request(
        db,
        client_id=client.client_id,
        redirect_uri="https://claude.ai/cb",
        response_type="code",
        code_challenge=challenge,
        code_challenge_method="S256",
        scope=None,
        resource=None,
        state=None,
    )
    code = await oauth_service.issue_code(db, scope, request)
    grant = await oauth_service.exchange_code(
        db,
        client_id=client.client_id,
        code=code,
        redirect_uri="https://claude.ai/cb",
        code_verifier=VERIFIER,
    )
    return grant.access_token


async def _rpc(
    client: AsyncClient, token: str, method: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = await client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _call(client: AsyncClient, token: str, name: str, **arguments: Any) -> dict[str, Any]:
    reply = await _rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
    return dict(reply["result"])


def _json(result: dict[str, Any]) -> Any:
    text = result["content"][0]["text"]
    return json.loads(text[text.index("\n\n") + 2 :] if text.startswith("The JSON") else text)


async def test_no_token_is_401_and_points_at_the_discovery_document(client: AsyncClient) -> None:
    response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})

    assert response.status_code == 401
    assert "oauth-protected-resource" in response.headers["www-authenticate"]


async def test_a_bad_token_is_401(client: AsyncClient) -> None:
    response = await client.post(
        "/mcp",
        headers={"Authorization": "Bearer nope"},
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )

    assert response.status_code == 401


async def test_get_is_405(client: AsyncClient) -> None:
    assert (await client.get("/mcp")).status_code == 405


async def test_initialize_and_list_tools(client: AsyncClient, db: AsyncSession, prof_scope) -> None:
    token = await _token(db, prof_scope)

    init = await _rpc(client, token, "initialize", {"protocolVersion": "2025-06-18"})
    tools = (await _rpc(client, token, "tools/list"))["result"]["tools"]

    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert {tool["name"] for tool in tools} >= {"whoami", "list_reports", "get_overview"}
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
    assert all(tool["inputSchema"]["type"] == "object" for tool in tools)


async def test_a_notification_is_accepted_without_a_body(
    client: AsyncClient, db: AsyncSession, prof_scope
) -> None:
    token = await _token(db, prof_scope)

    response = await client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    assert response.status_code == 202


async def test_an_unknown_method_is_a_json_rpc_error(
    client: AsyncClient, db: AsyncSession, prof_scope
) -> None:
    reply = await _rpc(client, await _token(db, prof_scope), "resources/list")

    assert reply["error"]["code"] == -32601


async def test_whoami_names_the_professor_and_workspace(
    client: AsyncClient, db: AsyncSession, prof: identity_models.User, prof_scope
) -> None:
    result = await _call(client, await _token(db, prof_scope), "whoami")

    body = _json(result)
    assert body["user"]["email"] == prof.email
    assert body["workspace"]["id"] == str(prof.workspace_id)


async def test_bad_arguments_are_a_tool_error_not_a_crash(
    client: AsyncClient, db: AsyncSession, prof_scope
) -> None:
    result = await _call(client, await _token(db, prof_scope), "get_report_version", version_id="x")

    assert result["isError"] is True
    assert "version_id" in result["content"][0]["text"]


async def test_a_missing_record_is_a_tool_error(
    client: AsyncClient, db: AsyncSession, prof_scope
) -> None:
    result = await _call(
        client,
        await _token(db, prof_scope),
        "get_report_version",
        version_id="01a158aa-8263-74cb-81af-fbe0a4a9ea2c",
    )

    assert result["isError"] is True


async def test_list_reports_gives_submitted_reports_quoted_as_data(
    client: AsyncClient,
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, [student_a, student_b])
    await submit(db, student_a, week, make_entry(week.project.id, work="Wrote the loader"))
    token = await _token(db, prof_scope)

    result = await _call(client, token, "list_reports")

    assert result["isError"] is False
    assert result["content"][0]["text"].startswith(STUDENT_TEXT_NOTICE)
    items = _json(result)["items"]
    assert [item["student_id"] for item in items] == [str(student_a.id)]

    versions = _json(
        await _call(client, token, "list_report_versions", report_id=items[0]["report_id"])
    )
    detail = await _call(client, token, "get_report_version", version_id=versions[0]["id"])
    assert detail["content"][0]["text"].startswith(STUDENT_TEXT_NOTICE)
    assert "Wrote the loader" in detail["content"][0]["text"]


async def test_every_read_tool_answers_over_a_real_week(
    client: AsyncClient,
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, [student_a])
    await submit(db, student_a, week)
    token = await _token(db, prof_scope)
    period, project, student = str(week.period.id), str(week.project.id), str(student_a.id)

    calls: list[tuple[str, dict[str, Any]]] = [
        ("whoami", {}),
        ("list_students", {}),
        ("list_projects", {"status": "active"}),
        ("list_periods", {}),
        ("list_obligations", {"period_id": period}),
        ("get_overview", {}),
        ("list_reports", {"needs_review": True}),
        ("list_assessments", {"student_id": student}),
        ("get_trend", {"student_id": student, "project_id": project}),
        ("list_attachments", {"student_id": student}),
    ]
    for name, arguments in calls:
        result = await _call(client, token, name, **arguments)
        assert result["isError"] is False, (name, result)


async def test_another_workspaces_reports_are_invisible(
    client: AsyncClient,
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, [student_a])
    await submit(db, student_a, week)

    other = await make_workspace(db, name="Elsewhere")
    other_prof = await make_user(db, other, role=Role.PROF)
    from app.identity import service as identity_service

    token = await _token(db, await identity_service.scope_for(db, other_prof))

    items = _json(await _call(client, token, "list_reports"))["items"]

    assert items == []


async def test_a_call_is_audited_with_the_tool_name(
    client: AsyncClient, db: AsyncSession, prof: identity_models.User, prof_scope
) -> None:
    await _call(client, await _token(db, prof_scope), "list_projects")

    events = (
        (await db.execute(select(AuditEvent).where(AuditEvent.action == "mcp.tool_called")))
        .scalars()
        .all()
    )
    assert [(e.actor_id, e.after) for e in events] == [(prof.id, {"tool": "list_projects"})]
