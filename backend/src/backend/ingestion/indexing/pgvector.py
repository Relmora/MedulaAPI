"""Transactional PostgreSQL/pgvector implementation of the vector index."""

from sqlalchemy import select
from sqlalchemy.exc import (
    DataError,
    DBAPIError,
    IntegrityError,
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.exc import (
    TimeoutError as SQLAlchemyTimeoutError,
)

from backend.ingestion.claim import SessionFactory
from backend.ingestion.indexing.interface import (
    IndexDocument,
    IndexingError,
    IndexingTransientError,
    IndexWriteResult,
)
from backend.models import Document, IndexedChunk, KnowledgeBase
from backend.models.indexed_chunk import EMBEDDING_DIMENSIONS


class PgVectorIndex:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def replace_document(self, document: IndexDocument) -> IndexWriteResult:
        if document.embedding_dimensions != EMBEDDING_DIMENSIONS:
            raise IndexingError(
                "INDEX_DIMENSION_MISMATCH",
                "The embedding dimensions do not match the vector index.",
            )
        try:
            return self._replace_document(document)
        except (OperationalError, SQLAlchemyTimeoutError) as error:
            raise IndexingTransientError(
                "INDEX_DATABASE_UNAVAILABLE",
                "The vector index is temporarily unavailable.",
            ) from error
        except (IntegrityError, DataError) as error:
            raise IndexingError(
                "INDEX_WRITE_INVALID",
                "The vector index rejected the validated document.",
            ) from error
        except DBAPIError as error:
            if error.connection_invalidated:
                raise IndexingTransientError(
                    "INDEX_DATABASE_UNAVAILABLE",
                    "The vector index connection was interrupted.",
                ) from error
            raise IndexingError(
                "INDEX_WRITE_INVALID",
                "The vector index rejected the validated document.",
            ) from error
        except SQLAlchemyError as error:
            raise IndexingError(
                "INDEX_CONFIGURATION_INVALID",
                "The vector index is not configured correctly.",
            ) from error

    def _replace_document(self, document: IndexDocument) -> IndexWriteResult:
        with self._session_factory() as db, db.begin():
            tenant = db.execute(
                select(Document.knowledge_base_id, KnowledgeBase.workspace_id)
                .join(
                    KnowledgeBase,
                    KnowledgeBase.id == Document.knowledge_base_id,
                )
                .where(Document.id == document.document_id)
                .with_for_update()
            ).one_or_none()
            if tenant is None:
                raise IndexingError(
                    "INDEX_DOCUMENT_NOT_FOUND",
                    "The document cannot be indexed because it no longer exists.",
                )
            knowledge_base_id, workspace_id = tenant
            existing = db.scalars(
                select(IndexedChunk)
                .where(IndexedChunk.document_id == document.document_id)
                .with_for_update()
            ).all()
            current_by_key = {
                (row.chunk_id, row.embedding_config_hash): row for row in existing
            }
            retained_keys = {
                (chunk.chunk_id, document.embedding_config_hash)
                for chunk in document.chunks
            }
            for chunk in document.chunks:
                key = (chunk.chunk_id, document.embedding_config_hash)
                row = current_by_key.get(key)
                if row is None:
                    row = IndexedChunk(
                        document_id=document.document_id,
                        chunk_id=chunk.chunk_id,
                        embedding_config_hash=document.embedding_config_hash,
                    )
                    db.add(row)
                row.workspace_id = workspace_id
                row.knowledge_base_id = knowledge_base_id
                row.chunk_index = chunk.chunk_index
                row.chunk_text = chunk.text
                row.content_hash = chunk.content_hash
                row.embedding_provider = document.embedding_provider
                row.embedding_model = document.embedding_model
                row.embedding_dimensions = document.embedding_dimensions
                row.embedding = list(chunk.vector)
                row.source_object_key = document.source_object_key
                row.source_storage_version = document.source_storage_version

            for row in existing:
                if (row.chunk_id, row.embedding_config_hash) not in retained_keys:
                    db.delete(row)

        return IndexWriteResult(
            document_id=document.document_id,
            chunk_count=len(document.chunks),
            embedding_config_hash=document.embedding_config_hash,
        )
