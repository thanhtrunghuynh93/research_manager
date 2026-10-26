# ADR 0025 — MCP access for professors, one workspace per call

Status: accepted — 2026-10-20; amended 2026-10-26 (a call names its workspace)

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
  names one professor and one client. It also records the workspace they were in at consent, which
  is its **default**.
- **Every tool takes an optional `workspace_id`, and `list_workspaces` names the choices.** One
  call reads exactly one workspace, and only one the professor belongs to now: ownership without
  membership, an archived workspace, and another professor's are all reported as absent. The call
  runs under a copy of the professor's `Scope` with that workspace in it (`identity.service.scope_in`),
  so ADR 0021 holds: a `Scope` names one workspace and widening a read is not a flag. The account
  itself is never moved by a connector.
- The default is the workspace consented in while the professor still belongs to it, and otherwise
  the one their account is working in. Switching workspaces in the app does not repoint a connector.
- Resolving a token runs the same `identity.service.scope_for` a session does, so every tool sees
  exactly the rows the professor sees in the app and nothing the visibility predicates hide.
- If the account is deactivated or stops being a professor, the token stops resolving.
  *(As first accepted, a token also died when the account moved workspace, and a connector could
  read only the workspace it was consented in. A professor who belongs to two labs could not ask
  about the second without reconnecting, so the binding became a default.)*
- Consent happens on a page of the single-page app, behind the ordinary login. The OAuth endpoints
  never see a password.
- Tools are read-only, with one exception added by ADR 0026: feedback drafts, files and
  publication, behind a separate `rms:feedback` grant. Other writes (marking a report reviewed,
  requesting a revision) remain a later decision and would need the same.
- Refresh tokens rotate. Presenting a refresh token that was already used revokes everything issued
  to that user and client.

## Consequences

- A new module `app.oauth` (tables `oauth_clients`, `oauth_codes`, `oauth_tokens`, migration 0031)
  sits directly above `app.identity` in the layer order; `app.mcp` sits above everything and calls
  services only, never models.
- Report and attachment text reaches Claude's context. It is written by students, so tool output
  labels it as quoted data. `ai_restricted` is not consulted: no project uses it (the column stays
  for the assessment step, ADR 0024) and the professor already holds the right to read the text.
- Every tool call is audited with the user and the tool name, in the workspace it read.
- Caddy forwards `/mcp`, `/oauth/*` and `/.well-known/oauth-*` to the API.
