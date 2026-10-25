"""OAuth 2.1 authorization server for the MCP connector (ADR 0025).

Authorization code with PKCE (S256 only), public clients registered dynamically, opaque tokens
stored as digests. A token is bound to the workspace its professor consented in and stops
resolving if the account is deactivated, stops being a professor, or moves to another workspace.

Failures that belong on the token endpoint are `OAuthError`, which carries the RFC 6749 error code;
the router turns it into the JSON body the spec asks for. They are caught in the handler rather than
left to propagate, so the revocation done on a replayed refresh token is committed, not rolled back.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope
from app.core.clock import now
from app.core.types import Role
from app.identity import repository as identity_repository
from app.identity import security
from app.identity import service as identity_service
from app.identity.models import UserState
from app.oauth.models import OAuthClient, OAuthCode, OAuthToken

SCOPE_READ = "rms:read"
SUPPORTED_SCOPES = (SCOPE_READ,)

CODE_TTL = timedelta(minutes=5)
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)

MAX_REDIRECT_URIS = 10
MAX_CLIENT_NAME = 100
_LOOPBACK = ("localhost", "127.0.0.1", "[::1]")


class OAuthError(Exception):
    """An RFC 6749 §5.2 error: `error` is the code, `description` is for a human."""

    def __init__(self, error: str, description: str = "", status_code: int = 400) -> None:
        super().__init__(description or error)
        self.error = error
        self.description = description
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class TokenGrant:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str


@dataclass(frozen=True, slots=True)
class AuthorizeRequest:
    client: OAuthClient
    redirect_uri: str
    code_challenge: str
    scope: str
    resource: str | None
    state: str | None


@dataclass(frozen=True, slots=True)
class McpContext:
    scope: Scope
    user_id: UUID
    token_id: UUID


# ------------------------------------------------------------------ clients


def _redirect_uri_ok(uri: str) -> bool:
    parts = urlsplit(uri)
    if parts.fragment or not parts.netloc:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and (parts.hostname or "") in [h.strip("[]") for h in _LOOPBACK]


async def register_client(
    session: AsyncSession, *, client_name: str, redirect_uris: list[str]
) -> OAuthClient:
    """RFC 7591. Public clients only: PKCE takes the place of a secret."""
    if not redirect_uris or len(redirect_uris) > MAX_REDIRECT_URIS:
        raise OAuthError("invalid_redirect_uri", "give between one and ten redirect URIs")
    if not all(_redirect_uri_ok(uri) for uri in redirect_uris):
        raise OAuthError("invalid_redirect_uri", "redirect URIs must be https, or http on loopback")
    client = OAuthClient(
        client_id=secrets.token_urlsafe(24),
        client_name=(client_name.strip() or "MCP client")[:MAX_CLIENT_NAME],
        redirect_uris=redirect_uris,
    )
    session.add(client)
    await session.flush()
    return client


async def _client_by_public_id(session: AsyncSession, client_id: str) -> OAuthClient | None:
    return (
        await session.execute(select(OAuthClient).where(OAuthClient.client_id == client_id))
    ).scalar_one_or_none()


# ------------------------------------------------------------------ authorization


async def validate_authorize_request(
    session: AsyncSession,
    *,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    code_challenge: str | None,
    code_challenge_method: str | None,
    scope: str | None,
    resource: str | None,
    state: str | None,
) -> AuthorizeRequest:
    """Everything the consent page must trust before it shows a button.

    The client and redirect URI are checked first and raise `OAuthError` with no redirect: sending
    an error to an address the client never registered would make this an open redirector.
    """
    client = await _client_by_public_id(session, client_id)
    if client is None or redirect_uri not in client.redirect_uris:
        raise OAuthError("invalid_request", "unknown client or redirect URI")
    if response_type != "code":
        raise OAuthError("unsupported_response_type", "only response_type=code is supported")
    if not code_challenge or code_challenge_method != "S256":
        raise OAuthError("invalid_request", "PKCE with code_challenge_method=S256 is required")
    requested = (scope or SCOPE_READ).split()
    if not requested or any(item not in SUPPORTED_SCOPES for item in requested):
        raise OAuthError("invalid_scope", f"supported scopes: {' '.join(SUPPORTED_SCOPES)}")
    return AuthorizeRequest(
        client=client,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        scope=" ".join(requested),
        resource=resource,
        state=state,
    )


async def issue_code(session: AsyncSession, scope: Scope, request: AuthorizeRequest) -> str:
    """The professor said yes: mint a single-use code bound to them and to this workspace."""
    scope.require_prof()
    code, digest = security.mint_token()
    at = now()
    session.add(
        OAuthCode(
            code_hash=digest,
            client_id=request.client.id,
            workspace_id=scope.workspace_id,
            user_id=scope.user_id,
            redirect_uri=request.redirect_uri,
            code_challenge=request.code_challenge,
            scope=request.scope,
            resource=request.resource,
            expires_at=at + CODE_TTL,
        )
    )
    write_audit(
        session,
        scope=scope,
        action="oauth.authorized",
        target_table="oauth_clients",
        target_id=request.client.id,
        after={"client": request.client.client_name, "scope": request.scope},
    )
    await session.flush()
    return code


def _pkce_matches(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(computed, challenge)


async def exchange_code(
    session: AsyncSession,
    *,
    client_id: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> TokenGrant:
    client = await _client_by_public_id(session, client_id)
    if client is None:
        raise OAuthError("invalid_client", "unknown client", 401)

    row = (
        await session.execute(
            select(OAuthCode)
            .where(OAuthCode.code_hash == security.hash_token(code))
            .with_for_update()
        )
    ).scalar_one_or_none()
    at = now()
    if (
        row is None
        or row.client_id != client.id
        or row.used_at is not None
        or row.expires_at <= at
        or row.redirect_uri != redirect_uri
        or not _pkce_matches(code_verifier, row.code_challenge)
    ):
        raise OAuthError("invalid_grant", "the code is invalid, expired or already used")

    row.used_at = at
    return await _mint(
        session,
        client=client,
        workspace_id=row.workspace_id,
        user_id=row.user_id,
        scope=row.scope,
    )


async def _mint(
    session: AsyncSession,
    *,
    client: OAuthClient,
    workspace_id: UUID,
    user_id: UUID,
    scope: str,
) -> TokenGrant:
    access, access_hash = security.mint_token()
    refresh, refresh_hash = security.mint_token()
    at = now()
    session.add(
        OAuthToken(
            access_hash=access_hash,
            refresh_hash=refresh_hash,
            client_id=client.id,
            workspace_id=workspace_id,
            user_id=user_id,
            scope=scope,
            access_expires_at=at + ACCESS_TTL,
            refresh_expires_at=at + REFRESH_TTL,
        )
    )
    await session.flush()
    return TokenGrant(
        access_token=access,
        refresh_token=refresh,
        expires_in=int(ACCESS_TTL.total_seconds()),
        scope=scope,
    )


async def refresh(session: AsyncSession, *, client_id: str, refresh_token: str) -> TokenGrant:
    """Rotate: the presented pair is revoked and a new one issued.

    A refresh token that is presented after it was already used is a stolen copy or a confused
    client. Either way the grant is no longer trustworthy, so everything issued to that user and
    client is revoked.
    """
    client = await _client_by_public_id(session, client_id)
    if client is None:
        raise OAuthError("invalid_client", "unknown client", 401)
    row = (
        await session.execute(
            select(OAuthToken)
            .where(OAuthToken.refresh_hash == security.hash_token(refresh_token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    at = now()
    if row is None or row.client_id != client.id:
        raise OAuthError("invalid_grant", "unknown refresh token")
    if row.revoked_at is not None:
        await session.execute(
            update(OAuthToken)
            .where(
                OAuthToken.user_id == row.user_id,
                OAuthToken.client_id == row.client_id,
                OAuthToken.revoked_at.is_(None),
            )
            .values(revoked_at=at)
        )
        await session.flush()
        raise OAuthError("invalid_grant", "the refresh token was already used")
    if row.refresh_expires_at <= at:
        raise OAuthError("invalid_grant", "the refresh token has expired")
    if await _live_professor(session, row) is None:
        row.revoked_at = at
        raise OAuthError("invalid_grant", "the account can no longer use this connection")

    row.revoked_at = at
    return await _mint(
        session,
        client=client,
        workspace_id=row.workspace_id,
        user_id=row.user_id,
        scope=row.scope,
    )


async def revoke(session: AsyncSession, *, token: str) -> None:
    """RFC 7009: unknown tokens are not an error, so a probe learns nothing."""
    digest = security.hash_token(token)
    await session.execute(
        update(OAuthToken)
        .where(
            (OAuthToken.access_hash == digest) | (OAuthToken.refresh_hash == digest),
            OAuthToken.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    )


# ------------------------------------------------------------------ resolving a bearer token


async def _live_professor(session: AsyncSession, row: OAuthToken) -> object | None:
    user = await identity_repository.get_user_in_workspace(session, row.workspace_id, row.user_id)
    if user is None or user.state is not UserState.ACTIVE or user.role is not Role.PROF:
        return None
    return user


async def resolve_access_token(session: AsyncSession, *, token: str) -> McpContext | None:
    """The professor's Scope for a bearer token, or None.

    `get_user_in_workspace` filters on the workspace the token was bound to, so an account that has
    since moved to another workspace is not found and the token is dead (ADR 0025).
    """
    row = (
        await session.execute(
            select(OAuthToken).where(OAuthToken.access_hash == security.hash_token(token))
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.access_expires_at <= now():
        return None
    user = await identity_repository.get_user_in_workspace(session, row.workspace_id, row.user_id)
    if user is None or user.state is not UserState.ACTIVE or user.role is not Role.PROF:
        return None
    row.last_used_at = now()
    return McpContext(
        scope=await identity_service.scope_for(session, user),
        user_id=user.id,
        token_id=row.id,
    )


def redirect_with(request: AuthorizeRequest, **params: str) -> str:
    """The client's redirect URI with `params` (and the caller's `state`, if any) appended."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(request.redirect_uri)
    query = parse_qsl(parts.query) + list(params.items())
    if request.state:
        query.append(("state", request.state))
    return urlunsplit(parts._replace(query=urlencode(query)))
