"""Shared SQLAlchemy metadata for all application models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
