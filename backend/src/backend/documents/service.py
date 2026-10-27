"""Owner-scoped document upload-intent operations."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.documents.schemas import DocumentUploadIntentCreate
from backend.errors import AppError
from backend.knowledge_bases.service import get_knowledge_base
from backend.models import Document, User
from backend.object_storage import ObjectStorage, UploadInstructions

DEFAULT_UPLOAD_TTL = timedelta(minutes=15)


@dataclass(frozen=True)
class PendingDocumentUpload:
    document: Document
    upload: UploadInstructions


def create_pending_document(
    db: Session,
    user: User,
    workspace_id: UUID,
    knowledge_base_id: UUID,
    payload: DocumentUploadIntentCreate,
    *,
    storage: ObjectStorage,
    now: datetime | None = None,
    upload_ttl: timedelta = DEFAULT_UPLOAD_TTL,
) -> PendingDocumentUpload:
    """Reserve a private object key after proving knowledge-base ownership."""

    get_knowledge_base(db, user, workspace_id, knowledge_base_id)
    if upload_ttl <= timedelta(0):
        raise ValueError("upload_ttl must be positive")

    created_at = now or datetime.now(UTC)
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not storage.provider.strip() or not storage.bucket.strip():
        raise ValueError("storage provider and bucket must be nonempty")

    document_id = uuid4()
    object_key = f"documents/{document_id}/original"
    expires_at = created_at + upload_ttl
    document = Document(
        id=document_id,
        knowledge_base_id=knowledge_base_id,
        uploaded_by_user_id=user.id,
        original_filename=payload.original_filename,
        declared_content_type=payload.declared_content_type,
        declared_size_bytes=payload.declared_size_bytes,
        storage_provider=storage.provider,
        storage_bucket=storage.bucket,
        storage_object_key=object_key,
        upload_status="PENDING",
        processing_status="NOT_QUEUED",
        upload_expires_at=expires_at,
    )
    db.add(document)
    db.flush()
    db.refresh(document)
    upload = storage.create_upload_grant(
        object_key=object_key,
        content_type=payload.declared_content_type,
        size_bytes=payload.declared_size_bytes,
        expires_at=expires_at,
    )
    return PendingDocumentUpload(document=document, upload=upload)


def get_document(
    db: Session,
    user: User,
    workspace_id: UUID,
    knowledge_base_id: UUID,
    document_id: UUID,
) -> Document:
    """Return a document only through its user-owned workspace hierarchy."""
    get_knowledge_base(db, user, workspace_id, knowledge_base_id)
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.knowledge_base_id == knowledge_base_id,
        )
    )
    if document is None:
        raise AppError("DOCUMENT_NOT_FOUND", "Document not found.", 404)
    return document


def complete_document_upload(
    db: Session,
    user: User,
    workspace_id: UUID,
    knowledge_base_id: UUID,
    document_id: UUID,
    *,
    storage: ObjectStorage,
    now: datetime | None = None,
) -> Document:
    """Verify the private object and mark its upload as stored."""

    document = get_document(db, user, workspace_id, knowledge_base_id, document_id)
    if document.upload_status == "STORED":
        return document
    if document.upload_status != "PENDING":
        raise AppError(
            "DOCUMENT_UPLOAD_STATE",
            "Document is not awaiting an upload.",
            409,
        )
    if (
        document.storage_provider != storage.provider
        or document.storage_bucket != storage.bucket
    ):
        raise AppError(
            "STORAGE_CONFIGURATION_MISMATCH",
            "Document storage is temporarily unavailable.",
            503,
        )

    completed_at = now or datetime.now(UTC)
    if completed_at.tzinfo is None or completed_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    try:
        metadata = storage.get_object_metadata(document.storage_object_key)
    except FileNotFoundError as exc:
        raise AppError(
            "DOCUMENT_UPLOAD_INCOMPLETE",
            "Uploaded object was not found.",
            409,
        ) from exc

    if (
        metadata.size_bytes != document.declared_size_bytes
        or metadata.content_type != document.declared_content_type
    ):
        raise AppError(
            "DOCUMENT_UPLOAD_MISMATCH",
            "Uploaded object does not match the upload intent.",
            409,
        )

    document.stored_size_bytes = metadata.size_bytes
    document.storage_version = metadata.version
    document.storage_checksum = metadata.checksum
    document.storage_checksum_algorithm = metadata.checksum_algorithm
    document.upload_status = "STORED"
    document.uploaded_at = completed_at
    document.failure_code = None
    db.flush()
    db.refresh(document)
    return document
