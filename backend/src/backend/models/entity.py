"""Canonical knowledge-graph entities resolved across document chunks."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class Entity(Base):
    """One canonical graph node within a knowledge base."""

    __tablename__ = "entities"
    __table_args__ = (
        CheckConstraint("length(name) > 0", name="ck_entities_name_nonempty"),
        CheckConstraint(
            "length(normalized_name) > 0",
            name="ck_entities_normalized_name_nonempty",
        ),
        CheckConstraint(
            "length(entity_type) > 0",
            name="ck_entities_type_nonempty",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "entity_type",
            "normalized_name",
            name="uq_entities_identity",
        ),
        UniqueConstraint(
            "id",
            "knowledge_base_id",
            name="uq_entities_id_knowledge_base",
        ),
        Index("ix_entities_knowledge_base_id", "knowledge_base_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
