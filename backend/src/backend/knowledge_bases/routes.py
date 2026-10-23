from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user
from backend.auth.sessions import require_trusted_origin
from backend.database import get_db_session
from backend.knowledge_bases import service
from backend.knowledge_bases.schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from backend.models import User


def prevent_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/workspaces/{workspace_id}/knowledge-bases",
    tags=["Knowledge bases"],
    dependencies=[Depends(prevent_caching)],
)
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "",
    status_code=201,
    response_model=KnowledgeBaseResponse,
    dependencies=[Depends(require_trusted_origin)],
)
def create_knowledge_base(
    workspace_id: UUID,
    payload: KnowledgeBaseCreate,
    db: DatabaseSession,
    user: CurrentUser,
) -> KnowledgeBaseResponse:
    knowledge_base = service.create_knowledge_base(db, user, workspace_id, payload)
    result = KnowledgeBaseResponse.model_validate(knowledge_base)
    db.commit()
    return result


@router.get("", response_model=KnowledgeBaseListResponse)
def list_knowledge_bases(
    workspace_id: UUID,
    db: DatabaseSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KnowledgeBaseListResponse:
    return service.list_knowledge_bases(
        db, user, workspace_id, limit=limit, offset=offset
    )


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
def get_knowledge_base(
    workspace_id: UUID, knowledge_base_id: UUID, db: DatabaseSession, user: CurrentUser
) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse.model_validate(
        service.get_knowledge_base(db, user, workspace_id, knowledge_base_id)
    )


@router.patch(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
    dependencies=[Depends(require_trusted_origin)],
)
def rename_knowledge_base(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    payload: KnowledgeBaseUpdate,
    db: DatabaseSession,
    user: CurrentUser,
) -> KnowledgeBaseResponse:
    knowledge_base = service.rename_knowledge_base(
        db, user, workspace_id, knowledge_base_id, payload
    )
    result = KnowledgeBaseResponse.model_validate(knowledge_base)
    db.commit()
    return result
