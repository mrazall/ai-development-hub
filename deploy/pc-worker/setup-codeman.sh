#!/bin/bash
# PC worker (WSL, user dev): Codeman as a systemd user service on loopback :3000.
# Exposure to the tailnet is a separate, explicit step on Windows (tailscale serve), never 0.0.0.0.
set -euo pipefail
APP=~/Codeman
[ -f "$APP/dist/index.js" ] || { echo "build Codeman first: https://github.com/Ark0N/Codeman"; exit 1; }
mkdir -p ~/.config/systemd/user ~/.aihub
# Codeman is a terminal with this user's rights: never reachable without a password.
[ -f ~/.aihub/codeman.env ] || (umask 077; printf "CODEMAN_PASSWORD=%s
" "$(openssl rand -hex 16)" > ~/.aihub/codeman.env)
cat > ~/.config/systemd/user/codeman-web.service <<EOF
[Unit]
Description=Codeman web (AI Development Hub agent workspace)
After=network-online.target

[Service]
WorkingDirectory=$APP
ExecStart=$(command -v node) $APP/dist/index.js web --host 127.0.0.1 --port 3000
Restart=on-failure
EnvironmentFile=%h/.aihub/codeman.env
Environment=PATH=$HOME/.opencode/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable codeman-web.service
systemctl --user restart codeman-web.service
sleep 4
systemctl --user is-active codeman-web.service
curl -s -o /dev/null -w "codeman http %{http_code}\n" http://127.0.0.1:3000/
