from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_workspace_routes import clients as clients

from backend.models import KnowledgeBase


def workspace(client):
    return client.post("/workspaces", json={"name": "Workspace"}).json()["id"]


def collection(workspace_id):
    return f"/workspaces/{workspace_id}/knowledge-bases"


def test_lifecycle_persistence_and_duplicate_names(clients):
    alice, _, engine = clients
    workspace_id = workspace(alice)
    path = collection(workspace_id)
    response = alice.post(path, json={"name": " Docs "})
    assert response.status_code == 201
    saved = response.json()
    assert saved["name"] == "Docs"
    assert saved["workspace_id"] == workspace_id
    assert set(saved) == {"id", "workspace_id", "name", "created_at", "updated_at"}
    duplicate = alice.post(path, json={"name": "Docs"}).json()
    assert duplicate["id"] != saved["id"]
    detail = f"{path}/{saved['id']}"
    assert alice.get(detail).json() == saved
    response = alice.patch(detail, json={"name": " Renamed "})
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["created_at"] == saved["created_at"]
    assert response.json()["updated_at"] >= saved["updated_at"]
    assert alice.get(detail).json()["name"] == "Renamed"
    for response in (response, alice.get(path), alice.get(detail)):
        assert response.headers["cache-control"] == "no-store"
    with Session(engine) as db:
        assert sorted(db.scalars(select(KnowledgeBase.name))) == ["Docs", "Renamed"]


def test_other_user_and_missing_workspace_reject_all_operations(clients):
    alice, bob, _ = clients
    path = collection(workspace(alice))
    item = alice.post(path, json={"name": "Private"}).json()
    for forbidden in (path, collection(uuid4())):
        for response in (
            bob.post(forbidden, json={"name": "Bad"}),
            bob.get(forbidden),
            bob.get(f"{forbidden}/{item['id']}"),
            bob.patch(f"{forbidden}/{item['id']}", json={"name": "Bad"}),
        ):
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"
    assert alice.get(f"{path}/{item['id']}").json()["name"] == "Private"


def test_wrong_workspace_for_same_owner_and_missing_base(clients):
    alice, _, _ = clients
    path = collection(workspace(alice))
    other = collection(workspace(alice))
    item = alice.post(path, json={"name": "Private"}).json()
    for detail in (f"{other}/{item['id']}", f"{path}/{uuid4()}"):
        for response in (
            alice.get(detail),
            alice.patch(detail, json={"name": "Bad"}),
        ):
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "KNOWLEDGE_BASE_NOT_FOUND"


def test_pagination_is_scoped_and_stably_ordered(clients):
    alice, bob, engine = clients
    path = collection(workspace(alice))
    other = collection(workspace(alice))
    foreign = collection(workspace(bob))
    assert alice.get(path).json() == {"items": [], "limit": 20, "offset": 0, "total": 0}
    ids = [alice.post(path, json={"name": "Docs"}).json()["id"] for _ in range(3)]
    alice.post(other, json={"name": "Other"})
    bob.post(foreign, json={"name": "Foreign"})
    with Session(engine) as db:
        for item in db.scalars(select(KnowledgeBase)):
            item.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        db.commit()
    page = alice.get(f"{path}?limit=1&offset=1").json()
    assert page["total"] == 3
    assert [item["id"] for item in page["items"]] == sorted(ids, reverse=True)[1:2]
    assert alice.get(f"{path}?offset=10").json()["items"] == []
    for query in ("limit=0", "limit=101", "offset=-1", "limit=bad"):
        assert alice.get(f"{path}?{query}").status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": ""},
        {"name": " \t\n"},
        {"name": "a" * 101},
        {"name": None},
        {"name": 123},
        {"name": "Docs", "workspace_id": str(uuid4())},
        {"name": "Docs", "owner_user_id": str(uuid4())},
    ],
)
def test_invalid_payloads(clients, payload):
    alice, _, _ = clients
    path = collection(workspace(alice))
    item = alice.post(path, json={"name": "Original"}).json()
    assert alice.post(path, json=payload).status_code == 422
    assert alice.patch(f"{path}/{item['id']}", json=payload).status_code == 422
    assert alice.get(f"{path}/{item['id']}").json()["name"] == "Original"
    assert alice.get(path).json()["total"] == 1


def test_authentication_and_origin_protection(clients):
    alice, _, _ = clients
    path = collection(workspace(alice))
    item = alice.post(path, json={"name": "Original"}).json()
    detail = f"{path}/{item['id']}"
    for method, target in (("POST", path), ("PATCH", detail)):
        assert (
            alice.request(
                method,
                target,
                json={"name": "Bad"},
                headers={"Origin": "https://attacker.example"},
            ).status_code
            == 403
        )
    assert alice.get(path).json()["total"] == 1
    assert alice.get(detail).json()["name"] == "Original"
    alice.cookies.clear()
    for method, target in (
        ("POST", path),
        ("GET", path),
        ("GET", detail),
        ("PATCH", detail),
    ):
        kwargs = {"json": {"name": "Bad"}} if method in ("POST", "PATCH") else {}
        assert alice.request(method, target, **kwargs).status_code == 401


@pytest.mark.parametrize("operation", ["create", "rename"])
def test_failed_commit_rolls_back(clients, monkeypatch, operation):
    alice, _, engine = clients
    path = collection(workspace(alice))
    item = alice.post(path, json={"name": "Original"}).json()

    def fail(self):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", fail)
    if operation == "create":
        response = alice.post(path, json={"name": "Bad"})
    else:
        response = alice.patch(f"{path}/{item['id']}", json={"name": "Bad"})
    assert response.status_code == 500
    with Session(engine) as db:
        assert list(db.scalars(select(KnowledgeBase.name))) == ["Original"]
