# Deployment

## Local or a single server

```bash
./scripts/quickstart.sh            # hub on http://127.0.0.1:58080, data in Docker volumes, secrets in .aihub/
```

Keep it on `127.0.0.1` and reach it over a private network (Tailscale `serve`, WireGuard, an SSH tunnel). The
hub has passwords and short-lived tokens, but it is not hardened for the open internet.

Point it at your vault and real embeddings:

```bash
AIHUB_VAULT_HOST_DIR=/path/to/vault ./scripts/quickstart.sh
# embeddings: run Ollama with an embedding model and set AIHUB_EMBED_BACKEND=ollama, AIHUB_OLLAMA_URL
```

Set **Settings → System → Hub address** to the URL your workers use.

## A home server behind Tailscale

`deploy/home-server/` is a template for one Linux box that runs the stack and publishes the panel to your
tailnet only:

1. Start Tailscale in a container (`deploy/home-server/tailscale/docker-compose.yml`), `tailscale up`, then
   `tailscale serve --bg 127.0.0.1:8000`. Never `funnel` — that would put the hub on the internet.
2. Build the panel (`cd apps/web && npm ci && npm run build`) and run
   `AIHUB_VAULT_HOST_DIR=/path/to/vault AIHUB_PUBLIC_URL=https://hub.<tailnet>.ts.net deploy/home-server/install.sh .`
   It creates secrets (0600, never printed), starts the stack and writes the first admin password to a file.
3. Before each release, `scripts/predeploy-check.sh` runs lint, every test suite and the user-scenario tests.

## Backups and upgrades

- `infra/backup/aihub-backup.sh` — restic snapshots of the database (and optionally the vault);
  **System health → Backups** warns when they get stale.
- Upgrades: pull, then `docker compose … up -d --build`; database migrations run automatically
  (`migrate-control`, `migrate-knowledge`).
