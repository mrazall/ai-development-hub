"""Device sessions: stay signed in until logout or 30 days without use."""
from alembic import op
import sqlalchemy as sa

revision = "0021_device_sessions"
down_revision = "0020_accounts_ux"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("control.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("previous_hash", sa.String(64)),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.String(255)),
        schema="control",
    )
    op.create_index("ix_control_device_sessions_user_id", "device_sessions", ["user_id"], schema="control")
    op.create_index(
        "ix_control_device_sessions_token_hash", "device_sessions", ["token_hash"], unique=True, schema="control"
    )
    op.create_index("ix_control_device_sessions_previous_hash", "device_sessions", ["previous_hash"], schema="control")


def downgrade() -> None:
    op.drop_table("device_sessions", schema="control")
