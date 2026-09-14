# Runbook — Production readiness

Audit of 14 September 2026, against the working tree at the time. Scope is the two flows a first
deployment cannot open without: **enrolling a professor and a student**, and **submitting a weekly
report**. Everything else — assessments, the assistant, repository sync, exports — is out of scope
here and may hold findings of its own.

Trigger: before a first production deploy, and again before any deploy that changes authentication,
mail, or object storage. Work through it alongside [deploy.md](deploy.md), which is the procedure;
this is what must already be true for that procedure to produce a working system.

An item is closed when it is either fixed or written down as an accepted risk with a name against
it. "We know about it" is not closed.

## 1 Blockers — enrolment will not work reliably

**1.1 A token email that fails to send is invisible.**
Invitation and recovery emails deliberately bypass `email_deliveries` (architecture §6.2): a token
message has no in-app counterpart, because the addressee has no session, and the queue row would
hold a live credential until the next sweep. The cost is that `failed_deliveries()` — what puts the
mail warning on the professor's overview (UI-01) — does not count them. With SMTP misconfigured the
job exhausts `RETRY_TRANSIENT` and dies in `procrastinate_jobs`, while the roll still reads
"Invitation sent to …". Nobody learns the student was never contacted.

Fix: count failed `notifications.send_token_email` jobs into the same overview warning, or give
token emails a delivery record of their own that carries no token.

**1.2 Readiness does not cover the worker or SMTP.**
`/api/readyz` checks the database and object storage and nothing else (`app/api/v1/health.py`).
Since the invitation email is a deferred job, a deploy with a dead worker or wrong SMTP credentials
answers `ready` and enrols nobody. Report submission degrades gracefully — a failed enqueue is
swallowed on purpose so the submission still lands — but enrolment has no such fallback, and it is
the one flow with no way in if it fails.

Fix: add a worker-liveness check (last job completion, or a heartbeat row) and an SMTP connect
check to `readyz`, or accept and add both to the post-deploy verification in deploy.md step 9.

**1.3 Mail deliverability is addressed nowhere.**
`RM_MAIL_FROM` ships as `research-management@example.edu`, and no runbook mentions SPF, DKIM, or
DMARC for the sending domain. An invitation in a spam folder is the same as no invitation, and
since enrolment is invitation-only (AUTH-01, ADR 0011) there is no other way in.

Fix: choose the mail provider (still open — implementation_status §5.1), publish SPF and DKIM for
the sending domain, and send one invitation to an external mailbox as part of the first deploy.

## 2 Must fix before go-live

**2.1 `RM_SECRET_KEY` is read by nothing. — CLOSED 14 September 2026 (trunght), fixed.**
The only match for `secret_key` outside `app/core/config.py` was `s3_secret_key`. Sessions,
invitations, and reset links are 32-byte `secrets.token_urlsafe` values stored as SHA-256 digests;
no signing key was involved anywhere in the system.

