# AI Hub backup and restore test

The scheduled backup is intentionally isolated in the `restic-aihub` repository. It
creates a custom-format PostgreSQL dump through the local Docker Compose PostgreSQL
service and stores an allowlisted configuration snapshot. It does not copy secrets,
the Qdrant volume, Vault, existing restic repositories, or existing cron jobs.

On the deployment host, create the repository password and API token as files with
mode `0600`. The scripts default to `~/ai-dev-hub/secrets/restic-aihub-password` and
`~/ai-dev-hub/secrets/backup-api-token`; override paths with environment variables.

Run `infra/backup/aihub-backup.sh` from the repository root. Set
`AIHUB_RESTIC_CHECK=1` for an integrity check after pruning. Vault is already backed
up by the homelab; set `AIHUB_BACKUP_INCLUDE_VAULT=1` (with `AIHUB_VAULT_HOST_DIR`)
only when an independent copy is explicitly required. The repository defaults to
`/srv/media2/restic-aihub` (`AIHUB_RESTIC_REPOSITORY`). Each run reports one row per
kind to the Backups page: `database`, `config` and, when included, `vault`.

Run `infra/backup/aihub-restore-test.sh` monthly. It restores the newest restic
snapshot into the temporary database `aihub_restore_test`, counts rows in the
`control` schema, and reports `kind=restore_test`. This database is disposable and
is never used as the production database.

Retention is 7 daily, 4 weekly, and 12 monthly snapshots. Database RPO is six hours;
the Backups API reports an exceeded RPO when the last successful database snapshot is
older than that or absent.
