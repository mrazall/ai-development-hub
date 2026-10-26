# Rollback

Rollback requires an approved prior Git revision and a tested PostgreSQL dump. Stop
the application services, restore the revision, and start with the existing named
volumes:

```bash
docker compose -f infra/docker-compose.yml stop control-plane knowledge
git checkout <approved-known-good-revision>
docker compose -f infra/docker-compose.yml config
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml ps
```

If a migration is not backward-compatible, stop and use the documented restore
procedure in the Stage 5 backup plan. Never delete volumes as a rollback shortcut;
escalate if a database restore is needed.
