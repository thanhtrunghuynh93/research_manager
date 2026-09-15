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

## The backup key lives next door, and is the one that fails quietly

[`../backup/age-recipients.txt`](../backup/) holds the age *public* keys every nightly backup is
encrypted to, and is gitignored for a reason worth stating: a recipients file inherited from
another deployment encrypts backups to a key whose private half nobody here has. Those backups run,
report success, and cannot be restored — a failure discovered only during a recovery, which is the
worst moment to discover it. Copy `age-recipients.txt.example`, generate the pair off this host,
and keep the private key somewhere a compromise of this host would not reach:

```bash
age-keygen -o rm-backup-identity.key     # NOT on the VPS
```

`scripts/preflight.sh` fails when the file is missing, is a directory, or holds no `age1…` key.
The three files under this heading are all bind mounts, and Docker creates a missing bind source
as a *directory* — which is why "the file does not exist" and "the file is a directory" are
separate checks there.
