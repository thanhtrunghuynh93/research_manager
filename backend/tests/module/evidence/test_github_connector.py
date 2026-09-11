"""REPO-01/02/05 and ADR 0005: the GitHub App connector.

Every request is stubbed, so these tests prove the parts that are ours — the installation token
exchange, pagination, error mapping, webhook verification, and the normalisation of GitHub's
shapes into the connector contract — without depending on GitHub being reachable or on a real App.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.evidence.connectors.base import AuthorizationError, RateLimitedError, RepoRef
from app.evidence.connectors.github import GitHubConnector

pytestmark = pytest.mark.module

REPO = RepoRef(provider="github", external_id="42", full_name="lab/baseline")
WEBHOOK_SECRET = "a shared secret"  # noqa: S105 - test double


@pytest.fixture(scope="module")
def private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def _connector(private_key: str, handler) -> GitHubConnector:
    transport = httpx.MockTransport(handler)
    return GitHubConnector(
        app_id="123",
        private_key=private_key,
        webhook_secret=WEBHOOK_SECRET,
        installation_id="456",
        client=httpx.AsyncClient(transport=transport, base_url="https://api.github.com"),
    )


def _token_response() -> httpx.Response:
    return httpx.Response(
        201, json={"token": "ghs_installation", "expires_at": "2099-01-01T00:00:00Z"}
    )


async def test_it_exchanges_an_app_jwt_for_an_installation_token(private_key: str) -> None:
    # ADR 0005: installation tokens are minted per run and never stored.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/access_tokens"):
            return _token_response()
        return httpx.Response(200, json=[])

    connector = _connector(private_key, handler)
    await connector.list_commits(REPO, None, None)

    token_request = next(r for r in seen if r.url.path.endswith("/access_tokens"))
    assert token_request.headers["Authorization"].startswith("Bearer ")
    api_request = next(r for r in seen if "/commits" in r.url.path)
    assert api_request.headers["Authorization"] == "Bearer ghs_installation"
    assert api_request.headers["Accept"] == "application/vnd.github+json"


async def test_the_token_is_reused_within_one_run(private_key: str) -> None:
    exchanges = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal exchanges
        if request.url.path.endswith("/access_tokens"):
            exchanges += 1
            return _token_response()
        return httpx.Response(200, json=[])

    connector = _connector(private_key, handler)
    await connector.list_commits(REPO, None, None)
    await connector.list_issues(REPO, None, None)

    assert exchanges == 1, "one exchange per run, not one per call"


async def test_commits_keep_author_time_and_commit_time_apart(private_key: str) -> None:
    # REPO-06: these are different facts and GitHub reports both.
    payload = [
        {
            "sha": "aaa",
            "html_url": "https://github.com/lab/baseline/commit/aaa",
            "commit": {
                "message": "Add the loader\n\nDetails follow.",
                "author": {"name": "Student A", "email": "a@example.edu", "date": "2026-09-10T08:00:00Z"},
                "committer": {"name": "Student A", "email": "a@example.edu", "date": "2026-09-14T09:00:00Z"},
            },
            "author": {"login": "student-a", "type": "User"},
            "committer": {"login": "student-a", "type": "User"},
            "stats": {"additions": 40, "deletions": 3},
            "files": [{"filename": "src/loader.py"}],
            "parents": [{"sha": "zzz"}],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return _token_response()
        if request.url.path.endswith("/commits"):
            return httpx.Response(200, json=[{"sha": "aaa"}])
        return httpx.Response(200, json=payload[0])

    connector = _connector(private_key, handler)
    page = await connector.list_commits(REPO, None, None)

    [commit] = page.items
    assert commit.sha == "aaa"
    assert commit.authored_at == datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    assert commit.committed_at == datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
    assert commit.paths == ["src/loader.py"]
    assert commit.additions == 40
    assert {actor.role for actor in commit.actors} == {"author", "committer"}


async def test_a_co_authored_trailer_becomes_a_second_author(private_key: str) -> None:
    # REPO-03/AC-06: Co-authored-by trailers produce joint rows for every resolved co-author.
    detail = {
        "sha": "aaa",
        "commit": {
            "message": "Add the loader\n\nCo-authored-by: Student B <b@example.edu>",
            "author": {"name": "Student A", "email": "a@example.edu", "date": "2026-09-14T09:00:00Z"},
            "committer": {"name": "Student A", "email": "a@example.edu", "date": "2026-09-14T09:00:00Z"},
        },
        "author": {"login": "student-a", "type": "User"},
        "files": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return _token_response()
        if request.url.path.endswith("/commits"):
            return httpx.Response(200, json=[{"sha": "aaa"}])
        return httpx.Response(200, json=detail)

    connector = _connector(private_key, handler)
    page = await connector.list_commits(REPO, None, None)

    emails = {actor.email for actor in page.items[0].actors if actor.role == "author"}
    assert "b@example.edu" in emails


async def test_a_bot_account_is_labelled(private_key: str) -> None:
    detail = {
        "sha": "aaa",
        "commit": {
            "message": "Bump a dependency",
            "author": {"name": "dependabot", "email": "bot@github.com", "date": "2026-09-14T09:00:00Z"},
            "committer": {"name": "dependabot", "email": "bot@github.com", "date": "2026-09-14T09:00:00Z"},
        },
        "author": {"login": "dependabot[bot]", "type": "Bot"},
        "files": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return _token_response()
        if request.url.path.endswith("/commits"):
            return httpx.Response(200, json=[{"sha": "aaa"}])
        return httpx.Response(200, json=detail)

    connector = _connector(private_key, handler)
    page = await connector.list_commits(REPO, None, None)

    assert all(actor.is_bot for actor in page.items[0].actors if actor.login)


async def test_pagination_follows_the_link_header(private_key: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return _token_response()
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[],
            headers={
                "Link": '<https://api.github.com/repositories/42/commits?page=2>; rel="next"'
            },
        )

    connector = _connector(private_key, handler)
    page = await connector.list_commits(REPO, None, None)

    assert page.cursor == "2", "the next page is offered rather than fetched eagerly"


async def test_a_merged_pull_request_reports_its_merger(private_key: str) -> None:
    pulls = [
        {
            "number": 7,
            "title": "Add the loader",
            "state": "closed",
            "body": "",
            "created_at": "2026-09-14T09:00:00Z",
            "updated_at": "2026-09-14T11:00:00Z",
            "merged_at": "2026-09-14T11:00:00Z",
            "merge_commit_sha": "ccc",
            "user": {"login": "student-a", "type": "User"},
            "merged_by": {"login": "prof", "type": "User"},
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return _token_response()
        return httpx.Response(200, json=pulls)

    connector = _connector(private_key, handler)
    page = await connector.list_pull_requests(REPO, None, None)

    [pull_request] = page.items
    assert pull_request.state == "merged"
    roles = {(actor.role, actor.login) for actor in pull_request.actors}
    assert ("author", "student-a") in roles
    assert ("merger", "prof") in roles


async def test_a_diff_beyond_the_cap_is_marked_truncated(private_key: str) -> None:
    # REPO-02: record content omitted due to limits.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return _token_response()
        return httpx.Response(200, text="+" * 5000)

    connector = _connector(private_key, handler)
    result = await connector.get_commit_diff(REPO, "aaa", max_bytes=100)

    assert result.truncated is True
    assert len(result.text.encode()) <= 100


async def test_a_revoked_installation_is_an_authorization_error(private_key: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return _token_response()
        return httpx.Response(401, json={"message": "Bad credentials"})

    connector = _connector(private_key, handler)

    with pytest.raises(AuthorizationError):
        await connector.list_commits(REPO, None, None)


async def test_a_rate_limit_is_told_apart_from_a_refusal(private_key: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return _token_response()
        return httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"X-RateLimit-Remaining": "0", "Retry-After": "120"},
        )

    connector = _connector(private_key, handler)

    with pytest.raises(RateLimitedError) as raised:
        await connector.list_commits(REPO, None, None)
    assert raised.value.retry_after_seconds == 120


async def test_a_forbidden_response_that_is_not_a_rate_limit_is_an_authorization_error(
    private_key: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return _token_response()
        return httpx.Response(403, json={"message": "Resource not accessible by integration"})

    connector = _connector(private_key, handler)

    with pytest.raises(AuthorizationError):
        await connector.list_commits(REPO, None, None)


def test_a_webhook_signature_is_verified(private_key: str) -> None:
    connector = _connector(private_key, lambda request: httpx.Response(200, json=[]))
    body = json.dumps({"repository": {"id": 42}}).encode()
    signature = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()

    event = connector.verify_webhook(
        {"X-Hub-Signature-256": signature, "X-GitHub-Delivery": "d1", "X-GitHub-Event": "push"},
        body,
    )

    assert event is not None
    assert event.delivery_id == "d1"
    assert event.external_repo_id == "42"


def test_a_forged_webhook_is_rejected(private_key: str) -> None:
    connector = _connector(private_key, lambda request: httpx.Response(200, json=[]))
    body = json.dumps({"repository": {"id": 42}}).encode()

    assert (
        connector.verify_webhook(
            {"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Delivery": "d1"}, body
        )
        is None
    )
    assert connector.verify_webhook({"X-GitHub-Delivery": "d1"}, body) is None


def test_a_webhook_body_that_was_altered_is_rejected(private_key: str) -> None:
    connector = _connector(private_key, lambda request: httpx.Response(200, json=[]))
    body = json.dumps({"repository": {"id": 42}}).encode()
    signature = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()

    tampered = json.dumps({"repository": {"id": 99}}).encode()

    assert (
        connector.verify_webhook(
            {"X-Hub-Signature-256": signature, "X-GitHub-Delivery": "d1"}, tampered
        )
        is None
    )
