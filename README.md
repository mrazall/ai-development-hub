<p align="center">
  <img src="apps/web/public/brand/logo-nodes.svg" width="72" alt="">
</p>

<h1 align="center">AI Development Hub</h1>

<p align="center">
  A self-hosted control room for AI coding agents.<br>
  Run <b>Claude Code</b> and <b>Codex</b> on your own machines and subscriptions, watch every session live,
  let an orchestrator split work across git branches, and give agents a shared, reviewable memory in your
  Obsidian vault.
</p>

<p align="center">
  <a href="https://github.com/mrazall/ai-development-hub/actions/workflows/ci.yml"><img src="https://github.com/mrazall/ai-development-hub/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License: Apache-2.0"></a>
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Status: alpha">
</p>

![The demo: a session, a chat with memory and the knowledge graph (mock engines)](docs/assets/demo.gif)

<sub>Recorded in the built-in demo mode: the agents are mock engines that echo the task, so it runs without any
subscription. Real sessions look the same with Claude Code or Codex output.</sub>

> **Status: alpha.** It runs the author's homelab every day: real Claude Code and Codex sessions, orchestration and
> notes. Expect rough edges. Read [Limitations](#limitations) and [SECURITY.md](SECURITY.md) first.

## Why

Agent CLIs are great in a terminal and awkward everywhere else:

- a session lives in one terminal on one machine; close the laptop and it is gone;
- a provider limit stops a long job halfway, and you restart it by hand when the window resets;
- every run starts from zero: there is no memory the next agent can search, and no review of what agents
  "remember";
- two agents on one checkout step on each other's files.

AI Development Hub keeps the agents **where their logins, tools and code already are — your machines** — and gives
you one panel for all of them. Subscription logins never leave the workers: each CLI logs in there, the official
way, under its own per-account config directory.

## What you can do with it

**Watch and steer agents from anywhere on your network.** Start a Claude Code or Codex session on any registered
machine from the browser (or your phone over Tailscale), follow its output live, open a shell in its working
folder, look at the git diff, and send follow-up messages. Attach files to a task — pick them, drop them, or
paste them from the clipboard.

**Decide what an agent may do.** Each Claude Code session has a permission mode: *edits only* (file edits, no
commands), *ask* (every other action becomes an approval in the panel — Allow or Reject, with a notification),
*auto* (Claude Code's own auto mode decides and blocks risky actions) or *allow everything*. You can change it
when you continue a session.

**Let long jobs survive limits.** When a subscription limit stops a session, the hub schedules it to resume the
moment the limit resets, in the same CLI conversation.

**Split a task between agents.** In orchestrated mode a Claude orchestrator publishes a plan, starts up to four
Codex executors, each in its own git worktree and branch, reviews their work and merges it. You see the plan,
every executor's branch, changed files, token usage and cost. With *manual merge* on, the orchestrator asks and
you press *Accept*.

**Give agents a memory you control.** Your Obsidian vault is indexed for hybrid search (Postgres full text +
Qdrant vectors) and exposed to agents through an MCP server. Agents never edit your notes: they write **drafts**
into one folder; you review a draft, and one click lets a model merge it into the right notes as a git commit
— one more click reverts it. Browse the vault as a list or a link graph.

**Chat with your notes.** Personal Claude chats that can search the vault; choose the account, model and effort
per message.

**Know when something breaks.** A System health page checks workers, Tailscale, account limits, the index,
backups and recent failures, and sends a notification when a check fails or recovers.

## Why self-hosted

- **Your subscriptions, your machines.** Agents run where you already installed and logged in the CLIs. No
  hosted service in between and no telemetry.
- **Your code and notes stay local.** The hub is Docker Compose on a laptop or a home server; workers connect
  *out* to it, so worker machines need no open ports.
- **Private network first.** Bind to `127.0.0.1` and reach it over Tailscale/WireGuard. The repository ships a
  home-server template with Tailscale in a container.
- **Plain, inspectable parts.** FastAPI, Postgres, Qdrant, React; Alembic migrations; restic backups; Apache-2.0.

## Quickstart: the demo (about 5 minutes)

Needs Docker with Compose v2 and `openssl`. Nothing is exposed beyond `127.0.0.1`.

```bash
git clone https://github.com/mrazall/ai-development-hub && cd ai-development-hub
./scripts/quickstart.sh --demo
```

Open http://127.0.0.1:58080 and sign in as `admin`; the generated password is in `.aihub/admin-password` (the
`.aihub/` folder holds all local secrets, mode 0700, git-ignored). The demo worker runs **mock engines** — they
echo the task or write a file — so you can create sessions, chat and browse the demo vault without any
subscription. Orchestration needs real agents and is not part of the demo.

Stop it with `./scripts/quickstart.sh --down` (data volumes are kept); `--reset` deletes the demo's data and
`.aihub/` to start over.

## Real agents

1. Start the hub without the demo: `./scripts/quickstart.sh`, or deploy it on a server —
   [docs/deployment.md](docs/deployment.md).
2. On each machine with Claude Code and/or Codex (Linux or WSL2), run a worker — [docs/workers.md](docs/workers.md).
3. **Settings → Accounts**: add a profile per subscription and log the CLI in once under that profile.
4. Point the knowledge service at your vault (`AIHUB_VAULT_HOST_DIR`) — [docs/configuration.md](docs/configuration.md).

## How it works

```
 browser ──HTTPS──▶  hub (control plane + panel) ──▶ Postgres, knowledge service (Qdrant, embeddings)
                         ▲            ▲
          poll / events  │            │  MCP (memory, orchestration)
                         │            │
             worker on machine A   worker on machine B ──▶ claude / codex CLIs, git worktrees
```

- **Hub** — FastAPI control plane and the React panel: users and roles, projects, sessions and their event log,
  orchestration, settings, health, notifications.
- **Knowledge service** — indexes the vault (read-only mount), hybrid search, the link graph, agents' drafts.
- **Worker** — a small Python process per machine. It polls the hub for work, runs the CLI in the project
  folder, streams events back and keeps per-account CLI config directories.
- **MCP server** — gives agents the memory and, for orchestrators, the orchestration tools, with short-lived
  scoped tokens.

More: [architecture](docs/architecture.md) · [configuration](docs/configuration.md) ·
[engines](docs/engines.md) (adding another agent CLI) · [workers](docs/workers.md) ·
[deployment](docs/deployment.md).

## Limitations

- **Agents are not sandboxed by this project.** They run with your user's rights on the worker, in the project
  folder. Codex uses its own `workspace-write` sandbox; for Claude Code you pick the permissions per session
  (below). Use a dedicated user or VM for workers when that matters. See [SECURITY.md](SECURITY.md).
- **Not for the open internet.** There is no login rate limiting; keep the panel on a private network.
- **Workers run on Linux or WSL2.** macOS and native Windows workers are untested.
- **Subscriptions.** Running Claude Code / Codex through your own subscription for your own work is how this was
  built; check your provider's terms for anything beyond that.
- **UI languages:** English and Russian (some server-generated details are still Russian only).

## Development

```bash
scripts/dev/dev-db.sh          # Postgres and Qdrant for development
scripts/predeploy-check.sh     # lint and every test suite, incl. user scenarios with a real (mock-engine) worker
```

Tests never call paid models. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
