# Configuration

Configuration comes from environment variables (prefix `AIHUB_`) set at deployment. Some settings can also be
changed in the panel (**Settings → System**); a value saved there overrides the environment until you reset it.

## Hub (control plane)

| Variable | Default | Panel | Meaning |
|---|---|:-:|---|
| `AIHUB_DATABASE_URL`, `AIHUB_DB_PASSWORD_FILE` | — | | Postgres |
| `AIHUB_SECRET_KEY_FILE`, `AIHUB_INTERNAL_SECRET_FILE` | — | | signing keys (created by `infra/scripts/init-secrets.sh`) |
| `AIHUB_PUBLIC_URL` | `http://127.0.0.1:8000` | ✓ | address workers and agents use to reach the hub |
| `AIHUB_KNOWLEDGE_URL` | `http://knowledge:8000` | | knowledge service |
| `AIHUB_WEB_DIR` | `/app/web` | | built panel |
| `AIHUB_FRAME_SRC` | empty | | CSP `frame-src` for embedded Codeman terminals |
| `AIHUB_WORKER_SHELL_HINT` | empty | ✓ | how to open a shell on a worker (shown in login instructions) |
| `AIHUB_CHAT_ENGINE` | `claude_code` | ✓ | engine of personal chats (`mock_echo_prompt` for demos) |
| `AIHUB_CHAT_SYSTEM_PROMPT` | built-in | ✓ | system prompt appended to chats |
| `AIHUB_VAULT_WORKER_ID`, `AIHUB_VAULT_WORKDIR`, `AIHUB_VAULT_MODEL` | empty, empty, `claude-sonnet-5-5` | ✓ | where *Apply draft* runs: worker, vault git checkout on it, model |
| `AIHUB_OBSIDIAN_VAULT` | empty | ✓ | vault name for "Open in Obsidian" links (empty hides the button) |
| `AIHUB_HEALTH_INTERVAL_S` | 60 | ✓ | health checks and failure notifications (0 = off) |
| `AIHUB_TAILSCALE_SOCKET` | empty | | tailscaled LocalAPI socket (mounted read-only) for the health page |
| `AIHUB_CLAUDE_CONTEXT_LIMIT` | 250000 | | context meter of chats |
| `AIHUB_ACCESS_TOKEN_TTL_S` | 3600 | | lifetime of user and agent tokens (workers renew agent tokens) |
| `AIHUB_DEMO` | `0` | | demo deployment: mock engines in the panel, banner |

## Knowledge service

| Variable | Default | Meaning |
|---|---|---|
| `AIHUB_VAULT_DIR` | — | the vault inside the container (compose mounts `AIHUB_VAULT_HOST_DIR` there read-only) |
| `AIHUB_VAULT_ID_PREFIX` | `vault` | id prefix of notes without frontmatter — keep it stable, ids are referenced |
| `AIHUB_EMBED_BACKEND` | `fake` | `ollama` for real embeddings |
| `AIHUB_OLLAMA_URL`, `AIHUB_EMBEDDING_MODEL` | `…:11434`, `qwen3-embedding:0.6b` | embeddings |
| `AIHUB_EMBEDDING_RATE_PER_SECOND` | 0 (unlimited) | throttle indexing on small hosts |
| `AIHUB_QDRANT_URL` | `http://qdrant:6333` | vectors |

## Compose files

- `infra/docker-compose.yml` — the stack.
- `infra/docker-compose.quickstart.yml` — one image with the panel, no database ports, optional demo worker.
- `deploy/home-server/` — a production template (one Linux box behind Tailscale): compose override, install
  script, Tailscale in a container. Copy and adapt it.
