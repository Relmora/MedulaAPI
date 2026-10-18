from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth.passwords import hash_password
from backend.auth.schemas import RegisterRequest, UserResponse
from backend.config import Settings
from backend.database import get_db_session
from backend.errors import AppError
from backend.logging import get_logger
from backend.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def require_registration_enabled() -> None:
    if not Settings().registration_enabled:
        raise AppError("REGISTRATION_DISABLED", "Registration is disabled.", 403)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_registration_enabled)],
)
def register(
    payload: RegisterRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> User:
    # Sync route: expensive password hashing runs off the async event loop.
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password.get_secret_value()),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
       
        if session.scalar(select(User.id).where(User.username == payload.username)):
            raise AppError(
                "USERNAME_UNAVAILABLE", "Username is unavailable.", 409
            ) from None
        raise
    session.refresh(user)
    logger.info("Account created", extra={"event": "auth.account_created"})
    return user
