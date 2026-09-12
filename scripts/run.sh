#!/usr/bin/env bash
# Run the stack against real integrations, or against the fakes.
#
#   scripts/run.sh                 real mode: real model provider, real GitHub App, real mail
#   scripts/run_mock.sh            mock mode: deterministic gateway, in-memory connector, mailpit
#
# The two modes are separate compose projects, so their databases and object stores never mix: a
# demo dataset seeded in mock mode cannot end up beside real student work. They publish the same
# ports, so only one runs at a time and this refuses to start the second.
#
# Each mode reads its own env file — infra/.env.real and infra/.env.mock — which is copied into
# infra/.env because that is what the compose services declare as `env_file`.
#
# Most of this script is refusing to start rather than starting. That is deliberate: every
# integration here falls back to a working fake when its credentials are absent, so a
# misconfigured real run does not fail, it quietly produces fake output. The check for the
# credential is the only thing standing between "assessments cost money and mean something" and
# "assessments are heuristics with a plausible shape".
set -euo pipefail
cd "$(dirname "$0")/.."

MODE=real
START_WEB=1
DO_SEED=0
DO_DOWN=0
HOST_ADDR=""
BOOTSTRAP_ARGS=()

usage() {
  cat <<'USAGE'
Usage: scripts/run.sh [--mode real|mock] [options]

  --mode real|mock   which integrations to use (default: real)
  --seed             load the demo dataset (mock mode only; it publishes a password)
  --bootstrap "Lab" prof@example.edu "Prof Name"
                     create the workspace and its professor, then print the invitation link
  --host ADDR        the address you will reach this stack from, when that is not this
                     machine — a LAN or Tailscale IP. Points RM_PUBLIC_URL and
                     RM_S3_ENDPOINT at it, so invitation links open and attachment
                     uploads resolve from the other machine rather than from localhost.
  --no-web           start the backend stack only, without the frontend dev server
  --down             stop this mode's stack and exit
  -h, --help         this
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="${2:-}"; shift 2 ;;
    --seed) DO_SEED=1; shift ;;
    --bootstrap) BOOTSTRAP_ARGS=("${2:-}" "${3:-}" "${4:-}"); shift 4 ;;
    --host) HOST_ADDR="${2:-}"; shift 2 ;;
    --no-web) START_WEB=0; shift ;;
    --down) DO_DOWN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$MODE" in
  real) PROJECT=research-management;      ENV_SOURCE=infra/.env.real ;;
  mock) PROJECT=research-management-mock; ENV_SOURCE=infra/.env.mock ;;
  *) echo "--mode must be real or mock, not '$MODE'" >&2; exit 2 ;;
esac

# Checked here rather than where the seed runs, so an impossible request costs nothing: the
# alternative brought the whole stack up and refused afterwards.
if [[ "$DO_SEED" == 1 && "$MODE" != mock ]]; then
  echo "--seed is mock-mode only: the demo dataset creates a professor with a password" >&2
  echo "published in the repository. Use scripts/run_mock.sh --seed." >&2
  exit 2
fi

COMPOSE=(docker compose -p "$PROJECT" -f infra/docker-compose.yml -f infra/docker-compose.dev.yml)
OTHER_PROJECT=$([[ "$MODE" == real ]] && echo research-management-mock || echo research-management)

APP_HOST="${HOST_ADDR:-localhost}"
APP_URL="http://$APP_HOST:8020"
# Always loopback: this is what the script itself polls, from this machine.
API_URL=http://localhost:8021

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33mwarn\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- stop and leave

if [[ "$DO_DOWN" == 1 ]]; then
  cp -f "$ENV_SOURCE" infra/.env 2>/dev/null || cp -f .env.example infra/.env
  "${COMPOSE[@]}" down
  exit 0
fi

# ---------------------------------------------------------------- the env file

if [[ ! -f "$ENV_SOURCE" ]]; then
  cp .env.example "$ENV_SOURCE"
  if [[ "$MODE" == real ]]; then
    die "Created $ENV_SOURCE from .env.example. It holds development defaults, so real mode will
