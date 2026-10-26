# Architecture

## Parts

| Part | Where it runs | What it does |
|---|---|---|
| **Control plane** (`services/control-plane`, FastAPI) | hub (Docker) | users, projects, sessions, the append-only event log, orchestration API, notifications, health checks, serves the web panel |
| **Web panel** (`apps/web`, React + Vite) | browser | workspace, chats, knowledge, agents graph, settings |
| **Knowledge service** (`services/knowledge`) | hub (Docker) | indexes the Obsidian vault: chunks → Postgres full text + Qdrant vectors (Ollama embeddings or a fake backend), wiki-link graph, agent drafts |
| **Postgres, Qdrant** | hub (Docker) | storage |
| **Worker** (`packages/agent-adapters`, `aihub-worker`) | each machine with agent CLIs | polls the hub for assignments, runs engines, streams events back, executes workspace requests (files, git diff, merges), renews short-lived agent tokens |
| **MCP server** (`packages/mcp-knowledge`, `aihub-knowledge-mcp`) | started by the worker per session | gives agents the memory tools (`knowledge.search/read/write_draft`) and, for orchestrators, `orch_*` tools |

The hub never holds agent credentials. Each worker runs the CLIs under profiles that were logged in on that
machine (`CLAUDE_CONFIG_DIR` / `CODEX_HOME` per account profile).

## A session's life

1. The panel creates a session (status `queued`; `draft` while attachments upload).
2. The worker for that session claims it, prepares the working directory (a git worktree for executors),
   writes a per-session MCP config with a **scoped, short-lived token** and starts the engine.
3. Engine output is normalised into events (`message`, `tool.call`, `tool.result`, `diff`, `session.status`…)
   and posted in batches; the panel follows them over Server-Sent Events.
4. On exit the worker reports the final status. If the last answer was a provider limit, the hub schedules an
   **auto-resume** at the reset time.

## Orchestration

An orchestrator session (Claude) gets the `orch_*` MCP tools, scoped to itself:

- `orch_set_plan` — publish/update the plan shown in the panel;
- `orch_spawn_executor` — start a Codex executor on a new branch/worktree (up to N at a time);
- `orch_wait`, `orch_get_executor`, `orch_list_executors`, `orch_stop_executor`;
- `orch_request_merge` — in *manual merge* mode, ask the owner to merge a finished branch. The owner's
  *Accept* makes the worker run `git merge --no-ff` in the orchestration checkout (refused on a dirty tree,
  aborted on conflict); the decision is sent back to the orchestrator as a message.

## Memory

The vault is mounted **read-only** into the knowledge service, except `_Агенты/` where agents save drafts.
Drafts are kept out of search until the owner applies them: *Apply* starts a model session on the machine with
a git checkout of the vault (synced, e.g., with Syncthing), which merges the draft into the right notes and
commits; *Revert* runs `git revert` of that commit.

## Data and events

`control.agent_events` is append-only (deletes only through the purge job). Views ask for what they show:
`/events?view=chat|activity|events` drop engine bookkeeping on the server, and the live stream starts after the
loaded history.
