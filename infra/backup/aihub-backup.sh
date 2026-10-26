#!/usr/bin/env bash
set -Eeuo pipefail

# Backs up only this project's database and non-secret configuration. It never
# runs restic against an existing homelab repository unless explicitly passed.
repo="${AIHUB_RESTIC_REPOSITORY:-/srv/media/restic-aihub}"
password_file="${AIHUB_RESTIC_PASSWORD_FILE:-$HOME/ai-dev-hub/secrets/restic-aihub-password}"
compose_file="${AIHUB_COMPOSE_FILE:-infra/docker-compose.yml}"
compose_project="${AIHUB_COMPOSE_PROJECT:-aihub}"
# restic runs in a container, like the homelab backups (no host install, no sudo); pinned version.
restic_image="${AIHUB_RESTIC_IMAGE:-restic/restic:0.19.1}"
report_url="${AIHUB_BACKUP_REPORT_URL:-http://127.0.0.1:58080/api/v0/backups/report}"
token_file="${AIHUB_BACKUP_TOKEN_FILE:-$HOME/ai-dev-hub/secrets/backup-api-token}"
run_check="${AIHUB_RESTIC_CHECK:-0}"
include_vault="${AIHUB_BACKUP_INCLUDE_VAULT:-0}"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/aihub-backup.XXXXXX")"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

report_failure() {
  local rc="$1" token report finished
  [[ -r "$token_file" ]] || return 0
  token="$(<"$token_file")"
  finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  report="$(python3 - "$started" "$finished" "$rc" <<'PY'
import json, sys
print(json.dumps({"id": "failed-" + sys.argv[2].replace(":", ""), "repo": "restic-aihub", "kind": "database", "started_at": sys.argv[1], "finished_at": sys.argv[2], "ok": False, "error": "backup command failed (exit " + sys.argv[3] + ")", "tags": ["aihub"]}))
PY
  )"
  curl --fail-with-body --silent --show-error --retry 2 --retry-all-errors --max-time 20 \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    --data "$report" "$report_url" >/dev/null || true
}

trap 'rc=$?; if ((rc != 0)); then report_failure "$rc"; fi; rm -rf -- "$work_dir"; exit "$rc"' EXIT

[[ -r "$password_file" ]] || { echo "restic password file is not readable" >&2; exit 2; }
mkdir -p "$work_dir/config" "$repo"
# Chat attachments live in the control-plane data volume; backed up read-only next to the dump.
data_volume="${AIHUB_DATA_VOLUME:-${compose_project}_control_data}"
data_mount=()
docker volume inspect "$data_volume" >/dev/null 2>&1 && data_mount=(-v "$data_volume":/backup-data:ro)
restic() {
  docker run --rm -v "$repo":/repo -v "$password_file":/pw:ro -v "$work_dir":/backup:ro "${data_mount[@]}" \
    -e RESTIC_PASSWORD_FILE=/pw "$restic_image" -r /repo "$@"
}
restic cat config >/dev/null 2>&1 || restic init >/dev/null

dump="$work_dir/aihub-postgres.dump"
docker compose -p "$compose_project" -f "$compose_file" exec -T postgres pg_dump --format=custom --no-owner --no-privileges \
  --username "${POSTGRES_USER:-aihub}" --dbname "${POSTGRES_DB:-aihub}" > "$dump"

# Explicitly copy allowlisted configuration and exclude secret material.
for path in infra/docker-compose.yml infra/docker-compose.override.yml infra/.env.example; do
  [[ -f "$path" ]] && cp -- "$path" "$work_dir/config/"
done
if [[ "$include_vault" == 1 && -d "${AIHUB_VAULT_HOST_DIR:-./vault}" ]]; then
  mkdir -p "$work_dir/config/vault"
  cp -a -- "${AIHUB_VAULT_HOST_DIR:-./vault}/." "$work_dir/config/vault/"
fi

backup_json="$work_dir/restic.json"
backup_paths=(/backup)
((${#data_mount[@]})) && backup_paths+=(/backup-data)
restic backup --json --tag aihub "${backup_paths[@]}" > "$backup_json"
snapshot_id="$(python3 -c 'import json,sys; xs=[json.loads(x) for x in open(sys.argv[1]) if x.strip()]; print(xs[-1].get("snapshot_id", "unknown"))' "$backup_json")"
size_bytes="$(stat -c '%s' "$dump")"
restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
[[ "$run_check" == 1 ]] && restic check

finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [[ -r "$token_file" ]]; then
  token="$(<"$token_file")"
  report="$(python3 - "$snapshot_id" "$started" "$finished" "$size_bytes" <<'PY'
import json, sys
print(json.dumps({"id": sys.argv[1], "repo": "restic-aihub", "kind": "database", "started_at": sys.argv[2], "finished_at": sys.argv[3], "ok": True, "size_bytes": int(sys.argv[4]), "tags": ["aihub"]}))
PY
  )"
  curl --fail-with-body --silent --show-error --retry 4 --retry-all-errors --max-time 20 \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    --data "$report" "$report_url" >/dev/null
else
  echo "backup completed; report token file is not readable" >&2
fi
printf 'AI Hub backup completed: snapshot=%s size_bytes=%s\n' "$snapshot_id" "$size_bytes"
