"""Directed graph edges between canonical entities."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class EntityRelationship(Base):
    """One deduplicated directed edge and its first source chunk."""

    __tablename__ = "entity_relationships"
    __table_args__ = (
        CheckConstraint(
            "length(predicate) > 0",
            name="ck_entity_relationships_predicate_nonempty",
        ),
        CheckConstraint(
            "subject_entity_id <> object_entity_id",
            name="ck_entity_relationships_distinct_endpoints",
        ),
        ForeignKeyConstraint(
            ["subject_entity_id", "knowledge_base_id"],
            ["entities.id", "entities.knowledge_base_id"],
            ondelete="CASCADE",
            name="fk_entity_relationships_subject_tenant",
        ),
        ForeignKeyConstraint(
            ["object_entity_id", "knowledge_base_id"],
            ["entities.id", "entities.knowledge_base_id"],
            ondelete="CASCADE",
            name="fk_entity_relationships_object_tenant",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "subject_entity_id",
            "predicate",
            "object_entity_id",
            name="uq_entity_relationships_edge",
        ),
        Index(
            "ix_entity_relationships_knowledge_base",
            "knowledge_base_id",
        ),
        Index("ix_entity_relationships_subject", "subject_entity_id"),
        Index("ix_entity_relationships_object", "object_entity_id"),
        Index(
            "ix_entity_relationships_document_chunk",
            "document_id",
            "chunk_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE")
    )
    subject_entity_id: Mapped[UUID]
    predicate: Mapped[str] = mapped_column(String(64))
    object_entity_id: Mapped[UUID]
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    chunk_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
