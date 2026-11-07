"""Authenticated document upload-intent routes."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user
from backend.auth.sessions import require_trusted_origin
from backend.database import get_db_session
from backend.documents import service
from backend.documents.schemas import (
    DocumentGraphResponse,
    DocumentProcessingStatus,
    DocumentUploadCompleteRequest,
    DocumentUploadCompleteResponse,
    DocumentUploadIntentCreate,
    DocumentUploadIntentResponse,
    GraphEdgeResponse,
    GraphNodeResponse,
    UploadInstructionsResponse,
)
from backend.models import User
from backend.object_storage.dependencies import get_object_storage
from backend.object_storage.interface import ObjectStorage


def prevent_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/documents",
    tags=["Documents"],
    dependencies=[Depends(prevent_caching)],
)
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
ConfiguredObjectStorage = Annotated[ObjectStorage, Depends(get_object_storage)]


@router.get("/{document_id}/graph", response_model=DocumentGraphResponse)
def get_document_graph(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    document_id: UUID,
    db: DatabaseSession,
    user: CurrentUser,
) -> DocumentGraphResponse:
    graph = service.get_document_graph(
        db,
        user,
        workspace_id,
        knowledge_base_id,
        document_id,
    )
    return DocumentGraphResponse(
        document_id=graph.document_id,
        nodes=[
            GraphNodeResponse(
                id=node.id,
                name=node.name,
                entity_type=node.entity_type,
            )
            for node in graph.nodes
        ],
        edges=[
            GraphEdgeResponse(
                id=edge.id,
                source=edge.source,
                target=edge.target,
                predicate=edge.predicate,
                chunk_id=edge.chunk_id,
            )
            for edge in graph.edges
        ],
    )


@router.post(
    "/upload-intent",
    status_code=201,
    response_model=DocumentUploadIntentResponse,
    dependencies=[Depends(require_trusted_origin)],
)
def create_upload_intent(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    payload: DocumentUploadIntentCreate,
    db: DatabaseSession,
    user: CurrentUser,
    storage: ConfiguredObjectStorage,
) -> DocumentUploadIntentResponse:
    pending = service.create_pending_document(
        db,
        user,
        workspace_id,
        knowledge_base_id,
        payload,
        storage=storage,
    )
    result = DocumentUploadIntentResponse(
        document_id=pending.document.id,
        upload=UploadInstructionsResponse.model_validate(
            pending.upload, from_attributes=True
        ),
    )
    db.commit()
    return result


@router.post(
    "/{document_id}/complete",
    response_model=DocumentUploadCompleteResponse,
    dependencies=[Depends(require_trusted_origin)],
)
def complete_upload(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    document_id: UUID,
    payload: DocumentUploadCompleteRequest,
    db: DatabaseSession,
    user: CurrentUser,
    storage: ConfiguredObjectStorage,
) -> DocumentUploadCompleteResponse:
    del payload
    completed = service.complete_document_upload(
        db,
        user,
        workspace_id,
        knowledge_base_id,
        document_id,
        storage=storage,
    )
    document = completed.document
    if document.stored_size_bytes is None or document.uploaded_at is None:
        raise RuntimeError("Completed upload is missing verified storage metadata.")
    if document.processing_status not in {
        "QUEUED",
        "PROCESSING",
        "READY",
        "REJECTED",
        "FAILED",
    }:
        raise RuntimeError("Completed upload has an invalid processing status.")

    result = DocumentUploadCompleteResponse(
        document_id=document.id,
        job_id=completed.job.id,
        upload_status="STORED",
        processing_status=cast(DocumentProcessingStatus, document.processing_status),
        stored_size_bytes=document.stored_size_bytes,
        storage_version=document.storage_version,
        storage_checksum=document.storage_checksum,
        storage_checksum_algorithm=document.storage_checksum_algorithm,
        uploaded_at=document.uploaded_at,
    )
    db.commit()
    return result
