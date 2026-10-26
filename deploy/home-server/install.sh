#!/bin/bash
# Runs on the server: install.sh <release-dir>. Idempotent; never prints secrets.
# A release dir is a checkout of this repo with the panel built into apps/web/dist.
# Needs: AIHUB_VAULT_HOST_DIR (your notes), AIHUB_PUBLIC_URL; optional AIHUB_BASE (default ~/aihub).
set -euo pipefail
REL=$(cd "$1" && pwd)
BASE=${AIHUB_BASE:-$HOME/aihub}
SECRETS=$BASE/secrets
VAULT=${AIHUB_VAULT_HOST_DIR:?set AIHUB_VAULT_HOST_DIR to your vault}
: "${AIHUB_PUBLIC_URL:?set AIHUB_PUBLIC_URL, e.g. https://hub.<your-tailnet>.ts.net}"
cd "$REL"
[ -f apps/web/dist/index.html ] || { echo "build the panel first: (cd apps/web && npm ci && npm run build)"; exit 1; }

sh infra/scripts/init-secrets.sh "$SECRETS"      # creates only missing files, umask 077
for name in restic-aihub-password backup-api-token; do
  [ -s "$SECRETS/$name" ] || (umask 077; openssl rand -base64 36 | tr -d '\n' > "$SECRETS/$name")
done
[ -d "$VAULT" ] || { echo "vault $VAULT missing"; exit 1; }
# Agents' drafts: the one writable folder of the vault. Created here (not by Docker as root) so the
# knowledge container (uid 1000) can write into it.
mkdir -p "$VAULT/_Агенты" "$BASE/tailscale/run" "$BASE/stack"

cat > "$BASE/aihub.env" <<EOF
AIHUB_SECRETS_HOST_DIR=$SECRETS
AIHUB_VAULT_HOST_DIR=$VAULT
AIHUB_WEB_HOST_DIR=$REL/apps/web/dist
AIHUB_TAILSCALE_RUN_DIR=$BASE/tailscale/run
AIHUB_PUBLIC_URL=$AIHUB_PUBLIC_URL
EOF
chmod 600 "$BASE/aihub.env"

C="docker compose -p aihub --env-file infra/.env.example --env-file $BASE/aihub.env -f infra/docker-compose.yml -f deploy/home-server/docker-compose.home.yml"
$C build -q
$C up -d --wait --wait-timeout 300
ln -sfn "$REL" "$BASE/stack/current"

# First admin: random password in a 0600 file; never echoed.
if [ ! -f "$SECRETS/admin-initial-password" ]; then
  (umask 077; openssl rand -base64 18 | tr -d '/+=' > "$SECRETS/admin-initial-password")
  AIHUB_ADMIN_PASSWORD="$(cat "$SECRETS/admin-initial-password")" $C exec -T -e AIHUB_ADMIN_PASSWORD control-plane aihub-control create-admin >/dev/null
  echo "admin created; initial password: $SECRETS/admin-initial-password"
fi
$C ps --format '{{.Service}} {{.Status}}'
