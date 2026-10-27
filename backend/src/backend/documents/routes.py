"""Authenticated document upload-intent routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user
from backend.auth.sessions import require_trusted_origin
from backend.database import get_db_session
from backend.documents import service
from backend.documents.schemas import (
    DocumentUploadIntentCreate,
    DocumentUploadIntentResponse,
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
