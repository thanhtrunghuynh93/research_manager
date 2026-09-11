# Runbook — Professor account recovery (break-glass)

Trigger: the professor cannot log in and the normal emailed reset cannot reach them, or the
professor account must be transferred (AUTH-01).

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
   since the lock-out may be a mistaken demotion or deactivation. The notification to the address
   on record is sent once the notifications module is deployed; until then the audit row and this
   log entry are the record of the action.
3. For a transfer, run `breakglass transfer-professor --from <old> --to <new>` instead; the old
   account is deactivated in the same transaction.
4. Hand the link over through a different channel from the one used to request it.
5. Record who requested, who verified, and when, in the operations log.
