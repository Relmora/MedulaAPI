"""Import all models here so Alembic sees the complete shared metadata."""

from backend.models.auth_session import AuthSession
from backend.models.base import Base
from backend.models.knowledge_base import KnowledgeBase
from backend.models.user import User
from backend.models.workspace import Workspace

__all__ = ["AuthSession", "Base", "KnowledgeBase", "User", "Workspace"]
