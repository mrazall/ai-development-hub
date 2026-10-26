# Backup policy (Stage 5 scaffold)

The production target is an encrypted Restic repository on NAS plus an independent
off-site copy. This directory contains inventory and a safe `pg_dump` scaffold only;
it does not initialize a repository, contact NAS, or run a backup.

- Vault: hourly.
- Projects (including uncommitted and untracked files): every 4 hours.
- PostgreSQL dumps and session exports: at least every 6 hours.
- Configuration: daily.
- Retention: 7 daily, 4 weekly, 12 monthly snapshots.
- Never back up open secrets, `node_modules`, build caches, temporary containers, or
  the live PostgreSQL data directory by file copy.
- Run `restic check` on a schedule and perform a monthly restore into an isolated
  directory. Alert on missed or failed snapshots and RPO violations.

Before Stage 5, define repository credentials in an external secret store and test
both the NAS and off-site restore paths. Do not place `RESTIC_PASSWORD` or repository
URLs in this repository.
