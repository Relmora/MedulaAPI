"""Document upload metadata; file bytes live in private object storage."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
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


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "length(original_filename) BETWEEN 1 AND 255",
            name="ck_documents_original_filename_length",
        ),
        CheckConstraint(
            "length(declared_content_type) BETWEEN 1 AND 127",
            name="ck_documents_declared_content_type_length",
        ),
        CheckConstraint(
            "declared_size_bytes > 0",
            name="ck_documents_declared_size_positive",
        ),
        CheckConstraint(
            "stored_size_bytes IS NULL OR stored_size_bytes > 0",
            name="ck_documents_stored_size_positive",
        ),
        CheckConstraint(
            "length(storage_provider) > 0",
            name="ck_documents_storage_provider_nonempty",
        ),
        CheckConstraint(
            "length(storage_bucket) > 0",
            name="ck_documents_storage_bucket_nonempty",
        ),
        CheckConstraint(
            "length(storage_object_key) > 0",
            name="ck_documents_storage_object_key_nonempty",
        ),
        CheckConstraint(
            "upload_status IN ('PENDING', 'STORED', 'EXPIRED', 'DELETED')",
            name="ck_documents_upload_status",
        ),
        CheckConstraint(
            "processing_status IN "
            "('NOT_QUEUED', 'QUEUED', 'PROCESSING', 'READY', "
            "'REJECTED', 'FAILED')",
            name="ck_documents_processing_status",
        ),
        Index(
            "ix_documents_upload_status_expires_at",
            "upload_status",
            "upload_expires_at",
        ),
        UniqueConstraint(
            "storage_provider",
            "storage_bucket",
            "storage_object_key",
            name="uq_documents_storage_location",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="RESTRICT"), index=True
    )
    uploaded_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    declared_content_type: Mapped[str] = mapped_column(String(127))
    detected_content_type: Mapped[str | None] = mapped_column(
        String(127), nullable=True
    )
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger)
    stored_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    storage_provider: Mapped[str] = mapped_column(String(32))
    storage_bucket: Mapped[str] = mapped_column(String(255))
    storage_object_key: Mapped[str] = mapped_column(String(1024))
    storage_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    storage_checksum_algorithm: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    parsed_storage_object_key: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    parsed_storage_version: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    upload_status: Mapped[str] = mapped_column(
        String(32), default="PENDING", server_default="PENDING"
    )
    processing_status: Mapped[str] = mapped_column(
        String(32), default="NOT_QUEUED", server_default="NOT_QUEUED"
    )
    upload_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
