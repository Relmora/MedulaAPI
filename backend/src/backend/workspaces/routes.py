from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user
from backend.auth.sessions import require_trusted_origin
from backend.database import get_db_session
from backend.models import User
from backend.workspaces import service
from backend.workspaces.schemas import (
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
)


def prevent_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/workspaces", tags=["Workspaces"], dependencies=[Depends(prevent_caching)]
)
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "",
    status_code=201,
    response_model=WorkspaceResponse,
    dependencies=[Depends(require_trusted_origin)],
)
def create_workspace(
    payload: WorkspaceCreate, db: DatabaseSession, user: CurrentUser
) -> WorkspaceResponse:
    workspace = service.create_workspace(db, user, payload)
    result = WorkspaceResponse.model_validate(workspace)
    db.commit()
    return result


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(
    db: DatabaseSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkspaceListResponse:
    return service.list_workspaces(db, user, limit=limit, offset=offset)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: UUID, db: DatabaseSession, user: CurrentUser
) -> WorkspaceResponse:
    return WorkspaceResponse.model_validate(
        service.get_workspace(db, user, workspace_id)
    )


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    dependencies=[Depends(require_trusted_origin)],
)
def rename_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    db: DatabaseSession,
    user: CurrentUser,
) -> WorkspaceResponse:
    workspace = service.rename_workspace(db, user, workspace_id, payload)
    result = WorkspaceResponse.model_validate(workspace)
    db.commit()
    return result
