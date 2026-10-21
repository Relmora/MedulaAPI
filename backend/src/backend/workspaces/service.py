"""Owner-scoped operations; callers authenticate the user and commit writes."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.errors import AppError
from backend.models import User, Workspace
from backend.workspaces.schemas import (
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
)


def create_workspace(db: Session, user: User, payload: WorkspaceCreate) -> Workspace:
    workspace = Workspace(name=payload.name, owner_user_id=user.id)
    db.add(workspace)
    db.flush()
    db.refresh(workspace)
    return workspace


def get_workspace(db: Session, user: User, workspace_id: UUID) -> Workspace:
    workspace = db.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id, Workspace.owner_user_id == user.id
        )
    )
    if workspace is None:
        raise AppError("WORKSPACE_NOT_FOUND", "Workspace not found.", 404)
    return workspace


def list_workspaces(
    db: Session, user: User, *, limit: int = 20, offset: int = 0
) -> WorkspaceListResponse:
    if not 1 <= limit <= 100 or offset < 0:
        raise AppError("INVALID_PAGINATION", "Invalid pagination parameters.", 422)
    owner_filter = Workspace.owner_user_id == user.id
    total = db.scalar(select(func.count()).select_from(Workspace).where(owner_filter))
    items = db.scalars(
        select(Workspace)
        .where(owner_filter)
        .order_by(Workspace.created_at.desc(), Workspace.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return WorkspaceListResponse(
        items=[WorkspaceResponse.model_validate(item) for item in items],
        limit=limit,
        offset=offset,
        total=total,
    )


def rename_workspace(
    db: Session, user: User, workspace_id: UUID, payload: WorkspaceUpdate
) -> Workspace:
    workspace = get_workspace(db, user, workspace_id)
    workspace.name = payload.name
    db.flush()
    db.refresh(workspace)
    return workspace
