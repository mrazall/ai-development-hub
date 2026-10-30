#!/usr/bin/env bash
set -Eeuo pipefail

# Backs up only this project's database and non-secret configuration. It never
# runs restic against an existing homelab repository unless explicitly passed.
repo="${AIHUB_RESTIC_REPOSITORY:-/srv/media2/restic-aihub}"
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

# report <id> <kind> <ok> <size_bytes|""> <error|"">: one row on the panel's Backups page per kind.
report() {
  local token body
  [[ -r "$token_file" ]] || { echo "report token file is not readable" >&2; return 1; }
  token="$(<"$token_file")"
  body="$(python3 - "$1" "$2" "$3" "$4" "$5" "$started" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" <<'PY'
import json, sys
id_, kind, ok, size, error, started, finished = sys.argv[1:]
row = {"id": id_, "repo": "restic-aihub", "kind": kind, "started_at": started, "finished_at": finished,
       "ok": ok == "1", "tags": ["aihub"]}
if size:
    row["size_bytes"] = int(size)
if error:
    row["error"] = error
print(json.dumps(row))
PY
  )"
  curl --fail-with-body --silent --show-error --retry 4 --retry-all-errors --max-time 20 \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    --data "$body" "$report_url" >/dev/null
}

report_failure() {
  local stamp
  stamp="failed-$(date -u +%Y%m%dT%H%M%SZ)"
  report "$stamp" database 0 "" "backup command failed (exit $1)" || true
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
vault_dir="${AIHUB_VAULT_HOST_DIR:-./vault}"
if [[ "$include_vault" == 1 ]]; then
  [[ -d "$vault_dir" ]] || { echo "vault directory $vault_dir not found" >&2; exit 3; }
  mkdir -p "$work_dir/vault"
  cp -a -- "$vault_dir/." "$work_dir/vault/"
fi

backup_json="$work_dir/restic.json"
backup_paths=(/backup)
((${#data_mount[@]})) && backup_paths+=(/backup-data)
restic backup --json --tag aihub "${backup_paths[@]}" > "$backup_json"
snapshot_id="$(python3 -c 'import json,sys; xs=[json.loads(x) for x in open(sys.argv[1]) if x.strip()]; print(xs[-1].get("snapshot_id", "unknown"))' "$backup_json")"
size_bytes="$(stat -c '%s' "$dump")"
restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
[[ "$run_check" == 1 ]] && restic check

# The config files and the vault ride in the same restic snapshot; each gets its own row (id suffixed).
report "$snapshot_id" database 1 "$size_bytes" "" || echo "backup completed; database report failed" >&2
report "$snapshot_id-config" config 1 "$(du -sb "$work_dir/config" | cut -f1)" "" || true
vault_size=""
if [[ "$include_vault" == 1 ]]; then
  vault_size="$(du -sb "$work_dir/vault" | cut -f1)"
  report "$snapshot_id-vault" vault 1 "$vault_size" "" || true
fi
printf 'AI Hub backup completed: snapshot=%s size_bytes=%s vault_bytes=%s\n' "$snapshot_id" "$size_bytes" "${vault_size:-off}"
