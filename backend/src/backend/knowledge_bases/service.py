"""Owner-scoped operations; callers authenticate the user and commit writes."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.errors import AppError
from backend.knowledge_bases.schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from backend.models import KnowledgeBase, User
from backend.workspaces.service import get_workspace


def create_knowledge_base(
    db: Session, user: User, workspace_id: UUID, payload: KnowledgeBaseCreate
) -> KnowledgeBase:
    get_workspace(db, user, workspace_id)
    knowledge_base = KnowledgeBase(name=payload.name, workspace_id=workspace_id)
    db.add(knowledge_base)
    db.flush()
    db.refresh(knowledge_base)
    return knowledge_base


def get_knowledge_base(
    db: Session, user: User, workspace_id: UUID, knowledge_base_id: UUID
) -> KnowledgeBase:
    get_workspace(db, user, workspace_id)
    knowledge_base = db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.workspace_id == workspace_id,
        )
    )
    if knowledge_base is None:
        raise AppError("KNOWLEDGE_BASE_NOT_FOUND", "Knowledge base not found.", 404)
    return knowledge_base


def list_knowledge_bases(
    db: Session, user: User, workspace_id: UUID, *, limit: int = 20, offset: int = 0
) -> KnowledgeBaseListResponse:
    if not 1 <= limit <= 100 or offset < 0:
        raise AppError("INVALID_PAGINATION", "Invalid pagination parameters.", 422)
    get_workspace(db, user, workspace_id)
    owner_filter = KnowledgeBase.workspace_id == workspace_id
    total = db.scalar(
        select(func.count()).select_from(KnowledgeBase).where(owner_filter)
    )
    items = db.scalars(
        select(KnowledgeBase)
        .where(owner_filter)
        .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return KnowledgeBaseListResponse(
        items=[KnowledgeBaseResponse.model_validate(item) for item in items],
        limit=limit,
        offset=offset,
        total=total,
    )


def rename_knowledge_base(
    db: Session,
    user: User,
    workspace_id: UUID,
    knowledge_base_id: UUID,
    payload: KnowledgeBaseUpdate,
) -> KnowledgeBase:
    knowledge_base = get_knowledge_base(db, user, workspace_id, knowledge_base_id)
    knowledge_base.name = payload.name
    db.flush()
    db.refresh(knowledge_base)
    return knowledge_base
