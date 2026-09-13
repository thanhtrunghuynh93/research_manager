# Host secrets

Mounted read-only into the api and worker containers. Nothing in this directory is committed:
`.gitignore` covers it, and `gitleaks` runs on every commit and in CI.

| File | What it is | Without it |
| --- | --- | --- |
| `github-app.pem` | The GitHub App's private key, downloaded once when the App was created | The connector falls back to the in-memory one, and a connected repository reports no activity — which looks exactly like a student who did nothing (REPO-01, AC-04) |

The path inside the container is fixed at `/run/secrets/github-app.pem` and is what
`RM_GITHUB_APP_PRIVATE_KEY_PATH` points at. `RM_GITHUB_APP_PRIVATE_KEY_HOST_PATH` says where it
comes from on this host, so the key can live outside the repository entirely.

Compose needs the path to exist even when no App is configured, so create an empty placeholder:

```bash
touch infra/secrets/github-app.pem
```

An empty file is not a key: the factory checks that it can read one and logs the fallback.
