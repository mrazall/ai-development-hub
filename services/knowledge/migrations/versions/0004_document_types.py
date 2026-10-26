"""Keep document and graph relationship types available to API consumers."""

import sqlalchemy as sa
from alembic import op

revision = "0004_document_types"
down_revision = "0003_graph_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("type", sa.String(64), nullable=False, server_default="note"), schema="knowledge")
    op.add_column("document_links", sa.Column("link_type", sa.String(16), nullable=False, server_default="wiki"), schema="knowledge")


def downgrade() -> None:
    op.drop_column("document_links", "link_type", schema="knowledge")
    op.drop_column("documents", "type", schema="knowledge")
