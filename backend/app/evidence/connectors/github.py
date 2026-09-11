"""GitHub App connector (REPO-01, ADR 0005).

A GitHub App installed by the professor on chosen repositories, with read-only permissions. The
installation token is minted from the App's private key for the duration of a run and never
persisted; the private key itself is read from a file outside the repository and never stored in
the database (requirements §9).

Nothing here writes to GitHub, and no repository code is ever executed (REPO-08).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from app.evidence.connectors.base import (
    Actor,
    AuthorizationError,
    CheckSummary,
    CommitMeta,
    ConnectorError,
    DiffResult,
    Issue,
    Page,
    PullRequest,
    RateLimitedError,
    RepoRef,
    Review,
    Visibility,
    WebhookEvent,
)

log = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
ACCEPT = "application/vnd.github+json"
API_VERSION = "2022-11-28"
JWT_LIFETIME = timedelta(minutes=9)  # GitHub caps App JWTs at ten minutes
TOKEN_SAFETY_MARGIN = timedelta(minutes=1)
PAGE_SIZE = 100

_CO_AUTHOR = re.compile(r"^co-authored-by:\s*(?P<name>[^<]*)<(?P<email>[^>]+)>", re.IGNORECASE)
_NEXT_PAGE = re.compile(r'[?&]page=(\d+)[^>]*>;\s*rel="next"')


class GitHubConnector:
    """Read-only access to one installation. One instance per sync run."""

    provider = "github"

    def __init__(
        self,
        *,
        app_id: str,
        private_key: str,
        webhook_secret: str,
        installation_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._app_id = app_id
        self._private_key = private_key
        self._webhook_secret = webhook_secret
        self._installation_id = installation_id
        self._client = client or httpx.AsyncClient(base_url=API_ROOT, timeout=30.0)
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    # ---------------------------------------------------------------- webhooks

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookEvent | None:
        """Reject anything whose HMAC does not hold: an unverified delivery is not evidence."""
        lowered = {key.lower(): value for key, value in headers.items()}
        signature = lowered.get("x-hub-signature-256")
        delivery_id = lowered.get("x-github-delivery")
        if not signature or not delivery_id:
            return None

        expected = (
            "sha256=" + hmac.new(self._webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            log.warning("rejected a GitHub delivery whose signature did not verify")
            return None

        try:
            payload: dict[str, Any] = json.loads(body)
        except json.JSONDecodeError:
            return None

        return WebhookEvent(
            provider="github",
            delivery_id=delivery_id,
            event=lowered.get("x-github-event", "unknown"),
            external_repo_id=str(payload.get("repository", {}).get("id", "")),
            payload=payload,
        )

    # ---------------------------------------------------------------- reads

    async def repo_visibility(self, repo: RepoRef) -> Visibility:
        data = await self._get_json(f"/repos/{repo.full_name}")
        if data.get("private"):
            return "internal" if data.get("visibility") == "internal" else "private"
        return "public"

    async def list_commits(
        self, repo: RepoRef, since: datetime | None, cursor: str | None
    ) -> Page[CommitMeta]:
        params: dict[str, Any] = {"per_page": PAGE_SIZE}
        if since is not None:
            params["since"] = since.astimezone(UTC).isoformat().replace("+00:00", "Z")
        if cursor:
            params["page"] = cursor

        summaries, next_cursor = await self._get_page(f"/repos/{repo.full_name}/commits", params)
        commits = []
        for summary in summaries:
            # The list endpoint omits stats and files, which the rubric prompt needs to see what
            # kind of change this was rather than only how large it was (REPO-07).
            detail = await self._get_json(f"/repos/{repo.full_name}/commits/{summary['sha']}")
            commits.append(_commit_from(detail))
        return Page(items=commits, cursor=next_cursor)

    async def get_commit_diff(self, repo: RepoRef, sha: str, max_bytes: int) -> DiffResult:
        text = await self._get_text(
            f"/repos/{repo.full_name}/commits/{sha}", accept="application/vnd.github.diff"
        )
        encoded = text.encode()
        if len(encoded) > max_bytes:
            # REPO-02: content omitted because of a limit is recorded as omitted.
            return DiffResult(
                sha=sha, text=encoded[:max_bytes].decode(errors="ignore"), truncated=True
            )
        return DiffResult(sha=sha, text=text)

    async def list_pull_requests(
        self, repo: RepoRef, updated_since: datetime | None, cursor: str | None
    ) -> Page[PullRequest]:
        params: dict[str, Any] = {
            "per_page": PAGE_SIZE,
            "state": "all",
            "sort": "updated",
            "direction": "desc",
        }
        if cursor:
            params["page"] = cursor

        rows, next_cursor = await self._get_page(f"/repos/{repo.full_name}/pulls", params)
        pulls = [_pull_request_from(row) for row in rows]
        if updated_since is not None:
            pulls = [pull for pull in pulls if pull.updated_at > updated_since]
        return Page(items=pulls, cursor=next_cursor)

    async def list_reviews(self, repo: RepoRef, pr_number: int) -> list[Review]:
        rows, _ = await self._get_page(
            f"/repos/{repo.full_name}/pulls/{pr_number}/reviews", {"per_page": PAGE_SIZE}
        )
        return [_review_from(row, pr_number) for row in rows if row.get("submitted_at")]

    async def list_issues(
        self, repo: RepoRef, updated_since: datetime | None, cursor: str | None
    ) -> Page[Issue]:
        params: dict[str, Any] = {"per_page": PAGE_SIZE, "state": "all", "sort": "updated"}
        if updated_since is not None:
            params["since"] = updated_since.astimezone(UTC).isoformat().replace("+00:00", "Z")
        if cursor:
            params["page"] = cursor

        rows, next_cursor = await self._get_page(f"/repos/{repo.full_name}/issues", params)
        # GitHub returns pull requests from the issues endpoint; they arrive through their own one.
        issues = [_issue_from(row) for row in rows if "pull_request" not in row]
        return Page(items=issues, cursor=next_cursor)

    async def list_check_runs(self, repo: RepoRef, sha: str) -> list[CheckSummary]:
        data = await self._get_json(
            f"/repos/{repo.full_name}/commits/{sha}/check-runs", {"per_page": PAGE_SIZE}
        )
        return [_check_from(row) for row in data.get("check_runs", [])]

    # ---------------------------------------------------------------- transport

    async def _installation_token(self) -> str:
        """Mint a token for this run, reusing it until shortly before it expires (ADR 0005)."""
        now = datetime.now(tz=UTC)
        if (
            self._token is not None
            and self._token_expires_at is not None
            and now < self._token_expires_at - TOKEN_SAFETY_MARGIN
        ):
            return self._token

        assertion = jwt.encode(
            {
                "iat": int((now - timedelta(seconds=30)).timestamp()),
                "exp": int((now + JWT_LIFETIME).timestamp()),
                "iss": self._app_id,
            },
            self._private_key,
            algorithm="RS256",
        )
        response = await self._client.post(
            f"/app/installations/{self._installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {assertion}",
                "Accept": ACCEPT,
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        _raise_for_status(response)
        payload = response.json()
        self._token = str(payload["token"])
        self._token_expires_at = _parse_time(payload.get("expires_at")) or (
            now + timedelta(hours=1)
        )
        return self._token

    async def _request(
        self, path: str, params: dict[str, Any] | None = None, *, accept: str = ACCEPT
    ) -> httpx.Response:
        token = await self._installation_token()
        try:
            response = await self._client.get(
                path,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": accept,
                    "X-GitHub-Api-Version": API_VERSION,
                },
            )
        except httpx.HTTPError as error:  # a network fault is a gap in coverage, not zero work
            raise ConnectorError(str(error)) from error
        _raise_for_status(response)
        return response

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        data: Any = (await self._request(path, params)).json()
        return data if isinstance(data, dict) else {}

    async def _get_text(self, path: str, *, accept: str) -> str:
        return (await self._request(path, accept=accept)).text

    async def _get_page(
        self, path: str, params: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str | None]:
        response = await self._request(path, params)
        body: Any = response.json()
        rows = body if isinstance(body, list) else []
        match = _NEXT_PAGE.search(response.headers.get("Link", ""))
        return rows, match.group(1) if match else None


def _raise_for_status(response: httpx.Response) -> None:
    """Tell a refusal apart from a throttle: only one of them can be retried as-is (REPO-05)."""
    if response.status_code < 400:
        return
    if response.status_code == 401:
        raise AuthorizationError(_message(response))
    if response.status_code in (403, 429):
        throttled = response.headers.get("X-RateLimit-Remaining") == "0" or (
            response.status_code == 429
        )
        if throttled or "rate limit" in _message(response).lower():
            retry_after = response.headers.get("Retry-After")
            raise RateLimitedError(
                _message(response),
                retry_after_seconds=int(retry_after) if retry_after else None,
            )
        raise AuthorizationError(_message(response))
    raise ConnectorError(f"{response.status_code}: {_message(response)}")


def _message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    return str(payload.get("message", "")) if isinstance(payload, dict) else ""


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _actor_from(
    account: Any, role: str, *, email: str | None = None, name: str | None = None
) -> Actor:
    login = account.get("login") if isinstance(account, dict) else None
    is_bot = bool(
        isinstance(account, dict)
        and (account.get("type") == "Bot" or str(login or "").endswith("[bot]"))
    )
    return Actor(role=role, login=login, email=email, name=name, is_bot=is_bot)  # type: ignore[arg-type]


def _commit_from(detail: dict[str, Any]) -> CommitMeta:
    commit = detail.get("commit", {})
    message = str(commit.get("message", ""))
    author_meta = commit.get("author", {}) or {}
    committer_meta = commit.get("committer", {}) or {}

    actors = [
        _actor_from(
            detail.get("author") or {},
            "author",
            email=author_meta.get("email"),
            name=author_meta.get("name"),
        )
    ]
    if detail.get("committer") or committer_meta:
        actors.append(
            _actor_from(
                detail.get("committer") or {},
                "committer",
                email=committer_meta.get("email"),
                name=committer_meta.get("name"),
            )
        )
    # REPO-03: a Co-authored-by trailer names someone who worked on this too.
    for line in message.splitlines():
        match = _CO_AUTHOR.match(line.strip())
        if match:
            actors.append(
                Actor(
                    role="author",
                    login=None,
                    email=match.group("email").strip(),
                    name=match.group("name").strip() or None,
                )
            )

    stats = detail.get("stats", {}) or {}
    files = detail.get("files", []) or []
    return CommitMeta(
        sha=str(detail.get("sha", "")),
        message=message,
        authored_at=_parse_time(author_meta.get("date")) or datetime.now(tz=UTC),
        committed_at=_parse_time(committer_meta.get("date"))
        or _parse_time(author_meta.get("date"))
        or datetime.now(tz=UTC),
        actors=actors,
        paths=[str(entry.get("filename", "")) for entry in files],
        additions=int(stats.get("additions", 0)),
        deletions=int(stats.get("deletions", 0)),
        files_changed=len(files),
        parents=[str(parent.get("sha", "")) for parent in detail.get("parents", []) or []],
    )


def _pull_request_from(row: dict[str, Any]) -> PullRequest:
    merged_at = _parse_time(row.get("merged_at"))
    actors = [_actor_from(row.get("user") or {}, "author")]
    if row.get("merged_by"):
        # AC-06: recorded as the merger, which is not authorship.
        actors.append(_actor_from(row["merged_by"], "merger"))
    return PullRequest(
        number=int(row.get("number", 0)),
        title=str(row.get("title", "")),
        state="merged" if merged_at else ("closed" if row.get("state") == "closed" else "open"),
        created_at=_parse_time(row.get("created_at")) or datetime.now(tz=UTC),
        updated_at=_parse_time(row.get("updated_at")) or datetime.now(tz=UTC),
        merged_at=merged_at,
        merge_commit_sha=row.get("merge_commit_sha"),
        actors=actors,
        body=str(row.get("body") or ""),
    )


def _review_from(row: dict[str, Any], pr_number: int) -> Review:
    state = str(row.get("state", "")).lower()
    return Review(
        external_id=str(row.get("id", "")),
        pull_request_number=pr_number,
        state=(
            "approved"
            if state == "approved"
            else "changes_requested"
            if state == "changes_requested"
            else "dismissed"
            if state == "dismissed"
            else "commented"
        ),
        submitted_at=_parse_time(row.get("submitted_at")) or datetime.now(tz=UTC),
        actor=_actor_from(row.get("user") or {}, "reviewer"),
        body=str(row.get("body") or ""),
    )


def _issue_from(row: dict[str, Any]) -> Issue:
    return Issue(
        number=int(row.get("number", 0)),
        title=str(row.get("title", "")),
        state="closed" if row.get("state") == "closed" else "open",
        created_at=_parse_time(row.get("created_at")) or datetime.now(tz=UTC),
        updated_at=_parse_time(row.get("updated_at")) or datetime.now(tz=UTC),
        actors=[_actor_from(row.get("user") or {}, "author")],
        body=str(row.get("body") or ""),
    )


def _check_from(row: dict[str, Any]) -> CheckSummary:
    conclusion = str(row.get("conclusion") or "neutral")
    allowed = {"success", "failure", "neutral", "cancelled", "timed_out", "skipped"}
    return CheckSummary(
        external_id=str(row.get("id", "")),
        name=str(row.get("name", "")),
        conclusion=conclusion if conclusion in allowed else "neutral",  # type: ignore[arg-type]
        completed_at=_parse_time(row.get("completed_at")),
        details_url=row.get("details_url"),
    )