not start until you fill in:

  RM_SECRET_KEY            python -c 'import secrets; print(secrets.token_urlsafe(48))'
  RM_OPENAI_API_KEY        without it, assessments run on the deterministic fake
  RM_SMTP_*                without a real provider, nobody is told they are late
  RM_PUBLIC_URL            the origin invitation links are built from

  Optional, but all-or-nothing if you want repository evidence:
  RM_GITHUB_APP_ID, RM_GITHUB_APP_PRIVATE_KEY_HOST_PATH, RM_GITHUB_WEBHOOK_SECRET

Then run this again."
  fi
  ok "created $ENV_SOURCE from .env.example"
fi

# Read it without sourcing: a value containing a space or a $ must not be executed.
setting() { grep -E "^$1=" "$ENV_SOURCE" | tail -1 | cut -d= -f2- || true; }

# ---------------------------------------------------------------- refuse to start wrong

say "Checking $MODE-mode configuration ($ENV_SOURCE)"

OPENAI_KEY=$(setting RM_OPENAI_API_KEY)
GITHUB_APP=$(setting RM_GITHUB_APP_ID)
WEBHOOK_SECRET=$(setting RM_GITHUB_WEBHOOK_SECRET)
SECRET_KEY=$(setting RM_SECRET_KEY)
SMTP_HOST=$(setting RM_SMTP_HOST)
PUBLIC_URL=$(setting RM_PUBLIC_URL)
KEY_PATH=$(setting RM_GITHUB_APP_PRIVATE_KEY_HOST_PATH)

if [[ "$MODE" == real ]]; then
  [[ -n "$SECRET_KEY" && "$SECRET_KEY" != "dev-only-change-me" ]] \
    || die "RM_SECRET_KEY is still the shipped default. Every session and invitation link is
signed with it, so leaving it is the same as having no protection at all.
  python -c 'import secrets; print(secrets.token_urlsafe(48))'"

  [[ -n "$OPENAI_KEY" ]] \
    || die "RM_OPENAI_API_KEY is empty, so this would run on the deterministic fake gateway and
produce assessments that look real and are not. That is a valid way to pilot the workflow —
scripts/run_mock.sh — but it should be a decision rather than a surprise."
  ok "model provider: key present"

  if [[ -n "$GITHUB_APP" ]]; then
    [[ -n "$WEBHOOK_SECRET" ]] \
      || die "RM_GITHUB_APP_ID is set but RM_GITHUB_WEBHOOK_SECRET is empty. The webhook endpoint
refuses every delivery in that state rather than verifying against an empty key, so pushes
would never trigger a sync. It must match the secret entered in the GitHub App itself."
    [[ -s "infra/${KEY_PATH#./}" ]] \
      || die "RM_GITHUB_APP_ID is set but the private key at infra/${KEY_PATH#./} is missing or
empty. Without a readable key the connector falls back to the in-memory one, and a connected
repository then reports no activity at all — which reads as a student who did nothing."
    ok "GitHub App: id, webhook secret and private key all present"
  else
    warn "no GitHub App configured; repository evidence will come from the in-memory connector"
  fi

  [[ "$SMTP_HOST" != "mailpit" ]] \
    || warn "RM_SMTP_HOST is still mailpit, so the missed-deadline email goes to a local inbox"
  [[ "$PUBLIC_URL" != *localhost* ]] \
    || warn "RM_PUBLIC_URL points at localhost; invitation links will only open on this machine"
else
  [[ -z "$OPENAI_KEY" ]] \
    || die "RM_OPENAI_API_KEY is set in $ENV_SOURCE. Mock mode must not reach a paid provider —
clear it, or use scripts/run.sh if you meant to run for real."
  [[ -z "$GITHUB_APP" ]] \
    || die "RM_GITHUB_APP_ID is set in $ENV_SOURCE. Mock mode must not reach a real GitHub App —
clear it, or use scripts/run.sh if you meant to run for real."
  ok "no real credentials present: deterministic gateway and in-memory connector"
fi

# ---------------------------------------------------------------- one mode at a time

if docker compose -p "$OTHER_PROJECT" -f infra/docker-compose.yml -f infra/docker-compose.dev.yml \
     ps --quiet 2>/dev/null | grep -q .; then
  die "The other mode ($OTHER_PROJECT) is running and holds the same ports.
