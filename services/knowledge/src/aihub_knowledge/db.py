from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, create_engine, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__: ClassVar = {"schema": "knowledge"}
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    title: Mapped[str] = mapped_column(String(512))
    visibility: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(64), default="note")
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DocumentLinkRow(Base):
    __tablename__ = "document_links"
    __table_args__: ClassVar = {"schema": "knowledge"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_document_id: Mapped[str] = mapped_column(String(255), index=True)
    target_document_id: Mapped[str | None] = mapped_column(String(255), index=True)
    target_ref: Mapped[str] = mapped_column(String(1024))
    target_title: Mapped[str] = mapped_column(String(512))
    target_path: Mapped[str | None] = mapped_column(String(1024))
    embedded: Mapped[bool] = mapped_column(Boolean, default=False)
    link_type: Mapped[str] = mapped_column(String(16), default="wiki")


class ChunkRow(Base):
    __tablename__ = "chunks"
    __table_args__: ClassVar = {"schema": "knowledge"}
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(255), index=True)
    heading: Mapped[str | None] = mapped_column(String(512))
    heading_path: Mapped[str] = mapped_column(String(1024), default="")
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    embedding_model: Mapped[str] = mapped_column(String(255))
    embedding_version: Mapped[str] = mapped_column(String(64))
    fts_russian: Mapped[object] = mapped_column(TSVECTOR, nullable=True)
    fts_english: Mapped[object] = mapped_column(TSVECTOR, nullable=True)
    fts_simple: Mapped[object] = mapped_column(TSVECTOR, nullable=True)


Index("ix_knowledge_chunks_fts_russian", ChunkRow.fts_russian, postgresql_using="gin")
Index("ix_knowledge_chunks_fts_english", ChunkRow.fts_english, postgresql_using="gin")
Index("ix_knowledge_chunks_fts_simple", ChunkRow.fts_simple, postgresql_using="gin")


class IndexJobRow(Base):
    __tablename__ = "index_jobs"
    __table_args__: ClassVar = {"schema": "knowledge"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    path: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IndexErrorRow(Base):
    __tablename__ = "index_errors"
    __table_args__: ClassVar = {"schema": "knowledge"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(1024))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def make_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


def create_schema(engine: Any) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS knowledge"))
    Base.metadata.create_all(engine)


def session_factory(engine: Any):
    return sessionmaker(bind=engine, expire_on_commit=False)
