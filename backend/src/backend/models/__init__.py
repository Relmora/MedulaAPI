"""Import all models here so Alembic sees the complete shared metadata."""

from backend.models.auth_session import AuthSession
from backend.models.base import Base
from backend.models.document import Document
from backend.models.entity import Entity
from backend.models.entity_relationship import EntityRelationship
from backend.models.indexed_chunk import IndexedChunk
from backend.models.ingestion_job import IngestionJob
from backend.models.ingestion_job_attempt import IngestionJobAttempt
from backend.models.knowledge_base import KnowledgeBase
from backend.models.outbox_event import OutboxEvent
from backend.models.user import User
from backend.models.workspace import Workspace

__all__ = [
    "AuthSession",
    "Base",
    "Document",
    "Entity",
    "EntityRelationship",
    "IngestionJob",
    "IngestionJobAttempt",
    "IndexedChunk",
    "KnowledgeBase",
    "OutboxEvent",
    "User",
    "Workspace",
]
