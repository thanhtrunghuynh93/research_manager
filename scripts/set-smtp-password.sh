#!/usr/bin/env bash
# Put the SMTP password into infra/.env without it appearing in a shell history, a log, or a
# terminal, and prove it works before the deploy depends on it.
#
# The verification matters more than the convenience. A wrong SMTP credential is the failure this
# system is least able to report: enrolment is invitation-only, so the relay is the only way in,
# and a rejected login surfaces as a job dying in the queue rather than as an error anyone sees.
# Checking it here means the deploy either has working mail or stops.
#
# Usage:  scripts/set-smtp-password.sh [path-to-env]     (default infra/.env)
set -uo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${1:-infra/.env}"
[ -f "$ENV_FILE" ] || { echo "no $ENV_FILE" >&2; exit 2; }

host=$(grep -E '^RM_SMTP_HOST=' "$ENV_FILE" | tail -1 | cut -d= -f2-)
port=$(grep -E '^RM_SMTP_PORT=' "$ENV_FILE" | tail -1 | cut -d= -f2-)
user=$(grep -E '^RM_SMTP_USER=' "$ENV_FILE" | tail -1 | cut -d= -f2-)

echo "Relay : $host:$port"
echo "User  : $user"
echo
echo "Paste the Google App Password (16 characters; spaces are ignored)."
echo "Create one at https://myaccount.google.com/apppasswords — it needs 2-Step Verification on."
printf 'Password (not shown): '
read -rs password
echo

# Google displays the app password in four groups of four. People paste it as displayed, and the
# spaces are not part of it — stripping them here avoids an authentication failure that looks
# like a wrong password.
password=$(printf '%s' "$password" | tr -d '[:space:]')

if [ -z "$password" ]; then
  echo "nothing entered; $ENV_FILE unchanged" >&2
  exit 1
fi
if [ ${#password} -ne 16 ]; then
  echo "warning: a Google App Password is 16 characters; got ${#password}." >&2
  printf 'Continue anyway? [y/N] '
  read -r reply
  case "$reply" in [yY]*) ;; *) echo "$ENV_FILE unchanged"; exit 1 ;; esac
fi

echo "Testing the login before writing it..."
if ! RM_TEST_PASSWORD="$password" RM_TEST_HOST="$host" RM_TEST_PORT="$port" \
     RM_TEST_USER="$user" python3 - <<'PY'
import os, smtplib, sys

try:
    with smtplib.SMTP(os.environ["RM_TEST_HOST"], int(os.environ["RM_TEST_PORT"]), timeout=15) as c:
        c.ehlo()
        c.starttls()
        c.ehlo()
        c.login(os.environ["RM_TEST_USER"], os.environ["RM_TEST_PASSWORD"])
except smtplib.SMTPAuthenticationError as error:
    print(f"  rejected: {error.smtp_code} {error.smtp_error.decode(errors='replace')}")
    print("  An app password is required; the ordinary account password is refused by Google.")
    sys.exit(1)
except Exception as error:  # noqa: BLE001 - any failure here means do not write the file
    print(f"  failed: {error}")
    sys.exit(1)
print("  accepted")
PY
then
  echo
  echo "$ENV_FILE unchanged — the password was not written." >&2
  exit 1
fi

tmp=$(mktemp)
chmod 600 "$tmp"
# Written with awk rather than sed -i so the password never becomes part of a command line, where
# it would be visible in `ps` to every user on the host for as long as the command runs.
RM_NEW_PASSWORD="$password" awk '
  /^RM_SMTP_PASSWORD=/ { print "RM_SMTP_PASSWORD=" ENVIRON["RM_NEW_PASSWORD"]; next }
  { print }
' "$ENV_FILE" > "$tmp" && cat "$tmp" > "$ENV_FILE" && rm -f "$tmp"
chmod 600 "$ENV_FILE"

echo
echo "Written to $ENV_FILE (mode 600)."
echo "Revoke it at https://myaccount.google.com/apppasswords if it is ever exposed."
