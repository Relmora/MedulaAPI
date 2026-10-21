from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.errors import AppError
from backend.models import Base, User, Workspace
from backend.workspaces.schemas import WorkspaceCreate, WorkspaceUpdate
from backend.workspaces.service import (
    create_workspace,
    get_workspace,
    list_workspaces,
    rename_workspace,
)


@pytest.fixture
def workspace_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        alice = User(username="alice", password_hash="unused")
        bob = User(username="bob", password_hash="unused")
        db.add_all([alice, bob])
        db.commit()
        yield db, alice, bob
    engine.dispose()


def test_create_rename_persist_and_allow_duplicate_names(workspace_db):
    db, alice, _ = workspace_db
    first = create_workspace(db, alice, WorkspaceCreate(name=" Docs "))
    second = create_workspace(db, alice, WorkspaceCreate(name="Docs"))
    first_id, second_id, owner_id = first.id, second.id, alice.id
    assert first_id != second_id
    created_at = first.created_at
    rename_workspace(db, alice, first_id, WorkspaceUpdate(name=" Updated "))
    db.commit()
    db.expire_all()
    saved = get_workspace(db, alice, first_id)
    assert saved.name == "Updated"
    assert saved.owner_user_id == owner_id
    assert saved.created_at == created_at
    assert saved.updated_at >= created_at
    assert get_workspace(db, alice, second_id).name == "Docs"


def test_foreign_and_missing_workspaces_have_same_error(workspace_db):
    db, alice, bob = workspace_db
    workspace = create_workspace(db, alice, WorkspaceCreate(name="Private"))
    db.commit()
    errors = []
    for workspace_id in (workspace.id, uuid4()):
        for operation in (
            lambda: get_workspace(db, bob, workspace_id),
            lambda: rename_workspace(
                db, bob, workspace_id, WorkspaceUpdate(name="Stolen")
            ),
        ):
            with pytest.raises(AppError) as exc:
                operation()
            errors.append((exc.value.status_code, exc.value.code, exc.value.message))
    assert errors == [(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")] * 4
    db.expire_all()
    assert get_workspace(db, alice, workspace.id).name == "Private"


def test_list_scopes_count_and_orders_paginated_results(workspace_db):
    db, alice, bob = workspace_db
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    owned = [
        Workspace(
            id=uuid4(),
            name="Docs",
            owner_user_id=alice.id,
            created_at=timestamp,
            updated_at=timestamp,
        )
        for _ in range(3)
    ]
    db.add_all(owned)
    create_workspace(db, bob, WorkspaceCreate(name="Other user"))
    db.commit()
    expected = sorted((item.id for item in owned), reverse=True)
    page = list_workspaces(db, alice, limit=1, offset=1)
    assert page.total == 3
    assert [item.id for item in page.items] == expected[1:2]
    assert [item.id for item in list_workspaces(db, alice).items] == expected
    assert list_workspaces(db, alice, offset=10).items == []
    assert list_workspaces(db, bob).total == 1


def test_create_and_rename_can_be_rolled_back(workspace_db):
    db, alice, _ = workspace_db
    workspace = create_workspace(db, alice, WorkspaceCreate(name="Original"))
    workspace_id = workspace.id
    db.rollback()
    assert db.get(Workspace, workspace_id) is None
    workspace = create_workspace(db, alice, WorkspaceCreate(name="Original"))
    workspace_id = workspace.id
    db.commit()
    rename_workspace(db, alice, workspace_id, WorkspaceUpdate(name="Changed"))
    db.rollback()
    assert get_workspace(db, alice, workspace_id).name == "Original"


@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (20, -1)])
def test_invalid_pagination_is_rejected(workspace_db, limit, offset):
    db, alice, _ = workspace_db
    with pytest.raises(AppError) as exc:
        list_workspaces(db, alice, limit=limit, offset=offset)
    assert exc.value.status_code == 422
