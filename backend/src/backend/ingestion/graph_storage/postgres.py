"""Transactional PostgreSQL implementation of entity and edge persistence."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import (
    DataError,
    DBAPIError,
    IntegrityError,
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import Session

from backend.ingestion.claim import SessionFactory
from backend.ingestion.graph_storage.interface import (
    GraphStorageError,
    GraphStorageTransientError,
    GraphWriteResult,
)
from backend.ingestion.graph_storage.normalization import normalize_entity_name
from backend.ingestion.relation_extraction import RelationExtractedDocument
from backend.models import Document, Entity, EntityRelationship


class PostgresGraphStore:
    """Resolve chunk-local entities and idempotently upsert graph rows."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def write(self, document: RelationExtractedDocument) -> GraphWriteResult:
        try:
            return self._write(document)
        except GraphStorageError:
            raise
        except (OperationalError, SQLAlchemyTimeoutError) as error:
            raise GraphStorageTransientError(
                "GRAPH_DATABASE_UNAVAILABLE",
                "The graph database is temporarily unavailable.",
            ) from error
        except (IntegrityError, DataError) as error:
            raise GraphStorageError(
                "GRAPH_WRITE_INVALID",
                "The graph database rejected the resolved entities or relationships.",
            ) from error
        except DBAPIError as error:
            if error.connection_invalidated:
                raise GraphStorageTransientError(
                    "GRAPH_DATABASE_UNAVAILABLE",
                    "The graph database connection was interrupted.",
                ) from error
            raise GraphStorageError(
                "GRAPH_WRITE_INVALID",
                "The graph database rejected the resolved graph.",
            ) from error
        except SQLAlchemyError as error:
            raise GraphStorageError(
                "GRAPH_CONFIGURATION_INVALID",
                "Graph persistence is not configured correctly.",
            ) from error

    def _write(self, document: RelationExtractedDocument) -> GraphWriteResult:
        created_entity_count = 0
        created_relationship_count = 0
        resolved_entity_ids: set[UUID] = set()
        resolved_relationship_ids: set[UUID] = set()

        with self._session_factory() as db, db.begin():
            source_document = db.scalar(
                select(Document)
                .where(Document.id == document.document_id)
                .with_for_update()
            )
            if source_document is None:
                raise GraphStorageError(
                    "GRAPH_DOCUMENT_NOT_FOUND",
                    "The source document no longer exists.",
                )
            knowledge_base_id = source_document.knowledge_base_id

            for chunk in document.chunks:
                chunk_entities: dict[UUID, Entity] = {}
                for extracted in chunk.entities:
                    entity, created = self._resolve_entity(
                        db,
                        knowledge_base_id=knowledge_base_id,
                        name=extracted.name,
                        entity_type=extracted.type,
                    )
                    chunk_entities[extracted.entity_id] = entity
                    resolved_entity_ids.add(entity.id)
                    created_entity_count += int(created)

                for extracted in chunk.relations:
                    subject = chunk_entities.get(extracted.source_entity_id)
                    object_entity = chunk_entities.get(extracted.target_entity_id)
                    if subject is None or object_entity is None:
                        raise GraphStorageError(
                            "GRAPH_RELATION_ENDPOINT_INVALID",
                            "A relationship endpoint is missing from its source chunk.",
                        )
                    if subject.id == object_entity.id:
                        continue
                    relationship, created = self._resolve_relationship(
                        db,
                        knowledge_base_id=knowledge_base_id,
                        subject_entity_id=subject.id,
                        predicate=extracted.type,
                        object_entity_id=object_entity.id,
                        document_id=document.document_id,
                        chunk_id=chunk.chunk_id,
                    )
                    resolved_relationship_ids.add(relationship.id)
                    created_relationship_count += int(created)

        return GraphWriteResult(
            document_id=document.document_id,
            entity_count=len(resolved_entity_ids),
            relationship_count=len(resolved_relationship_ids),
            created_entity_count=created_entity_count,
            created_relationship_count=created_relationship_count,
        )

    @staticmethod
    def _resolve_entity(
        db: Session,
        *,
        knowledge_base_id: UUID,
        name: str,
        entity_type: str,
    ) -> tuple[Entity, bool]:
        normalized_name = normalize_entity_name(name, entity_type)
        normalized_type = entity_type.strip().upper()
        if not normalized_name or not normalized_type:
            raise GraphStorageError(
                "GRAPH_ENTITY_INVALID",
                "An extracted entity cannot be normalized to a stable identity.",
            )
        query = select(Entity).where(
            Entity.knowledge_base_id == knowledge_base_id,
            Entity.entity_type == normalized_type,
            Entity.normalized_name == normalized_name,
        )
        existing = db.scalar(query)
        if existing is not None:
            return existing, False

        entity = Entity(
            knowledge_base_id=knowledge_base_id,
            name=" ".join(name.split()),
            normalized_name=normalized_name,
            entity_type=normalized_type,
        )
        try:
            with db.begin_nested():
                db.add(entity)
                db.flush()
        except IntegrityError:
            existing = db.scalar(query)
            if existing is None:
                raise
            return existing, False
        return entity, True

    @staticmethod
    def _resolve_relationship(
        db: Session,
        *,
        knowledge_base_id: UUID,
        subject_entity_id: UUID,
        predicate: str,
        object_entity_id: UUID,
        document_id: UUID,
        chunk_id: UUID,
    ) -> tuple[EntityRelationship, bool]:
        normalized_predicate = predicate.strip().upper()
        if not normalized_predicate:
            raise GraphStorageError(
                "GRAPH_RELATION_INVALID",
                "An extracted relationship must have a predicate.",
            )
        query = select(EntityRelationship).where(
            EntityRelationship.knowledge_base_id == knowledge_base_id,
            EntityRelationship.subject_entity_id == subject_entity_id,
            EntityRelationship.predicate == normalized_predicate,
            EntityRelationship.object_entity_id == object_entity_id,
        )
        existing = db.scalar(query)
        if existing is not None:
            return existing, False

        relationship = EntityRelationship(
            knowledge_base_id=knowledge_base_id,
            subject_entity_id=subject_entity_id,
            predicate=normalized_predicate,
            object_entity_id=object_entity_id,
            document_id=document_id,
            chunk_id=chunk_id,
        )
        try:
            with db.begin_nested():
                db.add(relationship)
                db.flush()
        except IntegrityError:
            existing = db.scalar(query)
            if existing is None:
                raise
            return existing, False
        return relationship, True
