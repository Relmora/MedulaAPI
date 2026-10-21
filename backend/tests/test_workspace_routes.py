from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.database import get_db_session
from backend.main import app
from backend.models import Base, Workspace


@pytest.fixture
def clients(monkeypatch):
    monkeypatch.setenv("REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("AUTH_SIGNING_KEY", "test-only-key-" * 4)
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    def override_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as alice, TestClient(app) as bob:
            for client, name in ((alice, "alice"), (bob, "bob")):
                result = client.post(
                    "/auth/register",
                    json={"username": name, "password": "long example password"},
                )
                assert result.status_code == 201
            yield alice, bob, engine
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        engine.dispose()


def test_workspace_lifecycle_and_isolation(clients):
    alice, bob, engine = clients
    response = alice.post("/workspaces", json={"name": " Docs "})
    assert response.status_code == 201
    workspace = response.json()
    workspace_id = workspace["id"]
    assert workspace["name"] == "Docs"
    assert set(workspace) == {"id", "name", "created_at", "updated_at"}
    assert response.headers["cache-control"] == "no-store"
    assert alice.get(f"/workspaces/{workspace_id}").json() == workspace
    assert alice.get("/workspaces?limit=1&offset=0").json()["total"] == 1
    assert bob.get("/workspaces").json()["items"] == []
    for target in (workspace_id, str(uuid4())):
        for response in (
            bob.get(f"/workspaces/{target}"),
            bob.patch(f"/workspaces/{target}", json={"name": "Stolen"}),
        ):
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"
    response = alice.patch(f"/workspaces/{workspace_id}", json={"name": " Renamed "})
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    with Session(engine) as db:
        assert db.scalar(select(Workspace)).name == "Renamed"


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/workspaces", {"name": "Docs"}),
        ("get", "/workspaces", None),
        ("get", f"/workspaces/{uuid4()}", None),
        ("patch", f"/workspaces/{uuid4()}", {"name": "Docs"}),
    ],
)
def test_login_required(clients, method, path, payload):
    alice, _, _ = clients
    alice.cookies.clear()
    kwargs = {"json": payload} if payload is not None else {}
    assert alice.request(method, path, **kwargs).status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "  "},
        {"name": "a" * 101},
        {"name": "Docs", "owner_user_id": str(uuid4())},
    ],
)
def test_reject_invalid_create_and_update(clients, payload):
    alice, _, _ = clients
    workspace_id = alice.post("/workspaces", json={"name": "Docs"}).json()["id"]
    assert alice.post("/workspaces", json=payload).status_code == 422
    assert alice.patch(f"/workspaces/{workspace_id}", json=payload).status_code == 422
    assert alice.get(f"/workspaces/{workspace_id}").json()["name"] == "Docs"


def test_pagination_validation_and_uuid(clients):
    alice, _, _ = clients
    for query in ("limit=0", "limit=101", "offset=-1"):
        assert alice.get(f"/workspaces?{query}").status_code == 422
    assert alice.get("/workspaces/not-a-uuid").status_code == 422


def test_untrusted_origin_cannot_write_and_patch_preflight_works(clients):
    alice, _, _ = clients
    workspace_id = alice.post("/workspaces", json={"name": "Docs"}).json()["id"]
    headers = {"Origin": "https://attacker.example"}
    assert (
        alice.post("/workspaces", json={"name": "Bad"}, headers=headers).status_code
        == 403
    )
    assert (
        alice.patch(
            f"/workspaces/{workspace_id}", json={"name": "Bad"}, headers=headers
        ).status_code
        == 403
    )
    assert alice.get(f"/workspaces/{workspace_id}").json()["name"] == "Docs"
    response = alice.options(
        f"/workspaces/{workspace_id}",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_failed_commit_does_not_report_success_or_persist(clients, monkeypatch):
    alice, _, engine = clients

    def fail(self):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", fail)
    assert alice.post("/workspaces", json={"name": "Docs"}).status_code == 500
    with Session(engine) as db:
        assert db.scalar(select(Workspace)) is None
