#!/usr/bin/env bash
set -Eeuo pipefail

# Stage 5 scaffold: run from the deployment directory after reviewing the target.
# This deliberately writes only to the caller-provided local output path.
output_path="${1:-./backups/postgres-$(date -u +%Y%m%dT%H%M%SZ).dump}"
mkdir -p "$(dirname -- "$output_path")"
docker compose -f infra/docker-compose.yml exec -T postgres \
  pg_dump --format=custom --no-owner --no-privileges \
  --username "${POSTGRES_USER:-aihub}" --dbname "${POSTGRES_DB:-aihub}" \
  > "$output_path"
printf 'PostgreSQL dump written to %s\n' "$output_path"
