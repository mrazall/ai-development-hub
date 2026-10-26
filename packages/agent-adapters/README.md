# AI Hub worker

Install the package in the worker's WSL environment and keep its bearer token in a
user-readable file outside the repository (for example `~/.config/aihub/worker.token`,
mode `600`). A systemd user unit can start it after login:

```ini
[Unit]
Description=AI Development Hub worker
After=network-online.target

[Service]
ExecStart=%h/.local/bin/aihub-worker --control-plane http://127.0.0.1:8000 --worker-id wsl-1 --token-file %h/.config/aihub/worker.token
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Save as `~/.config/systemd/user/aihub-worker.service`, then run
`systemctl --user daemon-reload && systemctl --user enable --now aihub-worker`.
Do not put the token in the unit file or in git. For a headless WSL session, enable
systemd in `/etc/wsl.conf` and use `loginctl enable-linger <user>`.
