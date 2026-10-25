"""Request and response shapes for the OAuth endpoints and the consent page (ADR 0025)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClientRegistrationIn(BaseModel):
    client_name: str = Field(default="", max_length=200)
    redirect_uris: list[str] = Field(default_factory=list)


class ClientRegistrationOut(BaseModel):
    client_id: str
    client_name: str
    redirect_uris: list[str]
    token_endpoint_auth_method: str = "none"  # noqa: S105 - OAuth method name
    grant_types: list[str] = ["authorization_code", "refresh_token"]
    response_types: list[str] = ["code"]


class AuthorizeIn(BaseModel):
    """What the SPA consent page posts back: the query string it was opened with."""

    client_id: str
    redirect_uri: str
    response_type: str = "code"
    code_challenge: str | None = None
    code_challenge_method: str | None = None
    scope: str | None = None
    resource: str | None = None
    state: str | None = None


class ConsentOut(BaseModel):
    client_name: str
    scope: str
    workspace_name: str


class AuthorizeOut(BaseModel):
    redirect_to: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"  # noqa: S105 - OAuth token type
    expires_in: int
    refresh_token: str
    scope: str
