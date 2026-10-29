#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/../../.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/aihub-install-test.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home" PATH="$tmp/bin:$PATH"
mkdir -p "$HOME" "$tmp/bin" "$tmp/bundle/packages" "$tmp/state"
printf 'test-1.0.0\n' > "$tmp/bundle/VERSION"
for package in contracts agent-adapters mcp-knowledge; do mkdir -p "$tmp/bundle/packages/$package"; printf '[project]\nname = "stub"\nversion = "0.0.0"\n' > "$tmp/bundle/packages/$package/pyproject.toml"; done
tar -czf "$tmp/worker.tar.gz" -C "$tmp/bundle" .
printf 'worker-secret\n' > "$HOME/.token-source"
# The owner's legacy worker must survive: its unit and token are sentinels.
mkdir -p "$HOME/.aihub" "$HOME/.config/systemd/user"
printf 'legacy-secret\n' > "$HOME/.aihub/worker-token"
printf 'legacy-unit\n' > "$HOME/.config/systemd/user/aihub-worker.service"
legacy_sum=$(cat "$HOME/.aihub/worker-token" "$HOME/.config/systemd/user/aihub-worker.service" | sha256sum)
for id in test-worker second-hub; do
  mkdir -p "$HOME/.aihub/workers/$id"
  cp "$HOME/.token-source" "$HOME/.aihub/workers/$id/token"
done

cat > "$tmp/bin/python3" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == "-m" && "$2" == "venv" ]]
mkdir -p "$3/bin"
touch "$3/bin/python" "$3/bin/pip"
chmod +x "$3/bin/python" "$3/bin/pip"
EOF
cat > "$tmp/bin/pip" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$tmp/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${AIHUB_TEST_STATE}/systemctl.log"
EOF
cat > "$tmp/bin/loginctl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$tmp/bin/"*
export AIHUB_TEST_STATE="$tmp/state"

install() { "$root/deploy/pc-worker/install-worker.sh" --bundle "$tmp/worker.tar.gz" --worker-id "$1" --engines mock --hub-url https://hub.example; }
install test-worker
first=$(readlink "$HOME/.local/share/aihub-worker/current")
install test-worker >/dev/null
second=$(readlink "$HOME/.local/share/aihub-worker/current")
[[ "$first" == "$second" ]]
install second-hub >/dev/null
for id in test-worker second-hub; do
  [[ "$(stat -c '%a' "$HOME/.aihub/workers/$id")" == 700 ]]
  [[ "$(stat -c '%a' "$HOME/.aihub/workers/$id/token")" == 600 ]]
  grep -F -- "--control-plane https://hub.example --worker-id $id --token-file %h/.aihub/workers/$id/token --enable-engines mock" "$HOME/.config/systemd/user/aihub-worker-$id.service" >/dev/null
  grep -F -- "enable --now aihub-worker-$id.service" "$tmp/state/systemctl.log" >/dev/null
done
# Exactly the per-id units were written; the legacy unit and token are untouched.
[[ "$(cd "$HOME/.config/systemd/user" && ls | sort | tr '\n' ' ')" == "aihub-worker-second-hub.service aihub-worker-test-worker.service aihub-worker.service " ]]
[[ "$(cat "$HOME/.aihub/worker-token" "$HOME/.config/systemd/user/aihub-worker.service" | sha256sum)" == "$legacy_sum" ]]
if grep -E '(^| )aihub-worker(\.service)?( |$)' "$tmp/state/systemctl.log"; then echo 'legacy unit touched' >&2; exit 1; fi
# --unit is no longer accepted: the unit name is derived from the id only.
if "$root/deploy/pc-worker/install-worker.sh" --bundle "$tmp/worker.tar.gz" --worker-id test-worker --engines mock --hub-url https://hub.example --unit aihub-worker 2>/dev/null; then
  echo '--unit must be rejected' >&2; exit 1
fi
echo 'install-worker shell test: ok'
