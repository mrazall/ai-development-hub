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
| `--max-session-seconds` | 3600 | timeout of a run (orchestrators: `AIHUB_ORCHESTRATOR_MAX_SECONDS`, up to 4 h) |
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
