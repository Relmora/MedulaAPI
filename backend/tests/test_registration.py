import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.auth.passwords import verify_password
from backend.database import get_db_session
from backend.main import app
from backend.models import Base, User


@pytest.fixture
def registration_client(monkeypatch):
    monkeypatch.setenv("REGISTRATION_ENABLED", "true")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # Isolated in-memory test database only; never application startup.
    Base.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        engine.dispose()


def test_register_persists_hash_and_rejects_normalized_duplicate(registration_client):
    client, engine = registration_client
    password = "my long example password"
    response = client.post(
        "/auth/register", json={"username": " Alice ", "password": password}
    )
    assert response.status_code == 201
    assert set(response.json()) == {"id", "username", "created_at"}
    assert response.json()["username"] == "alice"
    assert "set-cookie" not in response.headers
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "alice"))
        assert user.is_active
        assert user.password_hash != password
        assert verify_password(password, user.password_hash)
    duplicate = client.post(
        "/auth/register", json={"username": "ALICE", "password": password}
    )
    assert duplicate.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "ab", "password": "long example password"},
        {"username": "bad/name", "password": "long example password"},
        {"username": "alice", "password": "secret-short"},
        {"username": "alice", "password": "x" * 129},
        {"username": "alice", "password": "long example password", "is_active": True},
    ],
)
def test_invalid_input_does_not_create_user_or_echo_password(
    registration_client, payload
):
    client, engine = registration_client
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 422
    assert payload["password"] not in response.text
    with Session(engine) as session:
        assert session.scalar(select(User.id)) is None


def test_registration_can_be_disabled(registration_client, monkeypatch):
    client, engine = registration_client
    monkeypatch.setenv("REGISTRATION_ENABLED", "false")
    response = client.post(
        "/auth/register",
        json={"username": "alice", "password": "long example password"},
    )
    assert response.status_code == 403
    with Session(engine) as session:
        assert session.scalar(select(User.id)) is None
