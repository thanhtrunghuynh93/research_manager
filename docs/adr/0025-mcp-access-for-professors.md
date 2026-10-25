# ADR 0025 — MCP access for professors, through OAuth tokens bound to one workspace

Status: accepted — 2026-10-20

## Context

A professor wants to ask Claude about their workspace — who owes a report, what a student wrote,
what an assessment concluded — from a Claude connector. A connector speaks MCP over Streamable HTTP
and signs in with OAuth 2.1 (authorization code with PKCE, dynamic client registration). The API's
only credential is the `rm_session` cookie, which a connector cannot hold, and which should not be
minted for one.

## Decision

**The application serves a read-only MCP endpoint at `/mcp`, and is its own OAuth authorization
server.**

- Only a professor can authorise a connector. A student's account is refused at the consent step.
- A token is an opaque secret whose SHA-256 digest is stored, like a session (architecture §6.2). It
  names one user, one client and **one workspace**, fixed when the professor consents.
- Resolving a token runs the same `identity.service.scope_for` a session does, so every tool sees
  exactly the rows the professor sees in the app and nothing the visibility predicates hide.
- If the account is deactivated, demoted, or has moved to another workspace since consent, the
  token stops resolving. The professor reconnects to bind it to the new one. This is ADR 0021 held
  at the connector: a `Scope` names one workspace.
- Consent happens on a page of the single-page app, behind the ordinary login. The OAuth endpoints
  never see a password.
- Tools are read-only. Writes (marking a report reviewed, requesting a revision) are a later
  decision and would need their own scope and an audit actor that names the connector.
- Refresh tokens rotate. Presenting a refresh token that was already used revokes everything issued
  to that user and client.

## Consequences

- A new module `app.oauth` (tables `oauth_clients`, `oauth_codes`, `oauth_tokens`, migration 0031)
  sits directly above `app.identity` in the layer order; `app.mcp` sits above everything and calls
  services only, never models.
- Report and attachment text reaches Claude's context. It is written by students, so tool output
  labels it as quoted data. `ai_restricted` is not consulted: no project uses it (the column stays
  for the assessment step, ADR 0024) and the professor already holds the right to read the text.
- Every tool call is audited with the user and the tool name.
- Caddy forwards `/mcp`, `/oauth/*` and `/.well-known/oauth-*` to the API.
