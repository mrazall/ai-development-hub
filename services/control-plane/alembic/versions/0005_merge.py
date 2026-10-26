"""Merge the parallel accounts and orchestration branches. No schema changes."""

revision = "0005_merge"  # alembic_version is varchar(32)
down_revision = ("0002_accounts_mcp", "0003_orchestration")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
