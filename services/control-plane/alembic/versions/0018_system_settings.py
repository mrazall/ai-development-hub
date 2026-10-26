"""Settings the admin changes in the panel (they override the deployment env)."""
from alembic import op
import sqlalchemy as sa

revision = "0018_system_settings"
down_revision = "0017_session_resume_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON()),
        sa.Column("updated_by", sa.String(128)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="control",
    )


def downgrade() -> None:
    op.drop_table("system_settings", schema="control")
