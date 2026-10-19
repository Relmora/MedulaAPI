"""Session operations. Routes commit changes before sending cookies."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import Request, Response
from sqlalchemy import select, update
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


def decode_access_token(
    token: str, key: str, *, allow_expired: bool = False
) -> tuple[UUID, UUID]:
    claims = jwt.decode(
        token,
        key,
        algorithms=["HS256"],
        issuer=ISSUER,
        audience=AUDIENCE,
        options={
            "verify_exp": not allow_expired,
            "require": ["sub", "sid", "iat", "exp", "iss", "aud", "token_type"],
        },
    )
    if claims["token_type"] != "access":
        raise jwt.InvalidTokenError("Expected an access token")
    return UUID(claims["sub"]), UUID(claims["sid"])


def session_deadline(login: AuthSession) -> datetime:
    # SQLite tests return naive timestamps; PostgreSQL returns timezone-aware ones.
    deadline = login.expires_at
    return deadline if deadline.tzinfo else deadline.replace(tzinfo=UTC)


def refresh_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
    refresh_token = secrets.token_urlsafe(32)
    login = AuthSession(
        id=uuid4(),
        user_id=user.id,
        refresh_token_hash=refresh_token_hash(refresh_token),
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
    return access, refresh_token


def set_login_cookies(
    response: Response,
    tokens: tuple[str, str],
    settings: Settings,
    remaining_seconds: int = SESSION_SECONDS,
) -> None:
    access_token, refresh_token = tokens
    for name, value, seconds, path in [
        ("access_token", access_token, min(ACCESS_SECONDS, remaining_seconds), "/"),
        ("refresh_token", refresh_token, remaining_seconds, "/auth"),
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
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise invalid
    key = signing_key(Settings())
    try:
        user_id, session_id = decode_access_token(access_token, key)
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise invalid from None

    login = db.get(AuthSession, session_id)
    if login is None or login.user_id != user_id or login.revoked_at is not None:
        raise invalid

    deadline = session_deadline(login)
    if deadline <= datetime.now(UTC):
        raise invalid

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise invalid
    return user


def rotate_refresh_token(
    db: Session, refresh_token: str | None, settings: Settings
) -> tuple[tuple[str, str], int]:
    invalid = AppError(
        "REFRESH_REJECTED", "Session could not be refreshed. Sign in again.", 401
    )

    if not refresh_token or len(refresh_token) > 256:
        raise invalid
    key = signing_key(settings)
    old_hash = refresh_token_hash(refresh_token)
    now = datetime.now(UTC)
    login = db.scalar(
        select(AuthSession).where(AuthSession.refresh_token_hash == old_hash)
    )
    if login is None or login.revoked_at is not None:
        raise invalid
    deadline = session_deadline(login)
    remaining = int((deadline - now).total_seconds())
    if remaining < 1:
        raise invalid
    new_refresh_token = secrets.token_urlsafe(32)
    active_users = select(User.id).where(User.is_active.is_(True))
    # Check the old hash again in the UPDATE so only one concurrent refresh wins.
    result = db.execute(
        update(AuthSession)
        .where(
            AuthSession.id == login.id,
            AuthSession.refresh_token_hash == old_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
            AuthSession.user_id.in_(active_users),
        )
        .values(refresh_token_hash=refresh_token_hash(new_refresh_token)),
        execution_options={"synchronize_session": False},
    )
    if result.rowcount != 1:
        raise invalid
    access = jwt.encode(
        {
            "sub": str(login.user_id),
            "sid": str(login.id),
            "iat": now,
            "exp": min(now + timedelta(seconds=ACCESS_SECONDS), deadline),
            "iss": ISSUER,
            "aud": AUDIENCE,
            "token_type": "access",
            "jti": str(uuid4()),
        },
        key,
        algorithm="HS256",
    )
    return (access, new_refresh_token), remaining


def clear_login_cookies(response: Response, settings: Settings) -> None:
    for name, path in [("access_token", "/"), ("refresh_token", "/auth")]:
        response.delete_cookie(
            name,
            path=path,
            secure=settings.auth_cookie_secure,
            httponly=True,
            samesite="lax",
        )
    response.headers["Cache-Control"] = "no-store"


def revoke_current_session(request: Request, db: Session, settings: Settings) -> None:
    """An expired signed access token may revoke only its own session."""
    login = None
    access_token = request.cookies.get("access_token")
    if access_token:
        try:
            # Expired access may identify a session for logout, never for access.
            user_id, session_id = decode_access_token(
                access_token, signing_key(settings), allow_expired=True
            )
            login = db.scalar(
                select(AuthSession).where(
                    AuthSession.id == session_id, AuthSession.user_id == user_id
                )
            )
        except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
            pass
    # Browsers normally discard expired access cookies. Refresh remains usable
    # for logout even when the access cookie is absent or invalid.
    refresh_token = request.cookies.get("refresh_token")
    if login is None and refresh_token and len(refresh_token) <= 256:
        login = db.scalar(
            select(AuthSession).where(
                AuthSession.refresh_token_hash == refresh_token_hash(refresh_token)
            )
        )
    if login is not None:
        db.execute(
            update(AuthSession)
            .where(AuthSession.id == login.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )


def revoke_all_sessions(db: Session, user: User) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
