# Workers

A worker is a small process on a machine where agent CLIs are installed. It connects **out** to the hub; the
hub never connects to the worker.

## Requirements

- Linux or WSL2, Python 3.12, git.
- The CLIs you want to use, installed and runnable: `claude` (Claude Code) and/or `codex`.
- Network access to the hub URL (e.g. over Tailscale).

## Install

1. In the panel: **Settings → Workers → Add** — give it an id (e.g. `laptop`). Copy the one-time worker token.
2. On the machine:

```bash
git clone https://github.com/mrazall/ai-development-hub ~/ai-dev-hub
mkdir -p ~/.aihub && umask 077 && printf '%s' '<token>' > ~/.aihub/worker-token
AIHUB_HUB_URL=https://hub.example.ts.net AIHUB_WORKER_ID=laptop \
  bash ~/ai-dev-hub/deploy/pc-worker/setup-worker.sh claude_code,codex
```

The script creates a virtualenv, installs the worker and the MCP server, and registers a systemd **user**
service `aihub-worker`. Engines are opt-in: only those listed in `--enable-engines` run (the built-in `mock*`
engines always can).

3. **Settings → Accounts** — add a profile per subscription (Claude Code / Codex) on this worker and follow the
   login instructions once (the CLI logs in under that profile's own config directory).

## Options

| Flag / env | Default | Meaning |
|---|---|---|
| `--control-plane` | — | hub URL |
| `--worker-id`, `--token-file` | — | identity |
| `--enable-engines` | none | real engines this worker may run: `claude_code`, `codex` |
| `--max-session-seconds` | 86400 | timeout of a run, at most 24 h (orchestrators: `AIHUB_ORCHESTRATOR_MAX_SECONDS`, also up to 24 h) |
| `--codeman-url` | — | optional Codeman web terminal on this machine |
| `AIHUB_WORKER_MAX_PARALLEL` | 6 | sessions at a time |
| `AIHUB_WORKSPACE_ROOTS` | `~/projects` | where the hub may create project folders (`:`-separated) |
| `AIHUB_CLAUDE_EFFORT` | `low` | default `claude --effort` (a chat can choose its own) |
| `AIHUB_CLAUDE_CONTEXT_LIMIT` | 250000 | compact the conversation above this many context tokens |
| `AIHUB_WORKER_TERMINAL` | `1` | the embedded shell in the panel (`0` disables) |

## Safety

Agents run with the worker user's permissions. Working directories are confined to the project's allowed
paths, executors work in their own git worktrees, and non-interactive engines get an explicit allow-list of
tools — but this is not a sandbox. Run workers under a dedicated user or VM if that matters to you; see
[SECURITY.md](../SECURITY.md).

## Worker is offline

The hub marks a worker offline when its heartbeats stop; the reason is on the worker's side. Start with its
journal — the worker says why it cannot reach the hub, once per change:

```bash
journalctl --user -u aihub-worker -n 50 --no-pager | grep -E "hub (un)?reachable"
```

- **`cannot resolve <host>`** — DNS on the worker machine does not know the hub's name. Typical in WSL2 on
  Windows 10 after a reboot: the WSL DNS proxy (`nameserver` in `/etc/resolv.conf`, e.g. `172.29.x.1`) stops
  answering, often with a VPN client or Tailscale changing Windows DNS, and `dnsTunneling` is not available on
  Windows 10. Check and fix:

  ```bash
  getent hosts hub.<tailnet>.ts.net                 # empty = not resolved
  tailscale ip -4 <hub-machine>                     # on Windows: the hub's tailnet address
  ```

  Then either point WSL to working DNS servers or pin the hub's tailnet address (stable while the machine stays
  in the tailnet):

  ```ini
  # /etc/wsl.conf — keep WSL from overwriting the files below on restart
  [network]
  generateResolvConf = false
  generateHosts = false
  ```

  ```bash
  printf 'nameserver 192.168.1.1\nnameserver 1.1.1.1\n' | sudo tee /etc/resolv.conf   # your router + a public one
  echo '100.x.y.z hub.<tailnet>.ts.net' | sudo tee -a /etc/hosts
  wsl.exe --shutdown   # from Windows, then start the distro again
  systemctl --user restart aihub-worker
  ```

  With `generateHosts = false` entries of the Windows `hosts` file no longer reach WSL.
- **`does not answer in time` / `connection refused`** — the name resolves but the hub is not reachable: the
  hub is down, a VPN routes the traffic elsewhere, or a firewall drops it. `curl -sS <hub>/api/v0/health`.
- **`TLS error`** — a proxy or a wrong system clock.

The Windows app checks this by itself: when the hub answers Windows but shows the worker offline, it looks from
inside WSL (DNS, then a TCP connection) and shows the reason in the tray.
