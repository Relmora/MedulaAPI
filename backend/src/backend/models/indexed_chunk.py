"""Searchable chunk text and embeddings stored with pgvector."""

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base

EMBEDDING_DIMENSIONS = 768


class IndexedChunk(Base):
    """Current searchable projection of one embedded document chunk."""

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_chunk_embeddings_chunk_index_nonnegative",
        ),
        CheckConstraint(
            "length(chunk_text) > 0",
            name="ck_chunk_embeddings_text_nonempty",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_chunk_embeddings_content_hash_length",
        ),
        CheckConstraint(
            "embedding_dimensions = 768",
            name="ck_chunk_embeddings_dimensions",
        ),
        CheckConstraint(
            "length(embedding_config_hash) = 64",
            name="ck_chunk_embeddings_config_hash_length",
        ),
        UniqueConstraint(
            "document_id",
            "chunk_id",
            "embedding_config_hash",
            name="uq_chunk_embeddings_document_chunk_config",
        ),
        Index(
            "ix_chunk_embeddings_workspace_knowledge_base",
            "workspace_id",
            "knowledge_base_id",
        ),
        Index("ix_chunk_embeddings_document_id", "document_id"),
        Index(
            "ix_chunk_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE")
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    chunk_id: Mapped[UUID]
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding_provider: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(255))
    embedding_dimensions: Mapped[int] = mapped_column(Integer)
    embedding_config_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    source_object_key: Mapped[str] = mapped_column(String(1024))
    source_storage_version: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
