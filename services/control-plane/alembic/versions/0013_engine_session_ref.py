"""Store Claude conversation references and prompt context usage."""

from alembic import op
import sqlalchemy as sa

revision = "0013_engine_session_ref"
down_revision = "0012_events_purge_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("engine_session_ref", sa.String(255)), schema="control")
    op.add_column("sessions", sa.Column("context_tokens", sa.Integer()), schema="control")
    op.add_column(
        "sessions",
        sa.Column("context_fresh", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="control",
    )
    op.alter_column("sessions", "context_fresh", server_default=None, schema="control")


def downgrade() -> None:
    op.drop_column("sessions", "context_fresh", schema="control")
    op.drop_column("sessions", "context_tokens", schema="control")
    op.drop_column("sessions", "engine_session_ref", schema="control")