Three documents said otherwise: [.env.example](../../.env.example) ("Changing it invalidates every
session and every unused invitation and reset link"), [deploy.md](deploy.md) step 2 ("the same as
having no session protection at all"), and [rotate-secrets.md](rotate-secrets.md) row 1. Two more
the audit missed: [repo_layout.md](../repo_layout.md) §3.6 ("Session and token signing") and
[scripts/run.sh](../../scripts/run.sh), which refused to start real mode on the shipped default
with the same false explanation.

Resolution: **deleted, not wired up.** The opaque-token design is the stronger one — the row is the
authority, so revocation is immediate and single use is enforceable, neither of which a signed
token gives you without consulting the database anyway — and every secret with a real job already
has its own (webhook HMAC, S3, the App key). Wiring it would have meant inventing a use for a
variable. The unused `itsdangerous` dependency, the ghost of the intended design, went with it.

The gap the prose was hiding was not a missing key but **missing mass revocation**: the only
documented way to invalidate everything was a no-op, at a trigger that reads "a suspected leak, or
an operator leaving". `app.cli identity revoke-all-sessions` now does it for real, and is row 1 of
[rotate-secrets.md](rotate-secrets.md).

**2.2 No rate limiting on authentication.**
`POST /api/v1/auth/login`, `/auth/password-reset`, and `/auth/accept-invitation` have no limiter,
and Caddy adds none. The tokens themselves are unguessable at 32 bytes, so the exposure is
password brute-force against login and reset-request flooding of a known mailbox.

Fix: a limiter at the edge on those three paths is the cheapest form and needs no application
change.

**2.3 Nothing refuses to start on a development configuration.**
`Settings` carries no production validation. The application boots with `RM_ENV=prod` and every
shipped default in place; only `/api/metrics` self-disables. deploy.md step 2 lists the variables
that must be non-empty, which makes correctness depend on an operator reading a checklist.

Fix: a `model_validator` that refuses to start when `env == "prod"` and any of the known dev
defaults survive. That turns three manual steps into an assertion, and is the single change that
most reduces the chance of a quiet misconfiguration.

**2.4 `RM_ACME_EMAIL` is missing from `.env.example`.**
[infra/caddy/Caddyfile](../../infra/caddy/Caddyfile) reads it; `.env.example` does not list it.
deploy.md step 2 compares the *keys* in `infra/.env` against `.env.example`, so that check
structurally cannot catch this one, and Let's Encrypt registration falls back to
`admin@example.edu` — certificate expiry and problem notices go to a stranger.

Fix: add it to `.env.example` with the other hosting variables.

## 3 Report submission — open items

The path itself is ready. The `objects.<domain>` record, its certificate, `RM_S3_PUBLIC_ENDPOINT`,
and the CSP `connect-src` entry are all in place and already appear as deploy.md steps 0 and 8; the
bucket is created at API start-up and checked by `readyz`; the per-file cap is enforced before a
presigned URL is issued; and a submission survives a dead worker by design.

Two decisions remain:

- **No malware or content scanning on uploads.** A student uploads an arbitrary file and a
  professor later downloads it. `default-src 'none'; sandbox` on the objects subdomain stops the
  browser treating one as a page, which mitigates but does not remove the risk. Accept it in
  writing, or add a scan between `confirm` and extraction.
- **MinIO is single-node and unreplicated.** The nightly job mirrors the bucket
  ([infra/backup/backup.sh](../../infra/backup/backup.sh)), so the worst-case recovery point for
  attachments is 24 hours — a week's evidence, in the product's own terms. Confirm that is the
  intended target, or shorten the schedule.

## 4 Verified clean

Checked during this audit, and passing:

| Check | Result |
| --- | --- |
| Migrations from an empty database | all 16 apply; `alembic check` reports no drift |
| Frontend production build | succeeds; 401 kB JS, 123 kB gzipped |
| Backup coverage | Postgres dump **and** object bucket mirror |
| Release images | backend and Caddy, both with SBOM and provenance |
| Session cookie | `Secure` whenever `RM_ENV=prod` |
| Object store exposure | S3 API only; `/minio/*` returns 404 at the edge |

## 5 Decisions still owed

From [implementation_status.md](../implementation_status.md) §5, the ones that touch these flows:

1. **Mail provider** — SMTP relay or transactional API. Blocks 1.3.
2. **Monthly AI budget** — none configured means no limit, not a limit of zero.
3. **VPS region and offsite backup destination** — `RM_OFFSITE_REMOTE` empty means backups die with
   the host that made them.

## 6 Order of work

Roughly a day and a half, and the order matters less than the grouping:

1. §1 (1.1–1.3) — without these, enrolment fails silently. A day.
2. §2 (2.1–2.4) — the difference between a pilot and a deployment. Half a day.
3. §3 — configuration already described in deploy.md, plus two decisions to write down.

Re-run this audit after each group, and record the date and operator at the top of this file.
