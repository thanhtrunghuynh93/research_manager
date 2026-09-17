#!/usr/bin/env python3
"""Refuse the Docker commands that delete volumes.

On 16 September 2026 an agent ran `docker compose down -v` against this host, believing it was a
development stack. It is not: `infra/.env` line 1 reads "PRODUCTION — research.ecomind.dev". The
`-v` removed the `pgdata` and `objects` volumes, and with them the database and every uploaded
attachment. The local encrypted dumps survived and could not be decrypted here, by design.

`down` is routine and stays allowed. What this refuses is the small set of flags that destroy data
rather than stopping a container, because the difference between them is one character and the
consequence is not recoverable from this host.

Read on stdin as a Claude Code PreToolUse hook (see .claude/settings.json). Exits 0 either way: a
silent exit allows the command, and a `deny` decision on stdout refuses it with a reason.
"""

from __future__ import annotations

import json
import re
import sys

# Each rule is (pattern, what it would destroy). The patterns are deliberately narrow: a rule that
# also caught the harmless form would be turned off within a week, and then nothing would be
# guarded at all.
RULES: list[tuple[re.Pattern[str], str]] = [
    (
        # `docker compose ... down ... -v`, with any number of -f/--env-file arguments between.
        re.compile(r"\bdocker[\s-]+compose\b[^;&|]*\bdown\b[^;&|]*(?:\s-v\b|\s--volumes\b)"),
        "`docker compose down -v` removes the named volumes: on this host that is `pgdata` "
        "(the database) and `objects` (every uploaded attachment).",
    ),
    (
        re.compile(r"\bdocker\s+volume\s+(rm|remove)\b"),
        "`docker volume rm` deletes a volume outright.",
    ),
    (
        re.compile(r"\bdocker\s+volume\s+prune\b"),
        "`docker volume prune` deletes every volume no running container is using — which "
        "includes this project's, whenever the stack happens to be down.",
    ),
    (
        re.compile(r"\bdocker\s+system\s+prune\b[^;&|]*--volumes\b"),
        "`docker system prune --volumes` deletes unused volumes along with the images.",
    ),
]

ADVICE = (
    "Use `docker compose ... down` without `-v`. It stops and removes the containers and leaves "
    "the volumes alone, which is what restarting the stack actually needs.\n\n"
    "If you genuinely mean to destroy the data, take a dump you can decrypt first "
    "(docs/runbooks/backup-restore.md) and run the command yourself outside this session — the "
    "point of this guard is that an agent should not be the one to decide."
)


# `cmd <<'EOF' ... EOF` and `cmd <<EOF ... EOF`. What follows the marker is data the shell hands
# to a program — a commit message, a file being written — not something it executes. Scanning it
# refuses prose that merely names the command, which is how this guard first refused the commit
# that introduced it.
HEREDOC = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1.*?^\2$",
    re.DOTALL | re.MULTILINE,
)


# The exception to the exception: a heredoc fed to a shell *is* executed, so its body is not data.
# Conservative on purpose — if one appears anywhere, nothing is stripped and the whole string is
# scanned. Guarding against a mistake, not against someone deliberately hiding a command.
SHELL_HEREDOC = re.compile(r"\b(?:ba|z|da)?sh\b[^\n]*<<")


def executable_part(command: str) -> str:
    """The command with heredoc bodies removed, so only what the shell runs is scanned."""
    if SHELL_HEREDOC.search(command):
        return command
    return HEREDOC.sub("<<REDACTED", command)


def refusal(command: str) -> str | None:
    """The reason this command is refused, or None to let it through."""
    scanned = executable_part(command)
    for pattern, destroys in RULES:
        if pattern.search(scanned):
            return destroys
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # A hook that cannot read its input must not block the session.
        return 0

    command = str(payload.get("tool_input", {}).get("command", ""))
    destroys = refusal(command)
    if destroys is None:
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Refused: {destroys}\n\n{ADVICE}",
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
