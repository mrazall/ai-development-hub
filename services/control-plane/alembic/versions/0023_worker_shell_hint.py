"""How to open a terminal on a worker, as the worker reports it (shown in CLI sign-in instructions)."""
from alembic import op
import sqlalchemy as sa

revision = "0023_worker_shell_hint"
down_revision = "0022_session_acknowledged"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("worker_capabilities", sa.Column("shell_hint", sa.Text()), schema="control")


def downgrade() -> None:
    op.drop_column("worker_capabilities", "shell_hint", schema="control")
