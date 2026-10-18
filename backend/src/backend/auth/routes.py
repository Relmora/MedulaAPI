from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth.passwords import hash_password, password_needs_rehash, verify_password
from backend.auth.schemas import LoginRequest, RegisterRequest, UserResponse
from backend.auth.sessions import (
    authenticated_user,
    create_login_session,
    require_trusted_origin,
    set_login_cookies,
    signing_key,
)
from backend.config import Settings
from backend.database import get_db_session
from backend.errors import AppError
from backend.logging import get_logger
from backend.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Startup work keeps unknown-user login checks comparable to password mismatches.
_dummy_password_hash = hash_password("dummy-password-never-used-for-login")


def require_registration_enabled() -> None:
    if not Settings().registration_enabled:
        raise AppError("REGISTRATION_DISABLED", "Registration is disabled.", 403)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_registration_enabled),
        Depends(require_trusted_origin),
    ],
)
def register(
    payload: RegisterRequest,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> UserResponse:
    settings = Settings()
    signing_key(settings)
    # Sync route: expensive password hashing runs off the async event loop.
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password.get_secret_value()),
    )
    session.add(user)
    
    try:
        session.flush()
        tokens = create_login_session(session, user, settings)
        result = UserResponse.model_validate(user)
        session.commit()
    except IntegrityError:
        session.rollback()

        if session.scalar(select(User.id).where(User.username == payload.username)):
            raise AppError(
                "USERNAME_UNAVAILABLE", "Username is unavailable.", 409
            ) from None
        raise
    set_login_cookies(response, tokens, settings)
    logger.info("Account created", extra={"event": "auth.account_created"})
    return result


@router.post(
    "/login",
    response_model=UserResponse,
    dependencies=[Depends(require_trusted_origin)],
)
def login(
    payload: LoginRequest,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> UserResponse:
    settings = Settings()
    signing_key(settings)
    user = session.scalar(select(User).where(User.username == payload.username))

    password = payload.password.get_secret_value()
    valid = verify_password(
        password, user.password_hash if user else _dummy_password_hash
    )

    if not valid or user is None or not user.is_active:
        logger.warning("Login rejected", extra={"event": "auth.login_rejected"})
        raise AppError("INVALID_CREDENTIALS", "Invalid username or password.", 401)
    
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    tokens = create_login_session(session, user, settings)
    result = UserResponse.model_validate(user)
    session.commit()
    
    set_login_cookies(response, tokens, settings)
    logger.info("Login succeeded", extra={"event": "auth.login_succeeded"})
    return result


@router.get("/me", response_model=UserResponse)
def me(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> User:
    response.headers["Cache-Control"] = "no-store"
    return authenticated_user(request, session)
