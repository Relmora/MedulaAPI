"""Reusable authentication dependencies for protected routes."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.auth.sessions import authenticated_user
from backend.database import get_db_session
from backend.models import User


def get_current_user(
    request: Request, db: Annotated[Session, Depends(get_db_session)]
) -> User:
    return authenticated_user(request, db)
