#!/usr/bin/env bash
set -euo pipefail
bundle=; worker_id=; engines=; hub_url=
usage() { echo "usage: $0 --bundle FILE.tar.gz --worker-id ID --engines LIST --hub-url URL" >&2; }
die() { echo "install-worker: $*" >&2; exit 2; }
while (($#)); do
  case "$1" in
    --bundle) (($# >= 2)) || die "--bundle needs a value"; bundle=$2; shift 2 ;;
    --worker-id) (($# >= 2)) || die "--worker-id needs a value"; worker_id=$2; shift 2 ;;
    --engines) (($# >= 2)) || die "--engines needs a value"; engines=$2; shift 2 ;;
    --hub-url) (($# >= 2)) || die "--hub-url needs a value"; hub_url=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ -n "$bundle" && -f "$bundle" ]] || die "bundle does not exist"
[[ "$worker_id" =~ ^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$ ]] || die "invalid worker id"
# Each worker id gets its own unit and token, so several hubs/workers can share
# one machine and the legacy `aihub-worker` unit / ~/.aihub/worker-token stay untouched.
unit="aihub-worker-$worker_id"
token_dir="$HOME/.aihub/workers/$worker_id"
token_file="$token_dir/token"
[[ "$hub_url" =~ ^https://[^[:space:]]+$ || "$hub_url" =~ ^http://(localhost|127\.0\.0\.1)(:[0-9]+)?(/.*)?$ ]] || die "invalid hub URL"
[[ "$engines" =~ ^(claude_code|codex|mock)(,(claude_code|codex|mock))*$ ]] || die "invalid engines"
base="$HOME/.local/share/aihub-worker"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/aihub-worker.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
tar -xzf "$bundle" -C "$tmp"
[[ -s "$tmp/VERSION" ]] || die "bundle has no VERSION"
version=$(head -n 1 "$tmp/VERSION" | tr -d '\r\n')
[[ "$version" =~ ^[0-9A-Za-z][0-9A-Za-z._+-]*$ ]] || die "invalid bundle version"
target="$base/$version"
mkdir -p "$base"
if [[ ! -d "$target" ]]; then mkdir -p "$target"; cp -a "$tmp/." "$target/"; fi
ln -sfn "$target" "$base/current"
venv="$target/.venv"
if [[ ! -x "$venv/bin/python" ]]; then python3 -m venv "$venv"; fi
"$venv/bin/pip" install --disable-pip-version-check -q "$target/packages/contracts" "$target/packages/agent-adapters" "$target/packages/mcp-knowledge"
mkdir -p "$HOME/.config/systemd/user"
[[ -s "$token_file" ]] || { echo "worker token is missing at ~/.aihub/workers/$worker_id/token" >&2; exit 1; }
chmod 700 "$token_dir"
chmod 600 "$token_file"
cat > "$HOME/.config/systemd/user/$unit.service" <<EOF
[Unit]
Description=AI Development Hub worker ($worker_id)
After=network-online.target

[Service]
ExecStart=$venv/bin/aihub-worker --control-plane $hub_url --worker-id $worker_id --token-file %h/.aihub/workers/$worker_id/token --enable-engines $engines
Restart=on-failure
RestartSec=5
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now "$unit.service" >/dev/null
if command -v loginctl >/dev/null 2>&1; then loginctl enable-linger "$(id -un)" >/dev/null 2>&1 || echo "Could not enable linger; run: loginctl enable-linger $(id -un)" >&2; else echo "loginctl unavailable; enable user linger to run the worker after logout" >&2; fi
echo "Installed worker $version ($unit)"
