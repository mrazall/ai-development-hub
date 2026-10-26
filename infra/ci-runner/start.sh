#!/bin/bash
set -euo pipefail
cd /home/runner
command -v docker >/dev/null || (apt-get update -qq && apt-get install -y -qq docker.io >/dev/null)
# docker.io ships without the compose v2 plugin; CI jobs need `docker compose`.
docker compose version >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq docker-compose-v2 >/dev/null)
docker compose version
mkdir -p "$TMPDIR"
# Конфигурация раннера (.runner, .credentials*) переживает пересоздание контейнера.
for f in .runner .credentials .credentials_rsaparams; do
  [ -f "/state/$f" ] && cp "/state/$f" "$f"
done
if [ ! -f .runner ]; then
  token=$(cat /run/aihub/token 2>/dev/null || true)
  [ -n "$token" ] || { echo "no registration token in ./token" >&2; exit 1; }
  ./config.sh --unattended --replace --url "$AIHUB_RUNNER_REPO_URL" --token "$token" \
    --name "$AIHUB_RUNNER_NAME" --labels self-hosted,linux,aihub --work "$AIHUB_RUNNER_WORK"
  unset token
  cp .runner .credentials .credentials_rsaparams /state/
  chmod 600 /state/.credentials /state/.credentials_rsaparams
fi
exec ./run.sh
