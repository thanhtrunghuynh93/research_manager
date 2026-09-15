#!/usr/bin/env bash
# Pre-deploy checks against a filled-in infra/.env and the host it will run on.
#
# docs/runbooks/deploy.md step 2 asks an operator to compare the *keys* in infra/.env against
# .env.example by eye. That check cannot see three of the things that actually break a deploy:
#
#   - a key present with an empty value (RM_METRICS_TOKEN, RM_GITHUB_WEBHOOK_SECRET)
#   - a variable read by the Caddyfile but never passed into the caddy container (RM_ACME_EMAIL)
#   - a bind-mounted file that does not exist, which Docker silently creates as a *directory*
#     (infra/backup/age-recipients.txt, infra/backup/rclone.conf, infra/secrets/github-app.pem) —
#     the backup container then fails on its first nightly run and nothing says so
#
# The application refuses to start on development defaults in prod (app/core/config.py), so this
# covers what runs outside the application: compose, Caddy and the backup container.
#
# Usage:  scripts/preflight.sh [path-to-env]     (default infra/.env)
set -uo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${1:-infra/.env}"
problems=0
warnings=0

fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; problems=$((problems + 1)); }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$1"; warnings=$((warnings + 1)); }
pass() { printf '  \033[32mok\033[0m    %s\n' "$1"; }

if [ ! -f "$ENV_FILE" ]; then
  echo "no $ENV_FILE — copy .env.example to it and fill it in" >&2
  exit 2
fi

value() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2-; }

echo "Preflight against $ENV_FILE"
echo
echo "Configuration keys"

missing=$(comm -23 \
  <(grep -oE '^[A-Z_]+' .env.example | sort -u) \
  <(grep -oE '^[A-Z_]+' "$ENV_FILE" | sort -u))
if [ -n "$missing" ]; then
  fail "keys in .env.example but not in $ENV_FILE: $(echo "$missing" | tr '\n' ' ')"
else
  pass "every key in .env.example is present"
fi

echo
echo "Values that must not be empty"

# Empty here fails silently and differently in each case, which is why each gets its own line.
for required in RM_DOMAIN RM_PUBLIC_URL RM_METRICS_TOKEN RM_S3_PUBLIC_ENDPOINT RM_SMTP_HOST RM_MAIL_FROM; do
  if [ -z "$(value "$required")" ]; then
    fail "$required is empty"
  else
    pass "$required is set"
  fi
done

if [ -z "$(value RM_ACME_EMAIL)" ]; then
  # Let's Encrypt registration falls back to the Caddyfile's own default, and certificate expiry
  # and problem notices go to a stranger.
  fail "RM_ACME_EMAIL is empty; certificate notices would go to the Caddyfile's fallback address"
else
  pass "RM_ACME_EMAIL is set"
fi

if [ -n "$(value RM_GITHUB_APP_ID)" ] && [ -z "$(value RM_GITHUB_WEBHOOK_SECRET)" ]; then
  fail "RM_GITHUB_APP_ID is set without RM_GITHUB_WEBHOOK_SECRET; the webhook returns 503"
fi

if [ -z "$(value RM_OFFSITE_REMOTE)" ]; then
  warn "RM_OFFSITE_REMOTE is empty: backups stay on this host and die with its disk"
fi

if [ -z "$(value RM_OPENAI_API_KEY)" ]; then
  warn "RM_OPENAI_API_KEY is empty: assessments run on the deterministic fake gateway"
fi

echo
echo "Consistency between values"

domain=$(value RM_DOMAIN)
case "$(value RM_PUBLIC_URL)" in
  "https://$domain") pass "RM_PUBLIC_URL matches RM_DOMAIN over https" ;;
  *) fail "RM_PUBLIC_URL should be https://$domain to match RM_DOMAIN" ;;
esac

case "$(value RM_S3_PUBLIC_ENDPOINT)" in
  "https://objects.$domain") pass "RM_S3_PUBLIC_ENDPOINT matches the objects subdomain" ;;
  *) fail "RM_S3_PUBLIC_ENDPOINT should be https://objects.$domain; a presigned URL is signed over the host, so a mismatch fails at the moment the browser uploads" ;;
esac

echo
echo "Files that Docker would otherwise create as directories"

for mount in infra/backup/age-recipients.txt infra/backup/rclone.conf infra/secrets/github-app.pem; do
  if [ -d "$mount" ]; then
    fail "$mount is a DIRECTORY — Docker created it from a missing bind mount; remove it and create the file"
  elif [ ! -f "$mount" ]; then
    fail "$mount does not exist; compose would create it as a directory"
  else
    pass "$mount exists as a file"
  fi
done

if [ -f infra/backup/age-recipients.txt ] && ! grep -q '^age1' infra/backup/age-recipients.txt; then
  fail "infra/backup/age-recipients.txt holds no age1... public key; every backup would fail to encrypt"
fi

echo
echo "DNS"

for name in "$domain" "objects.$domain"; do
  resolved=$(getent hosts "$name" | awk '{print $1}' | head -1)
  if [ -z "$resolved" ]; then
    fail "$name does not resolve; Caddy cannot obtain a certificate for it"
  else
    pass "$name resolves to $resolved"
  fi
done

echo
echo "Host"

if [ -z "$(swapon --show --noheadings 2>/dev/null)" ]; then
  warn "no swap configured; this host has little headroom for the assessment pipeline"
else
  pass "swap is configured"
fi

if [ "$(stat -c '%a' "$ENV_FILE")" != "600" ]; then
  warn "$ENV_FILE is mode $(stat -c '%a' "$ENV_FILE"); it holds every credential and should be 600"
else
  pass "$ENV_FILE is mode 600"
fi

echo
if [ "$problems" -gt 0 ]; then
  echo "$problems blocking problem(s), $warnings warning(s) — do not deploy yet"
  exit 1
fi
echo "no blocking problems, $warnings warning(s)"
