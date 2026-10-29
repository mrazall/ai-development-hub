"""Account identity, login watch and worker-discovered logins."""
from alembic import op
import sqlalchemy as sa

revision = "0020_accounts_ux"
down_revision = "0019_session_permission_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("account_profiles", sa.Column("identity", sa.String(255)), schema="control")
    op.add_column("account_profiles", sa.Column("identity_checked_at", sa.DateTime(timezone=True)), schema="control")
    op.add_column("account_profiles", sa.Column("login_watch_until", sa.DateTime(timezone=True)), schema="control")
    op.add_column("workers", sa.Column("found_logins", sa.JSON(), nullable=False, server_default="[]"), schema="control")


def downgrade() -> None:
    op.drop_column("workers", "found_logins", schema="control")
    op.drop_column("account_profiles", "login_watch_until", schema="control")
    op.drop_column("account_profiles", "identity_checked_at", schema="control")
    op.drop_column("account_profiles", "identity", schema="control")
