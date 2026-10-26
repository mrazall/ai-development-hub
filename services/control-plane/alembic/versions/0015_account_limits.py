"""Store the latest official CLI account limit windows."""
from alembic import op
import sqlalchemy as sa

revision = "0015_account_limits"
down_revision = "0014_personal_chats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_limits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(63), sa.ForeignKey("control.account_profiles.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("used_percent", sa.Float, nullable=False),
        sa.Column("resets_at", sa.BigInteger),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32)),
        schema="control",
    )
    op.create_unique_constraint("account_limits_account_kind_uq", "account_limits", ["account_id", "kind"], schema="control")
    op.create_index("ix_account_limits_account_id", "account_limits", ["account_id"], schema="control")


def downgrade() -> None:
    op.drop_index("ix_account_limits_account_id", table_name="account_limits", schema="control")
    op.drop_table("account_limits", schema="control")
