from alembic import op
import sqlalchemy as sa

revision = "0002_accounts_mcp"
down_revision = "0001_control"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_profiles",
        sa.Column("id", sa.String(63), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("config_dir", sa.Text),
        sa.Column("base_url", sa.Text),
        sa.Column("secret_ref", sa.Text),
        sa.Column("secret_fingerprint", sa.String(64)),
        sa.Column("default_model", sa.String(255)),
        sa.Column("models", sa.JSON, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("status_detail", sa.Text),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        schema="control",
    )
    op.create_index("ix_control_account_profiles_worker_id", "account_profiles", ["worker_id"], schema="control")


def downgrade():
    op.drop_index("ix_control_account_profiles_worker_id", table_name="account_profiles", schema="control")
    op.drop_table("account_profiles", schema="control")
