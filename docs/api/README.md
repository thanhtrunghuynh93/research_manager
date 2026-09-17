# API schema

`openapi.json` is exported by `scripts/gen_api_client.sh` from the running application and
committed so reviewers can see API changes in pull requests. CI regenerates it and fails on drift.

Breaking changes to `/api/v1` are listed here with the release that introduced them.

| Release | Change |
| --- | --- |
| use cases v0.4 | **Ten routes removed.** Seven were the in-app notification surface (UI-07 amended to delivery only): `GET /notifications`, `GET /notifications/unread-count`, `POST /notifications/read-all`, `POST /notifications/{notification_id}/read`, `GET /notifications/preferences`, `POST /notifications/preferences/mute`, `POST /notifications/preferences/unmute`. Three were exports (UI-06 withdrawn): `GET /exports`, `GET /exports/kinds`, `GET /exports/{kind}.csv`. `PUT /notifications/reminder-offsets` survives — it configures email delivery, which is the channel UI-07 keeps |
| use cases v0.5–v0.9 | **Nine routes added, none breaking.** Eight for workspaces — `GET`/`POST /workspaces`, `GET`/`PATCH /workspaces/{workspace_id}`, `POST /workspaces/{workspace_id}/join`, `/leave`, `/archive` — and `POST /users/{user_id}/workspace` to move a student. `InvitationIn` gained an optional `workspace_id`, and `GET /users` lost its `across_workspaces` parameter when reads began spanning membership by default (ADR 0016) |
