# Contributing

Thanks for looking. Issues and pull requests are welcome — small focused ones are reviewed fastest.

## Layout

| Path | What |
|---|---|
| `services/control-plane` | FastAPI hub: users, projects, sessions, events, orchestration, settings, health |
| `services/knowledge` | vault indexer and search (Postgres + Qdrant) |
| `packages/agent-adapters` | the worker: runs Claude Code / Codex / mock engines, terminals, git |
| `packages/mcp-knowledge` | MCP server agents use for knowledge and orchestration |
| `packages/contracts` | shared pydantic models |
| `apps/web` | React + Vite panel |
| `infra/`, `deploy/` | compose files, images, backups, a home-server template |

Architecture: [docs/architecture.md](docs/architecture.md).

## Running it while you work

```bash
./scripts/quickstart.sh --demo        # the whole thing in Docker, mock agents
```

For quicker loops, run the parts from your checkout against dev databases in Docker:

```bash
scripts/dev/dev-db.sh                                              # Postgres :55432, Qdrant :56333
AIHUB_DEV_VAULT=examples/demo-vault scripts/dev/dev-knowledge.sh   # :58181
scripts/dev/dev-panel.sh                                           # :58090, builds apps/web first
```

## Checks

Everything CI runs, locally:

```bash
scripts/predeploy-check.sh
```

It runs ruff and every Python test suite (integration tests need the dev Postgres; the user-scenario tests
start a real worker with the mock engines) and the web panel's prettier, lint and types. Browser tests:
`cd apps/web && npx playwright test` against a running dev panel.

Rules that keep the suite useful:

- **No paid models in tests.** Use the mock engines (`mock_echo_prompt`, `mock_write`, `mock_limit`).
- A user-visible change comes with a test of the scenario, not only of the function.
- Don't claim a check passed unless you ran it.

## Code style

- Python 3.12, ruff. Comments explain *why*; keep them short.
- TypeScript strict, prettier, eslint. Icons from `lucide-react` via `components/ui/icons.tsx`.
- **UI text** is written in Russian inside `t('…')` (the Russian string is the key) and gets an English line
  in `apps/web/src/i18n/en.ts`. A missing line falls back to Russian, so add it in the same PR.
- Database changes are new Alembic migrations; never edit an applied one.
- Line endings are LF (`.gitattributes`).

## Security

Never commit secrets, tokens, real hostnames or personal paths — in code, fixtures, logs or screenshots.
Report vulnerabilities privately, see [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contribution is licensed under the project's [LICENSE](LICENSE).
