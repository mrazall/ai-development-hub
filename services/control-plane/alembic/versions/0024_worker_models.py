"""Models a worker's CLIs offer (Codex reports its own list with effort levels), for the session form."""
from alembic import op
import sqlalchemy as sa

revision = "0024_worker_models"
down_revision = "0023_worker_shell_hint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("worker_capabilities", sa.Column("models", sa.JSON()), schema="control")


def downgrade() -> None:
    op.drop_column("worker_capabilities", "models", schema="control")
