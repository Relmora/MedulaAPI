"""Owner-scoped document upload-intent persistence operations."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.documents.schemas import DocumentUploadIntentCreate
from backend.errors import AppError
from backend.knowledge_bases.service import get_knowledge_base
from backend.models import Document, User

DEFAULT_UPLOAD_TTL = timedelta(minutes=15)


def create_pending_document(
    db: Session,
    user: User,
    workspace_id: UUID,
    knowledge_base_id: UUID,
    payload: DocumentUploadIntentCreate,
    *,
    now: datetime | None = None,
    upload_ttl: timedelta = DEFAULT_UPLOAD_TTL,
) -> Document:
    
    """Reserve a private object key after proving knowledge-base ownership."""

    get_knowledge_base(db, user, workspace_id, knowledge_base_id)
    if upload_ttl <= timedelta(0):
        raise ValueError("upload_ttl must be positive")

    created_at = now or datetime.now(UTC)
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    document_id = uuid4()
    document = Document(
        id=document_id,
        knowledge_base_id=knowledge_base_id,
        uploaded_by_user_id=user.id,
        original_filename=payload.original_filename,
        declared_content_type=payload.declared_content_type,
        declared_size_bytes=payload.declared_size_bytes,
        gcs_object_key=f"documents/{document_id}/original",
        upload_status="PENDING",
        processing_status="NOT_QUEUED",
        upload_expires_at=created_at + upload_ttl,
    )
    db.add(document)
    db.flush()
    db.refresh(document)
    return document


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
