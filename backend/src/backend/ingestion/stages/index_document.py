"""Validate persisted embedding provenance and write the searchable index."""

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError

from backend.ingestion.chunking import ChunkedDocument
from backend.ingestion.embedding import EmbeddedDocument
from backend.ingestion.indexing import (
    IndexChunk,
    IndexDocument,
    IndexingError,
    VectorIndex,
)
from backend.ingestion.stages.embed_document import EmbeddedArtifact
from backend.object_storage import ObjectStorage, ObjectVersionMismatchError


@dataclass(frozen=True)
class IndexedArtifact:
    document_id: UUID
    chunk_count: int
    embedding_config_hash: str


class IndexStage:
    def __init__(self, vector_index: VectorIndex, storage: ObjectStorage) -> None:
        self._vector_index = vector_index
        self._storage = storage

    def execute(self, embedded: EmbeddedArtifact) -> IndexedArtifact:
        persisted_embedded = self._load_embedded(embedded)
        chunked = self._load_chunked(persisted_embedded)
        index_document = self._combine(
            embedded,
            persisted_embedded,
            chunked,
        )
        result = self._vector_index.replace_document(index_document)
        return IndexedArtifact(
            document_id=result.document_id,
            chunk_count=result.chunk_count,
            embedding_config_hash=result.embedding_config_hash,
        )

    def _load_embedded(self, embedded: EmbeddedArtifact) -> EmbeddedDocument:
        try:
            content = self._storage.read_object(
                embedded.object_key,
                version=embedded.storage_version,
            )
            persisted = EmbeddedDocument.model_validate_json(content)
        except (
            FileNotFoundError,
            ObjectVersionMismatchError,
            ValidationError,
        ) as error:
            raise IndexingError(
                "INDEX_INPUT_INVALID",
                "The persisted embedded artifact is missing or invalid.",
            ) from error
        if persisted != embedded.document:
            raise IndexingError(
                "INDEX_INPUT_INVALID",
                "The persisted embedded artifact does not match the stage input.",
            )
        return persisted

    def _load_chunked(self, embedded: EmbeddedDocument) -> ChunkedDocument:
        try:
            content = self._storage.read_object(
                embedded.source_chunked_object_key,
                version=embedded.source_chunked_storage_version,
            )
            return ChunkedDocument.model_validate_json(content)
        except (
            FileNotFoundError,
            ObjectVersionMismatchError,
            ValidationError,
        ) as error:
            raise IndexingError(
                "INDEX_INPUT_INVALID",
                "The source chunked artifact is missing or invalid.",
            ) from error

    @staticmethod
    def _combine(
        artifact: EmbeddedArtifact,
        embedded: EmbeddedDocument,
        chunked: ChunkedDocument,
    ) -> IndexDocument:
        configuration_json = json.dumps(
            embedded.configuration.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        configuration_hash = hashlib.sha256(
            configuration_json.encode("utf-8")
        ).hexdigest()
        if (
            embedded.document_id != chunked.document_id
            or embedded.chunked_schema_version != chunked.schema_version
            or len(embedded.embeddings) != len(chunked.chunks)
            or embedded.configuration_hash != configuration_hash
        ):
            raise IndexingError(
                "INDEX_PROVENANCE_MISMATCH",
                "The embedded and chunked artifacts have inconsistent provenance.",
            )
        records: list[IndexChunk] = []
        for embedding, chunk in zip(
            embedded.embeddings,
            chunked.chunks,
            strict=True,
        ):
            if (
                embedding.chunk_id != chunk.chunk_id
                or embedding.chunk_index != chunk.chunk_index
                or embedding.source_content_hash != chunk.content_hash
                or hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
                != chunk.content_hash
            ):
                raise IndexingError(
                    "INDEX_PROVENANCE_MISMATCH",
                    "The embedded and chunked artifacts have inconsistent provenance.",
                )
            records.append(
                IndexChunk(
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    content_hash=chunk.content_hash,
                    vector=embedding.vector,
                )
            )
        return IndexDocument(
            document_id=embedded.document_id,
            embedding_provider=embedded.configuration.provider,
            embedding_model=embedded.configuration.model,
            embedding_dimensions=embedded.configuration.dimensions,
            embedding_config_hash=embedded.configuration_hash,
            source_object_key=artifact.object_key,
            source_storage_version=artifact.storage_version,
            chunks=tuple(records),
        )
