"""Remember when a session stopped by a provider limit should continue."""
from alembic import op
import sqlalchemy as sa

revision = "0017_session_resume_at"
down_revision = "0016_orchestration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("resume_at", sa.DateTime(timezone=True)), schema="control")
    op.create_index("ix_sessions_resume_at", "sessions", ["resume_at"], schema="control")


def downgrade() -> None:
    op.drop_index("ix_sessions_resume_at", table_name="sessions", schema="control")
    op.drop_column("sessions", "resume_at", schema="control")
