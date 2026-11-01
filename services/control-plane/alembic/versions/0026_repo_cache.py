"""Cache repository data returned by workers."""
from alembic import op
import sqlalchemy as sa

revision = "0026_repo_cache"
down_revision = "0025_execution_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "repo_cache",
        sa.Column("project_id", sa.String(63), sa.ForeignKey("control.projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(48), primary_key=True),
        sa.Column("worker_id", sa.String(128)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        schema="control",
    )


def downgrade():
    op.drop_table("repo_cache", schema="control")
