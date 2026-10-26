#!/bin/bash
# Worker machine (Linux/WSL): aihub-worker as a systemd user service. Token: ~/.aihub/worker-token (0600).
# Real engines are opt-in (--enable-engines); workdirs are confined to the project's allowed_paths.
set -euo pipefail
ENGINES=${1:-codex}
# Where the hub is and how this worker is called (worker id as registered in the panel).
HUB_URL=${AIHUB_HUB_URL:?set AIHUB_HUB_URL, e.g. https://hub.example.ts.net}
WORKER_ID=${AIHUB_WORKER_ID:?set AIHUB_WORKER_ID, e.g. my-worker}
CODEMAN_URL=${AIHUB_CODEMAN_URL:-}   # optional: Codeman web terminal of this machine
cd ~/ai-dev-hub && git pull -q origin main
V=~/.venvs/aihub-worker
[ -d "$V" ] || python3 -m venv "$V"
"$V/bin/pip" install -q -e packages/contracts -e packages/agent-adapters -e packages/mcp-knowledge 2>&1 | grep -v notice || true
[ -s ~/.aihub/worker-token ] || { echo "no worker token"; exit 1; }
chmod 600 ~/.aihub/worker-token

mkdir -p ~/projects/hello-hub && cd ~/projects/hello-hub
[ -d .git ] || { git init -q && printf '# Hello Hub\n\nДемо-проект для AI Development Hub.\n' > README.md && git add README.md && git -c user.name=dev -c user.email=dev@local commit -qm init; }

mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/aihub-worker.service <<EOF
[Unit]
Description=AI Development Hub worker ($WORKER_ID)
After=network-online.target codeman-web.service

[Service]
ExecStart=$V/bin/aihub-worker --control-plane $HUB_URL --worker-id $WORKER_ID --token-file %h/.aihub/worker-token ${CODEMAN_URL:+--codeman-url $CODEMAN_URL} --enable-engines $ENGINES
Restart=on-failure
RestartSec=5
Environment=PATH=$HOME/.opencode/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable aihub-worker.service >/dev/null
systemctl --user restart aihub-worker.service
sleep 6
systemctl --user is-active aihub-worker.service
journalctl --user -u aihub-worker -n 5 --no-pager | cut -c1-200
