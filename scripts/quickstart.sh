#!/usr/bin/env bash
# quickstart.sh — run AI Development Hub locally with Docker in one command.
#
#   ./scripts/quickstart.sh --demo     # hub + a demo worker with built-in mock engines (no subscriptions needed)
#   ./scripts/quickstart.sh            # hub only; connect your own worker (docs/workers.md)
#   ./scripts/quickstart.sh --down     # stop it (data volumes are kept)
#   ./scripts/quickstart.sh --reset    # stop it and DELETE its data volumes and .aihub/ (start over)
#
# Everything local lives in .aihub/ (secrets, the admin password, settings). Nothing is exposed beyond
# 127.0.0.1 unless you change CONTROL_PLANE_PORT/HOST yourself.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
STATE=${AIHUB_STATE_DIR:-$ROOT/.aihub}
PROJECT=${AIHUB_COMPOSE_PROJECT:-aihub-quickstart}
PORT=${CONTROL_PLANE_PORT:-58080}
DEMO=0
case "${1:-}" in
  --demo) DEMO=1 ;;
  --down)
    docker compose -p "$PROJECT" --env-file infra/.env.example --env-file "$STATE/quickstart.env" \
      -f infra/docker-compose.yml -f infra/docker-compose.quickstart.yml --profile demo down
    exit 0 ;;
  --reset)
    # Compose needs the paths only to parse the files; the state may already be gone.
    AIHUB_SECRETS_HOST_DIR=${AIHUB_SECRETS_HOST_DIR:-$STATE/secrets} AIHUB_VAULT_HOST_DIR=${AIHUB_VAULT_HOST_DIR:-$ROOT/examples/demo-vault}       docker compose -p "$PROJECT" --env-file infra/.env.example       -f infra/docker-compose.yml -f infra/docker-compose.quickstart.yml --profile demo down -v
    rm -rf "$STATE"
    echo "Removed the $PROJECT containers, its data volumes and $STATE."
    exit 0 ;;
  "") ;;
  *) echo "usage: $0 [--demo|--down|--reset]" >&2; exit 2 ;;
esac

command -v docker >/dev/null || { echo "Docker is required: https://docs.docker.com/get-docker/" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required" >&2; exit 1; }

mkdir -p "$STATE"
chmod 700 "$STATE"
# The database volume keeps the password it was created with: new secrets cannot open old data.
if [ ! -s "$STATE/secrets/postgres_password" ] && docker volume inspect "${PROJECT}_postgres_data" >/dev/null 2>&1; then
  echo "Data from an earlier run exists (volume ${PROJECT}_postgres_data), but its secrets in $STATE are gone." >&2
  echo "Restore $STATE, or start over with: $0 --reset  (deletes that data)" >&2
  exit 1
fi
sh infra/scripts/init-secrets.sh "$STATE/secrets"
# Containers run as uid 1000 and Compose bind-mounts secret files with host ownership: make the files
# readable inside the containers. The directory stays 0700, so other host users still cannot reach them.
chmod 700 "$STATE/secrets"; chmod 644 "$STATE/secrets"/*
if [ ! -s "$STATE/admin-password" ]; then
  (umask 077; openssl rand -base64 18 | tr -d '/+=\n' > "$STATE/admin-password")
fi
VAULT=${AIHUB_VAULT_HOST_DIR:-$ROOT/examples/demo-vault}
cat > "$STATE/quickstart.env" <<EOF
AIHUB_SECRETS_HOST_DIR=$STATE/secrets
AIHUB_VAULT_HOST_DIR=$VAULT
CONTROL_PLANE_PORT=$PORT
AIHUB_DEMO=$DEMO
EOF

C=(docker compose -p "$PROJECT" --env-file infra/.env.example --env-file "$STATE/quickstart.env"
   -f infra/docker-compose.yml -f infra/docker-compose.quickstart.yml)
[ "$DEMO" = 1 ] && C+=(--profile demo)

echo "Building and starting (the first run downloads images and builds the panel — a few minutes)…"
"${C[@]}" up -d --build --wait --wait-timeout 600 control-plane knowledge
AIHUB_ADMIN_PASSWORD="$(cat "$STATE/admin-password")" \
  "${C[@]}" exec -T -e AIHUB_ADMIN_PASSWORD control-plane aihub-control create-admin >/dev/null
if [ "$DEMO" = 1 ]; then
  "${C[@]}" exec -T control-plane aihub-control demo-seed
  "${C[@]}" up -d --build --no-deps demo-worker
fi

cat <<EOF

AI Development Hub is running: http://127.0.0.1:$PORT
  user:     admin
  password: in $STATE/admin-password
$( [ "$DEMO" = 1 ] && echo "  demo:     Workspace → project “Demo project” → “+ New session” (mock engines); Chats answer with a mock." )
Stop: $0 --down
EOF
