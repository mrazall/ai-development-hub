"""knowledge documents and chunks"""

import sqlalchemy as sa
from alembic import op

revision = "0001_knowledge"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    op.create_table(
        "documents",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("project_id", sa.String(255)),
        sa.Column("path", sa.String(1024), unique=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("visibility", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fts_russian", sa.dialects.postgresql.TSVECTOR),
        sa.Column("fts_english", sa.dialects.postgresql.TSVECTOR),
        sa.Column("fts_simple", sa.dialects.postgresql.TSVECTOR),
        schema="knowledge",
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("doc_id", sa.String(255), nullable=False),
        sa.Column("heading", sa.String(512)),
        sa.Column("heading_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("line_start", sa.Integer, nullable=False),
        sa.Column("line_end", sa.Integer, nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        schema="knowledge",
    )
    op.create_table(
        "index_errors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="knowledge",
    )
    op.create_table(
        "index_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("path", sa.String(1024)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        schema="knowledge",
    )
    for name in ("russian", "english", "simple"):
        op.execute(f"CREATE INDEX ix_knowledge_documents_fts_{name} ON knowledge.documents USING gin(fts_{name})")
    op.execute("""CREATE OR REPLACE FUNCTION knowledge.documents_fts_update() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN NEW.fts_russian := to_tsvector('russian', coalesce(NEW.title,'') || ' ' || coalesce(NEW.content,''));
      NEW.fts_english := to_tsvector('english', coalesce(NEW.title,'') || ' ' || coalesce(NEW.content,''));
      NEW.fts_simple := to_tsvector('simple', coalesce(NEW.title,'') || ' ' || coalesce(NEW.content,'')); RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER documents_fts_trigger BEFORE INSERT OR UPDATE ON knowledge.documents FOR EACH ROW EXECUTE FUNCTION knowledge.documents_fts_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS documents_fts_trigger ON knowledge.documents")
    op.execute("DROP FUNCTION IF EXISTS knowledge.documents_fts_update()")
    op.drop_table("index_jobs", schema="knowledge")
    op.drop_table("index_errors", schema="knowledge")
    op.drop_table("chunks", schema="knowledge")
    op.drop_table("documents", schema="knowledge")
