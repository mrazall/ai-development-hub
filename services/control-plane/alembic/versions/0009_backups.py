"""Backup snapshot reports."""

import sqlalchemy as sa
from alembic import op

revision = "0009_backups"
down_revision = "0008_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_snapshots",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("repo", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("error", sa.Text),
        sa.Column("tags", sa.JSON, nullable=False),
        schema="control",
    )
    op.create_index("ix_control_backup_snapshots_kind", "backup_snapshots", ["kind"], schema="control")


def downgrade() -> None:
    op.drop_table("backup_snapshots", schema="control")
