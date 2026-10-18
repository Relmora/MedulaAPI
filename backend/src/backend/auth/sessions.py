"""Issue credentials for a persistent login; never commit inside this module."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import Request, Response
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.errors import AppError
from backend.models import AuthSession, User

ACCESS_SECONDS = 15 * 60
SESSION_SECONDS = 7 * 24 * 60 * 60
ISSUER = "medula-api"
AUDIENCE = "medula-browser"


def signing_key(settings: Settings) -> str:
    key = settings.auth_signing_key.get_secret_value()
    if len(key.encode()) < 32:
        raise AppError("AUTH_NOT_CONFIGURED", "Authentication is not configured.", 503)
    return key


def require_trusted_origin(request: Request) -> None:
    settings = Settings()
    origin = request.headers.get("origin")
    allowed = {str(value).rstrip("/") for value in settings.auth_allowed_origins}
    if origin is not None and origin not in allowed:
        raise AppError("UNTRUSTED_ORIGIN", "Request origin is not allowed.", 403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise AppError("UNTRUSTED_ORIGIN", "Cross-site requests are not allowed.", 403)
    # Non-browser clients may omit Origin. Requiring JSON prevents simple form CSRF.
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise AppError("JSON_REQUIRED", "Content-Type must be application/json.", 415)


def create_login_session(
    db: Session, user: User, settings: Settings
) -> tuple[str, str]:
    key = signing_key(settings)
    now = datetime.now(UTC)
    raw_refresh = secrets.token_urlsafe(32)
    login = AuthSession(
        id=uuid4(),
        user_id=user.id,
        refresh_token_hash=hashlib.sha256(raw_refresh.encode()).hexdigest(),
        created_at=now,
        expires_at=now + timedelta(seconds=SESSION_SECONDS),
    )
    db.add(login)
    access = jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(login.id),
            "iat": now,
            "exp": now + timedelta(seconds=ACCESS_SECONDS),
            "iss": ISSUER,
            "aud": AUDIENCE,
            "token_type": "access",
        },
        key,
        algorithm="HS256",
    )
    return access, raw_refresh


def set_login_cookies(
    response: Response, tokens: tuple[str, str], settings: Settings
) -> None:
    for name, value, seconds, path in [
        ("access_token", tokens[0], ACCESS_SECONDS, "/"),
        ("refresh_token", tokens[1], SESSION_SECONDS, "/auth"),
    ]:
        response.set_cookie(
            name,
            value,
            max_age=seconds,
            path=path,
            secure=settings.auth_cookie_secure,
            httponly=True,
            samesite="lax",
        )
    response.headers["Cache-Control"] = "no-store"


def authenticated_user(request: Request, db: Session) -> User:
    invalid = AppError("UNAUTHENTICATED", "A valid login is required.", 401)
    raw = request.cookies.get("access_token")
    if not raw:
        raise invalid
    key = signing_key(Settings())
    try:
        claims = jwt.decode(
            raw,
            key,
            algorithms=["HS256"],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={
                "require": ["sub", "sid", "iat", "exp", "iss", "aud", "token_type"]
            },
        )
        if claims["token_type"] != "access":
            raise invalid
        user_id, session_id = UUID(claims["sub"]), UUID(claims["sid"])
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise invalid from None
    login = db.get(AuthSession, session_id)
    if login is None or login.user_id != user_id or login.revoked_at is not None:
        raise invalid
    # SQLite test storage drops timezone metadata; PostgreSQL preserves it.
    deadline = login.expires_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if deadline <= datetime.now(UTC):
        raise invalid
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise invalid
    return user
