# Host secrets

Nothing in this directory is mounted any more. It held `github-app.pem`, the GitHub App key for the
repository connector, which was removed (ADR 0022); a copy left on a host can be deleted once the
release without the mount is deployed. The directory stays gitignored, and `gitleaks` runs on
every commit and in CI, so a secret dropped here by habit is still not committed.

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
The two files `preflight.sh` checks are both bind mounts, and Docker creates a missing bind source
as a *directory* — which is why "the file does not exist" and "the file is a directory" are
separate checks there.
