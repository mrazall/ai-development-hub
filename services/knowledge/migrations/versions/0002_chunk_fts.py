"""Keep full-text ranks at chunk granularity."""

import sqlalchemy as sa
from alembic import op

revision = "0002_chunk_fts"
down_revision = "0001_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("russian", "english", "simple"):
        op.execute(f"DROP INDEX IF EXISTS ix_knowledge_documents_fts_{name}")
    op.execute("DROP TRIGGER IF EXISTS documents_fts_trigger ON knowledge.documents")
    op.execute("DROP FUNCTION IF EXISTS knowledge.documents_fts_update()")
    for name in ("russian", "english", "simple"):
        op.add_column("chunks", sa.Column(f"fts_{name}", sa.dialects.postgresql.TSVECTOR), schema="knowledge")
    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.chunks_fts_update() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          NEW.fts_russian := to_tsvector('russian', coalesce(NEW.heading,'') || ' ' || coalesce(NEW.content,''));
          NEW.fts_english := to_tsvector('english', coalesce(NEW.heading,'') || ' ' || coalesce(NEW.content,''));
          NEW.fts_simple := to_tsvector('simple', coalesce(NEW.heading,'') || ' ' || coalesce(NEW.content,''));
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER chunks_fts_trigger BEFORE INSERT OR UPDATE ON knowledge.chunks
        FOR EACH ROW EXECUTE FUNCTION knowledge.chunks_fts_update()
    """)
    for name in ("russian", "english", "simple"):
        op.execute(f"CREATE INDEX ix_knowledge_chunks_fts_{name} ON knowledge.chunks USING gin(fts_{name})")
    op.execute(
        "ALTER TABLE knowledge.documents DROP COLUMN fts_russian, DROP COLUMN fts_english, DROP COLUMN fts_simple"
    )


def downgrade() -> None:
    op.add_column("documents", sa.Column("fts_russian", sa.dialects.postgresql.TSVECTOR), schema="knowledge")
    op.add_column("documents", sa.Column("fts_english", sa.dialects.postgresql.TSVECTOR), schema="knowledge")
    op.add_column("documents", sa.Column("fts_simple", sa.dialects.postgresql.TSVECTOR), schema="knowledge")
    op.execute("DROP TRIGGER IF EXISTS chunks_fts_trigger ON knowledge.chunks")
    op.execute("DROP FUNCTION IF EXISTS knowledge.chunks_fts_update()")
    for name in ("russian", "english", "simple"):
        op.execute(f"DROP INDEX IF EXISTS ix_knowledge_chunks_fts_{name}")
    op.drop_column("chunks", "fts_russian", schema="knowledge")
    op.drop_column("chunks", "fts_english", schema="knowledge")
    op.drop_column("chunks", "fts_simple", schema="knowledge")
    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.documents_fts_update() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          NEW.fts_russian := to_tsvector('russian', coalesce(NEW.title,'') || ' ' || coalesce(NEW.content,''));
          NEW.fts_english := to_tsvector('english', coalesce(NEW.title,'') || ' ' || coalesce(NEW.content,''));
          NEW.fts_simple := to_tsvector('simple', coalesce(NEW.title,'') || ' ' || coalesce(NEW.content,''));
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER documents_fts_trigger BEFORE INSERT OR UPDATE ON knowledge.documents
        FOR EACH ROW EXECUTE FUNCTION knowledge.documents_fts_update()
    """)
    for name in ("russian", "english", "simple"):
        op.execute(f"CREATE INDEX ix_knowledge_documents_fts_{name} ON knowledge.documents USING gin(fts_{name})")
