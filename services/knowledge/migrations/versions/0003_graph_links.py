"""Store links between indexed documents, including unresolved targets."""

import sqlalchemy as sa
from alembic import op

revision = "0003_graph_links"
down_revision = "0002_chunk_fts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_links",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source_document_id", sa.String(255), nullable=False, index=True),
        sa.Column("target_document_id", sa.String(255), nullable=True, index=True),
        sa.Column("target_ref", sa.String(1024), nullable=False),
        sa.Column("target_title", sa.String(512), nullable=False),
        sa.Column("target_path", sa.String(1024), nullable=True),
        sa.Column("embedded", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_table("document_links", schema="knowledge")