Stop it first:  scripts/run.sh --mode $([[ $MODE == real ]] && echo mock || echo real) --down"
fi

cp -f "$ENV_SOURCE" infra/.env

if [[ -n "$HOST_ADDR" ]]; then
  # Both of these end up in a browser. RM_PUBLIC_URL is what invitation and recovery links are
  # built from; RM_S3_ENDPOINT is what presigned upload URLs point at, and its default names the
  # compose network's `minio`, which no browser can resolve. The api container reaches the host
  # by this address too, so one value serves both sides.
  sed -i "s|^RM_PUBLIC_URL=.*|RM_PUBLIC_URL=http://$HOST_ADDR:8020|" infra/.env
  sed -i "s|^RM_S3_ENDPOINT=.*|RM_S3_ENDPOINT=http://$HOST_ADDR:9000|" infra/.env
  ok "links and uploads will point at $HOST_ADDR"
fi

# ---------------------------------------------------------------- up, wait, migrate

say "Starting the $MODE stack"
"${COMPOSE[@]}" up -d --build

printf '  waiting for the api '
for _ in $(seq 1 90); do
  if curl -fsS "$API_URL/api/healthz" >/dev/null 2>&1; then break; fi
  printf '.'; sleep 2
done
printf '\n'
curl -fsS "$API_URL/api/healthz" >/dev/null 2>&1 \
  || { "${COMPOSE[@]}" logs --tail=50 api; die "the api did not become healthy"; }
ok "api healthy on $API_URL"

"${COMPOSE[@]}" exec -T api uv run alembic upgrade head >/dev/null
ok "migrations applied"

# ---------------------------------------------------------------- what actually got installed
#
# Read from the api's own start-up log rather than from the env file: what matters is which
# gateway the process installed, not which one we intended it to.

say "What this process actually installed"
if "${COMPOSE[@]}" logs api 2>/dev/null | grep -q "model provider installed"; then
  ok "$("${COMPOSE[@]}" logs api 2>/dev/null | grep -o 'model provider installed.*' | tail -1)"
elif "${COMPOSE[@]}" logs api 2>/dev/null | grep -q "deterministic fake gateway"; then
  [[ "$MODE" == mock ]] && ok "deterministic fake gateway and local embedder (as intended)" \
                        || die "the api installed the FAKE gateway despite real mode; check RM_OPENAI_API_KEY"
else
  warn "could not tell from the api log which gateway was installed"
fi

# ---------------------------------------------------------------- optional data

if [[ ${#BOOTSTRAP_ARGS[@]} -eq 3 ]]; then
  say "Creating the workspace and its professor"
  "${COMPOSE[@]}" exec -T api uv run python -m app.cli identity bootstrap \
    --name "${BOOTSTRAP_ARGS[0]}" --email "${BOOTSTRAP_ARGS[1]}" \
    --display-name "${BOOTSTRAP_ARGS[2]}"
fi

if [[ "$DO_SEED" == 1 ]]; then
  say "Loading the demo dataset"
  "${COMPOSE[@]}" exec -T api uv run python -m app.cli seed demo
fi

# ---------------------------------------------------------------- where things are

say "Ready — $MODE mode"
cat <<EOF
  app            $APP_URL
  api docs       http://$APP_HOST:8021/api/docs
  postgres       $APP_HOST:8022
  mailpit        http://$APP_HOST:8025
  minio console  http://$APP_HOST:8026

  first account  scripts/run.sh --mode $MODE --bootstrap "Your Lab" you@example.edu "Your Name"
  queue health   ${COMPOSE[*]} exec postgres psql -U rm -d rm \\
                   -c "SELECT status, task_name, count(*) FROM procrastinate_jobs GROUP BY 1,2"
  stop           scripts/run.sh --mode $MODE --down
EOF

if [[ "$START_WEB" == 1 ]]; then
  [[ -d frontend/node_modules ]] || (say "Installing frontend dependencies"; cd frontend && npm ci)
  say "Starting the frontend on $APP_URL (Ctrl-C stops it; the stack keeps running)"
  cd frontend && exec npm run dev
fi
