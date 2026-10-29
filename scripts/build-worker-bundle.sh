#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
output_dir=${1:-"$repo_root/apps/desktop/src-tauri/resources"}
app_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$repo_root/apps/desktop/src-tauri/tauri.conf.json")
# The worker ships with the app version, so updating the app updates the worker.
version=${AIHUB_WORKER_VERSION:-$app_version}
[[ "$version" =~ ^[0-9A-Za-z][0-9A-Za-z._+-]*$ ]] || { echo "invalid version" >&2; exit 2; }
mkdir -p "$output_dir"
stage=$(mktemp -d "${TMPDIR:-/tmp}/aihub-worker-bundle.XXXXXX")
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/packages" "$stage/deploy/pc-worker"
cp -a "$repo_root/packages/contracts" "$stage/packages/"
cp -a "$repo_root/packages/agent-adapters" "$stage/packages/"
cp -a "$repo_root/packages/mcp-knowledge" "$stage/packages/"
cp "$repo_root/deploy/pc-worker/install-worker.sh" "$stage/deploy/pc-worker/"
printf '%s\n' "$version" > "$stage/VERSION"
find "$stage" -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .venv -o -name tests \) -prune -exec rm -rf {} +
find "$stage" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
archive="$output_dir/aihub-worker.tar.gz"
tar -czf "$archive" -C "$stage" .
echo "$archive"
