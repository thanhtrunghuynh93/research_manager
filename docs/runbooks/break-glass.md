# Runbook — Professor account lifecycle (break-glass)

Trigger: a professor cannot log in and the normal emailed reset cannot reach them, the professor
account must be transferred, or a professor must be demoted or deactivated (AUTH-01).

Professors are co-equal over students and have no authority over each other (ADR 0011), so
demoting, deactivating, or removing a professor is not reachable from the API — it lives here.
Every command below refuses to leave the workspace with no active professor; use
`transfer-professor` when there is only one.

Preconditions: shell access to the VPS and the `infra/.env` file. The procedure is not reachable
through the API by design.

1. Confirm identity out of band (a phone call to a known number, or in person).
2. On the VPS:
   ```bash
   docker compose --env-file infra/.env -f infra/docker-compose.yml exec api \
     python -m app.cli breakglass recover-professor --email <current-professor-email>
   ```
   The command prints a single-use reset link valid for 15 minutes and writes an `audit_events`
   row with `actor_kind = system`. It also restores the account's `prof` role and `active` state,
   since the lock-out may be a mistaken demotion or deactivation. The same link is emailed to the
   address on record, so hand over the printed one only when the mailbox is the thing that is
   unreachable.
3. For a transfer, run `breakglass transfer-professor --from <old> --to <new>` instead; the old
   account is deactivated in the same transaction and the workspace's break-glass contact
   (`workspaces.owner_id`) moves with it.
4. To remove one of several professors — a co-supervisor whose involvement has ended — run
   `breakglass demote-professor --email <address>` to return them to the student role, or
   `breakglass deactivate-professor --email <address>` to close the account and revoke every
   session. Both refuse if the named account is the only active professor left, and neither
   prints a link: there is no credential to hand over.
5. Hand the link over through a different channel from the one used to request it.
6. Record who requested, who verified, and when, in the operations log.
