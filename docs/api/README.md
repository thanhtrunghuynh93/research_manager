# API schema

`openapi.json` is exported by `scripts/gen_api_client.sh` from the running application and
committed so reviewers can see API changes in pull requests. CI regenerates it and fails on drift.

Breaking changes to `/api/v1` are listed here with the release that introduced them.

| Release | Change |
| --- | --- |
| use cases v0.4 | **Ten routes removed.** Seven were the in-app notification surface (UI-07 amended to delivery only): `GET /notifications`, `GET /notifications/unread-count`, `POST /notifications/read-all`, `POST /notifications/{notification_id}/read`, `GET /notifications/preferences`, `POST /notifications/preferences/mute`, `POST /notifications/preferences/unmute`. Three were exports (UI-06 withdrawn): `GET /exports`, `GET /exports/kinds`, `GET /exports/{kind}.csv`. `PUT /notifications/reminder-offsets` survives — it configures email delivery, which is the channel UI-07 keeps |
| use cases v0.5–v0.9 | **Nine routes added, none breaking.** Eight for workspaces — `GET`/`POST /workspaces`, `GET`/`PATCH /workspaces/{workspace_id}`, `POST /workspaces/{workspace_id}/join`, `/leave`, `/archive` — and `POST /users/{user_id}/workspace` to move a student. `InvitationIn` gained an optional `workspace_id`, and `GET /users` lost its `across_workspaces` parameter when reads began spanning membership by default (ADR 0016) |
| use cases v0.18 | **Eight routes removed, one parameter dropped** (requirements 0.10). Tasks: `GET`/`POST /projects/{project_id}/tasks`, `PATCH /tasks/{task_id}`. Decisions: `GET`/`POST /projects/{project_id}/decisions`. Reminders: `PUT /notifications/reminder-offsets`. Correction requests: `POST /assessments/{assessment_id}/corrections`, `GET /assessments/{assessment_id}/feedback`. `GET /periods` lost `across_workspaces` ([ADR 0021](../adr/0021-the-read-set-is-one-workspace.md)); a caller still sending it is ignored rather than refused |
| use cases v0.19 | **Eleven routes removed** with the repository connector (requirements 0.11, [ADR 0022](../adr/0022-no-repository-connector.md)): `GET`/`POST /repositories`, `GET`/`POST /repositories/{repository_id}/projects`, `GET`/`POST /repositories/{repository_id}/sync`, `GET`/`POST /developer-identities`, `POST /developer-identities/{identity_id}/confirm`, `GET /contributions`, `GET /admin/sync`; and the unlisted `POST /webhooks/github`. `GET /overview` lost `sync_issues`; assessment responses lost `integration_of_earlier_work` |
| use cases v0.20 | **Seven routes removed** with the research assistant (requirements 0.12, [ADR 0023](../adr/0023-no-research-assistant.md)): `POST /assistant/ask`, `POST /assistant/ask/stream`, `GET /assistant/conversations`, `GET /assistant/conversations/{conversation_id}/messages`, `GET /evidence/search`, `GET /evidence/references/{reference_id}`, `POST /supervision-notes`. `WorkspaceOut` lost `access_epoch` |
| use cases v0.21 | None (embeddings removed, requirements 0.13) |
