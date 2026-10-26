#!/bin/bash
# Dev databases for scripts/dev/*.sh and scripts/predeploy-check.sh: Postgres on 127.0.0.1:55432 (container
# aihub-dev-pg, user aihub, password aihub-dev-only — local development only) and Qdrant on 127.0.0.1:56333.
# Idempotent. Remove with: docker rm -f aihub-dev-pg aihub-dev-qdrant
set -euo pipefail
up() { docker start "$1" >/dev/null 2>&1 || docker run -d --name "$1" "${@:2}" >/dev/null; }
up aihub-dev-pg -p 127.0.0.1:55432:5432 -e POSTGRES_DB=aihub -e POSTGRES_USER=aihub \
  -e POSTGRES_PASSWORD=aihub-dev-only -v aihub-dev-pg:/var/lib/postgresql/data postgres:16.10-alpine
up aihub-dev-qdrant -p 127.0.0.1:56333:6333 -v aihub-dev-qdrant:/qdrant/storage qdrant/qdrant:v1.15.4
for _ in $(seq 1 60); do docker exec aihub-dev-pg pg_isready -U aihub -d aihub >/dev/null 2>&1 && break; sleep 1; done
docker exec aihub-dev-pg psql -U aihub -d aihub -qtc "SELECT 1 FROM pg_database WHERE datname='aihub_dev'" | grep -q 1 \
  || docker exec aihub-dev-pg createdb -U aihub aihub_dev
echo "dev Postgres on 127.0.0.1:55432 (db aihub_dev), Qdrant on 127.0.0.1:56333"
