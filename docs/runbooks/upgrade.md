# Upgrade

1. Review the release notes and create a rollback point (database dump plus Git
   revision) before changing images.
2. Fetch the approved revision and review `infra/.env` locally.
3. Validate without starting services:

   ```bash
   docker compose -f infra/docker-compose.yml config
   ```

4. Rebuild and apply migrations, then verify both health endpoints:

   ```bash
   docker compose -f infra/docker-compose.yml pull postgres qdrant
   docker compose -f infra/docker-compose.yml up -d --build
   docker compose -f infra/docker-compose.yml ps
   curl --fail http://127.0.0.1:58080/api/v0/health
   curl --fail http://127.0.0.1:58081/health
   ```

Keep the named volumes. Do not use `down -v` during an upgrade.
