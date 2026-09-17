#!/usr/bin/env python3
"""Cases for scripts/guard_docker_volumes.py. Run it: `python3 scripts/test_guard_docker_volumes.py`.

The destructive commands are assembled from a variable rather than written out, because the guard
reads the command it is given and would refuse the run that tests it — which is how the heredoc
exception below was found in the first place.

Two properties matter as much as the refusals. Plain `down` must stay allowed, or the guard gets
switched off; and a command that merely *names* one of these — a commit message, a file being
written — is data, not an instruction, unless the heredoc is being fed to a shell.
"""
import json, subprocess, sys

D = "docker"
CASES_DENY = [
    (f"{D} compose -f a.yml --env-file .env down -v", "compose down -v"),
    (f"{D} compose -f a.yml -f b.yml down -v --remove-orphans", "down -v --remove-orphans"),
    (f"{D} compose down --volumes", "down --volumes"),
    (f"{D}-compose down -v", "docker-compose down -v"),
    (f"{D} volume rm research-management_pgdata", "volume rm"),
    (f"{D} volume prune -f", "volume prune"),
    (f"{D} system prune -a --volumes", "system prune --volumes"),
    (f"cd /x && {D} compose down --volumes", "chained with &&"),
    (f"cat > x <<'EOF'\nhello\nEOF\n{D} volume prune -f", "real command after a heredoc"),
    (f"bash <<'EOF'\n{D} volume prune -f\nEOF", "heredoc piped into a shell"),
    (f"sh <<'EOF'\n{D} compose down -v\nEOF", "heredoc piped into sh"),
]
CASES_ALLOW = [
    (f"{D} compose -f infra/docker-compose.yml --env-file infra/.env down", "plain down"),
    (f"{D} compose down --remove-orphans", "down --remove-orphans"),
    (f"{D} compose up -d", "up -d"),
    (f"{D} volume ls", "volume ls"),
    (f"{D} system prune -a", "system prune without --volumes"),
    (f"{D} compose exec -T api alembic upgrade head", "exec"),
    (f"git commit -F - <<'MSG'\nnever run {D} compose down -v again\n{D} volume rm is refused too\nMSG", "commit message naming the commands"),
    (f"cat > note.md <<'EOF'\nuse {D} compose down -v to wipe\nEOF", "heredoc writing a file"),
]

def denied(cmd):
    out = subprocess.run(
        [sys.executable, "scripts/guard_docker_volumes.py"],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
        capture_output=True, text=True,
    ).stdout
    return '"deny"' in out

bad = 0
for cmd, label in CASES_DENY:
    ok = denied(cmd)
    bad += not ok
    print(f"  {'DENIED ' if ok else 'MISSED!'}  {label}")
print()
for cmd, label in CASES_ALLOW:
    ok = not denied(cmd)
    bad += not ok
    print(f"  {'allowed' if ok else 'FALSE+!'}  {label}")
print(f"\n{len(CASES_DENY)} deny + {len(CASES_ALLOW)} allow; {bad} wrong")
sys.exit(1 if bad else 0)
