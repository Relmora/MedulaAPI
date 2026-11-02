"""Chunk a normalized document and persist its versioned JSON artifact."""

from dataclasses import dataclass

from pydantic import ValidationError

from backend.ingestion.chunking import ChunkedDocument, Chunker, ChunkingError
from backend.ingestion.normalization import NormalizedDocument
from backend.ingestion.stages.normalize_document import NormalizedArtifact
from backend.object_storage import ObjectStorage, ObjectVersionMismatchError

CHUNKED_CONTENT_TYPE = "application/json"


@dataclass(frozen=True)
class ChunkedArtifact:
    document: ChunkedDocument
    object_key: str
    storage_version: str | None


class ChunkStage:
    def __init__(self, chunker: Chunker, storage: ObjectStorage) -> None:
        self._chunker = chunker
        self._storage = storage

    def execute(self, normalized: NormalizedArtifact) -> ChunkedArtifact:
        try:
            content = self._storage.read_object(
                normalized.object_key,
                version=normalized.storage_version,
            )
            source_document = NormalizedDocument.model_validate_json(content)
        except (
            FileNotFoundError,
            ObjectVersionMismatchError,
            ValidationError,
        ) as error:
            raise ChunkingError(
                "CHUNK_PROVENANCE_INVALID",
                "The persisted normalized artifact is missing or invalid.",
            ) from error
        if source_document != normalized.document:
            raise ChunkingError(
                "CHUNK_PROVENANCE_INVALID",
                "The persisted normalized artifact does not match the stage input.",
            )
        chunked = self._chunker.chunk(
            source_document,
            source_object_key=normalized.object_key,
            source_storage_version=normalized.storage_version,
        )
        object_key = self.object_key(chunked)
        content = chunked.model_dump_json(indent=2).encode("utf-8")
        metadata = self._storage.write_object(
            object_key,
            content,
            content_type=CHUNKED_CONTENT_TYPE,
        )
        return ChunkedArtifact(
            document=chunked,
            object_key=object_key,
            storage_version=metadata.version,
        )

    @staticmethod
    def object_key(document: ChunkedDocument) -> str:
        source_version = document.source_normalized_storage_version or "unversioned"
        return (
            f"documents/{document.document_id}/chunked/{source_version}/"
            f"{document.chunker_name}-v{document.chunker_version}-"
            f"{document.configuration_hash}.json"
        )
