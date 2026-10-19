import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.auth.passwords import verify_password
from backend.database import get_db_session
from backend.main import app
from backend.models import AuthSession, Base, User


@pytest.fixture
def registration_client(monkeypatch):
    monkeypatch.setenv("REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("AUTH_SIGNING_KEY", "test-only-key-" * 4)
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
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
    assert "set-cookie" in response.headers
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


PAYLOAD = {"username": "alice", "password": "my long example password"}


def test_signup_session_and_login_for_existing_user(registration_client):
    import hashlib

    client, engine = registration_client
    response = client.post("/auth/register", json=PAYLOAD)
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2
    assert all("HttpOnly" in cookie and "SameSite=lax" in cookie for cookie in cookies)
    with Session(engine) as db:
        record = db.scalar(select(AuthSession))
        assert (
            record.refresh_token_hash
            == hashlib.sha256(client.cookies.get("refresh_token").encode()).hexdigest()
        )
        assert str(record.user_id) == response.json()["id"]
    assert client.get("/auth/me").json()["username"] == "alice"
    client.cookies.clear()
    assert client.get("/auth/me").status_code == 401
    response = client.post("/auth/login", json=PAYLOAD)
    assert response.status_code == 200
    assert client.get("/auth/me").status_code == 200
    with Session(engine) as db:
        assert len(db.scalars(select(AuthSession)).all()) == 2


@pytest.mark.parametrize("case", ["wrong", "missing", "disabled"])
def test_rejected_login_does_not_create_session(registration_client, case):
    client, engine = registration_client
    client.post("/auth/register", json=PAYLOAD)
    payload = dict(PAYLOAD)
    if case == "wrong":
        payload["password"] = "wrong password"
    elif case == "missing":
        payload["username"] = "missing"
    else:
        with Session(engine) as db:
            db.scalar(select(User)).is_active = False
            db.commit()
    response = client.post("/auth/login", json=payload)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert "set-cookie" not in response.headers
    with Session(engine) as db:
        assert len(db.scalars(select(AuthSession)).all()) == 1


@pytest.mark.parametrize("case", ["revoked", "expired", "disabled"])
def test_me_checks_live_session_and_account(registration_client, case):
    from datetime import UTC, datetime, timedelta

    client, engine = registration_client
    client.post("/auth/register", json=PAYLOAD)
    with Session(engine) as db:
        record = db.scalar(select(AuthSession))
        if case == "revoked":
            record.revoked_at = datetime.now(UTC)
        elif case == "expired":
            record.created_at = datetime.now(UTC) - timedelta(days=2)
            record.expires_at = datetime.now(UTC) - timedelta(days=1)
        else:
            db.scalar(select(User)).is_active = False
        db.commit()
    assert client.get("/auth/me").status_code == 401


@pytest.mark.parametrize(
    "case", ["signature", "expiry", "audience", "type", "missing_sid"]
)
def test_invalid_access_tokens_are_rejected(registration_client, case):
    import jwt

    client, _ = registration_client
    client.post("/auth/register", json=PAYLOAD)
    claims = jwt.decode(
        client.cookies.get("access_token"), options={"verify_signature": False}
    )
    key = "test-only-key-" * 4
    if case == "signature":
        key = "different-key-" * 4
    elif case == "expiry":
        claims["exp"] = 1
    elif case == "audience":
        claims["aud"] = "another-app"
    elif case == "type":
        claims["token_type"] = "refresh"
    else:
        del claims["sid"]
    client.cookies.clear()
    client.cookies.set("access_token", jwt.encode(claims, key, algorithm="HS256"))
    assert client.get("/auth/me").status_code == 401


def test_untrusted_origin_cannot_register(registration_client):
    client, engine = registration_client
    response = client.post(
        "/auth/register", json=PAYLOAD, headers={"Origin": "https://attacker.example"}
    )
    assert response.status_code == 403
    with Session(engine) as db:
        assert db.scalar(select(User)) is None


def test_signup_session_failure_rolls_back_user(registration_client, monkeypatch):
    from backend.auth import routes

    client, engine = registration_client

    def fail(*args):
        raise RuntimeError("simulated session failure")

    monkeypatch.setattr(routes, "create_login_session", fail)
    response = client.post("/auth/register", json=PAYLOAD)
    assert response.status_code == 500
    assert "set-cookie" not in response.headers
    with Session(engine) as db:
        assert db.scalar(select(User)) is None
        assert db.scalar(select(AuthSession)) is None


def test_missing_signing_key_prevents_signup(registration_client, monkeypatch):
    client, engine = registration_client
    monkeypatch.setenv("AUTH_SIGNING_KEY", "")
    response = client.post("/auth/register", json=PAYLOAD)
    assert response.status_code == 503
    with Session(engine) as db:
        assert db.scalar(select(User)) is None


def test_secure_cookie_configuration(registration_client, monkeypatch):
    client, _ = registration_client
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    response = client.post("/auth/register", json=PAYLOAD)
    assert all("Secure" in value for value in response.headers.get_list("set-cookie"))


def test_refresh_rotates_and_rejects_old_token_without_revoking_session(
    registration_client,
):
    import hashlib

    client, engine = registration_client
    client.post("/auth/register", json=PAYLOAD)
    old = client.cookies.get("refresh_token")
    with Session(engine) as db:
        deadline = db.scalar(select(AuthSession)).expires_at
    response = client.post("/auth/refresh", json={})
    assert response.status_code == 204
    new = client.cookies.get("refresh_token")
    assert new != old
    with Session(engine) as db:
        record = db.scalar(select(AuthSession))
        assert record.expires_at == deadline
        assert record.refresh_token_hash == hashlib.sha256(new.encode()).hexdigest()
    assert client.get("/auth/me").status_code == 200
    response = client.post(
        "/auth/refresh", json={}, headers={"Cookie": f"refresh_token={old}"}
    )
    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/refresh", json={}).status_code == 204


@pytest.mark.parametrize(
    "case", ["missing", "invalid", "revoked", "expired", "disabled"]
)
def test_refresh_rejects_unusable_credentials(registration_client, case):
    from datetime import UTC, datetime, timedelta

    client, engine = registration_client
    client.post("/auth/register", json=PAYLOAD)
    if case == "missing":
        client.cookies.clear()
    elif case == "invalid":
        client.cookies.clear()
        client.cookies.set("refresh_token", "invalid")
    else:
        with Session(engine) as db:
            record = db.scalar(select(AuthSession))
            if case == "revoked":
                record.revoked_at = datetime.now(UTC)
            elif case == "expired":
                record.created_at = datetime.now(UTC) - timedelta(days=2)
                record.expires_at = datetime.now(UTC) - timedelta(days=1)
            else:
                db.scalar(select(User)).is_active = False
            db.commit()
    response = client.post("/auth/refresh", json={})
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_refresh_works_without_access_and_caps_expiry(registration_client):
    from datetime import UTC, datetime, timedelta

    import jwt

    client, engine = registration_client
    client.post("/auth/register", json=PAYLOAD)
    raw = client.cookies.get("refresh_token")
    with Session(engine) as db:
        record = db.scalar(select(AuthSession))
        record.expires_at = datetime.now(UTC) + timedelta(seconds=60)
        db.commit()
    client.cookies.clear()
    client.cookies.set("refresh_token", raw)
    response = client.post("/auth/refresh", json={})
    assert response.status_code == 204
    claims = jwt.decode(
        client.cookies.get("access_token"), options={"verify_signature": False}
    )
    assert 0 < claims["exp"] - datetime.now(UTC).timestamp() <= 60
    assert all(
        "Max-Age=59" in cookie or "Max-Age=60" in cookie
        for cookie in response.headers.get_list("set-cookie")
    )


def test_refresh_checks_origin(registration_client):
    client, _ = registration_client
    client.post("/auth/register", json=PAYLOAD)
    assert (
        client.post(
            "/auth/refresh", json={}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_logout_revokes_only_current_session_and_clears_cookies(registration_client):
    client, engine = registration_client
    client.post("/auth/register", json=PAYLOAD)
    first_access = client.cookies.get("access_token")
    first_refresh = client.cookies.get("refresh_token")
    client.post("/auth/login", json=PAYLOAD)
    second_access = client.cookies.get("access_token")
    second_refresh = client.cookies.get("refresh_token")
    response = client.post("/auth/logout", json={})
    assert response.status_code == 204
    assert response.headers["cache-control"] == "no-store"
    deleted = response.headers.get_list("set-cookie")
    assert len(deleted) == 2
    assert all("Max-Age=0" in value and "HttpOnly" in value for value in deleted)
    assert client.get("/auth/me").status_code == 401
    assert (
        client.get(
            "/auth/me", headers={"Cookie": f"access_token={second_access}"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/refresh",
            json={},
            headers={"Cookie": f"refresh_token={second_refresh}"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/auth/me", headers={"Cookie": f"access_token={first_access}"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/auth/refresh",
            json={},
            headers={"Cookie": f"refresh_token={first_refresh}"},
        ).status_code
        == 204
    )
    with Session(engine) as db:
        records = db.scalars(select(AuthSession)).all()
        assert sum(record.revoked_at is not None for record in records) == 1


def test_logout_without_access_uses_refresh_and_is_idempotent(registration_client):
    client, engine = registration_client
    client.post("/auth/register", json=PAYLOAD)
    refresh = client.cookies.get("refresh_token")
    client.cookies.clear()
    client.cookies.set("refresh_token", refresh)
    assert client.post("/auth/logout", json={}).status_code == 204
    client.cookies.clear()
    assert client.post("/auth/logout", json={}).status_code == 204
    with Session(engine) as db:
        assert db.scalar(select(AuthSession)).revoked_at is not None


def test_logout_all_does_not_affect_another_user(registration_client):
    client, engine = registration_client
    client.post("/auth/register", json={**PAYLOAD, "username": "bob"})
    bob_access = client.cookies.get("access_token")
    client.post("/auth/register", json=PAYLOAD)
    alice_first = client.cookies.get("access_token")
    alice_refresh = client.cookies.get("refresh_token")
    client.post("/auth/login", json=PAYLOAD)
    alice_second = client.cookies.get("access_token")
    response = client.post("/auth/logout-all", json={})
    assert response.status_code == 204
    assert len(response.headers.get_list("set-cookie")) == 2
    for access in (alice_first, alice_second):
        assert (
            client.get(
                "/auth/me", headers={"Cookie": f"access_token={access}"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/auth/refresh",
            json={},
            headers={"Cookie": f"refresh_token={alice_refresh}"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/auth/me", headers={"Cookie": f"access_token={bob_access}"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("endpoint", ["/auth/logout", "/auth/logout-all"])
def test_logout_origin_rejection_preserves_session(registration_client, endpoint):
    client, engine = registration_client
    client.post("/auth/register", json=PAYLOAD)
    response = client.post(
        endpoint, json={}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert client.get("/auth/me").status_code == 200


def test_logout_all_requires_authenticated_user(registration_client):
    client, _ = registration_client
    assert client.post("/auth/logout-all", json={}).status_code == 401


def test_logout_commit_failure_does_not_claim_success(registration_client, monkeypatch):
    client, engine = registration_client
    client.post("/auth/register", json=PAYLOAD)

    def fail(*args):
        raise RuntimeError("simulated commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail)
        response = client.post("/auth/logout", json={})
    assert response.status_code == 500
    assert "set-cookie" not in response.headers
    assert client.get("/auth/me").status_code == 200


def test_logout_allows_expired_signed_access_only_for_revocation(registration_client):
    import jwt

    client, engine = registration_client
    client.post("/auth/register", json=PAYLOAD)
    claims = jwt.decode(
        client.cookies.get("access_token"), options={"verify_signature": False}
    )
    claims["exp"] = 1
    expired = jwt.encode(claims, "test-only-key-" * 4, algorithm="HS256")
    client.cookies.clear()
    client.cookies.set("access_token", expired)
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/logout", json={}).status_code == 204
    with Session(engine) as db:
        assert db.scalar(select(AuthSession)).revoked_at is not None
