#!/usr/bin/env bash
set -Eeuo pipefail

repo="${AIHUB_RESTIC_REPOSITORY:-/srv/media2/restic-aihub}"
password_file="${AIHUB_RESTIC_PASSWORD_FILE:-$HOME/ai-dev-hub/secrets/restic-aihub-password}"
compose_file="${AIHUB_COMPOSE_FILE:-infra/docker-compose.yml}"
compose_project="${AIHUB_COMPOSE_PROJECT:-aihub}"
restic_image="${AIHUB_RESTIC_IMAGE:-restic/restic:0.19.1}"
report_url="${AIHUB_BACKUP_REPORT_URL:-http://127.0.0.1:58080/api/v0/backups/report}"
token_file="${AIHUB_BACKUP_TOKEN_FILE:-$HOME/ai-dev-hub/secrets/backup-api-token}"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/aihub-restore.XXXXXX")"
trap 'rm -rf -- "$work_dir"' EXIT

# Same containerised restic as aihub-backup.sh; restores into a scratch directory, never over live data.
restic() {
  docker run --rm -v "$repo":/repo:ro -v "$password_file":/pw:ro -v "$work_dir":/restore \
    -e RESTIC_PASSWORD_FILE=/pw "$restic_image" -r /repo --no-lock "$@"
}
pg() {
  docker compose -p "$compose_project" -f "$compose_file" exec -T postgres "$@"
}

snapshot="$(restic snapshots --json --tag aihub | python3 -c 'import json,sys; xs=json.load(sys.stdin); print(xs[-1]["short_id"])')"
restic restore "$snapshot" --target /restore
dump="$(find "$work_dir" -type f -name 'aihub-postgres.dump' -print -quit)"
[[ -n "$dump" && -f "$dump" ]] || { echo "latest backup has no PostgreSQL dump" >&2; exit 1; }

# A separate scratch database: the live database is never touched.
pg dropdb --if-exists --username "${POSTGRES_USER:-aihub}" aihub_restore_test
pg createdb --username "${POSTGRES_USER:-aihub}" aihub_restore_test
pg pg_restore --no-owner --no-privileges --username "${POSTGRES_USER:-aihub}" --dbname aihub_restore_test < "$dump"

# Exact counts (pg_stat n_live_tup is 0 right after a restore).
rows="$(pg psql --tuples-only --no-align --username "${POSTGRES_USER:-aihub}" --dbname aihub_restore_test -c \
  "SELECT (SELECT count(*) FROM control.users) + (SELECT count(*) FROM control.projects)
        + (SELECT count(*) FROM control.sessions) + (SELECT count(*) FROM control.agent_events);" | tr -d '[:space:]')"
[[ "$rows" =~ ^[0-9]+$ && "$rows" -gt 0 ]] || { echo "restored database has no rows" >&2; exit 1; }
pg dropdb --username "${POSTGRES_USER:-aihub}" aihub_restore_test
finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [[ -r "$token_file" ]]; then
  token="$(<"$token_file")"
  report="$(python3 - "$snapshot" "$finished" "$rows" <<'PY'
import json, sys
print(json.dumps({"id": "restore-" + sys.argv[1], "repo": "restic-aihub", "kind": "restore_test", "started_at": sys.argv[2], "finished_at": sys.argv[2], "ok": True, "size_bytes": None, "tags": ["aihub", "restore-test", "rows=" + sys.argv[3]]}))
PY
  )"
  curl --fail-with-body --silent --show-error --retry 4 --retry-all-errors --max-time 20 \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' --data "$report" "$report_url" >/dev/null
fi
printf 'AI Hub restore test completed: snapshot=%s control_rows=%s\n' "$snapshot" "$rows"
