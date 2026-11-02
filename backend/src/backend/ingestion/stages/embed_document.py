"""Embed a persisted chunked document and store its versioned artifact."""

from dataclasses import dataclass

from pydantic import ValidationError

from backend.ingestion.chunking import ChunkedDocument
from backend.ingestion.embedding import EmbeddedDocument, Embedder, EmbeddingError
from backend.ingestion.stages.chunk_document import ChunkedArtifact
from backend.object_storage import ObjectStorage, ObjectVersionMismatchError

EMBEDDED_CONTENT_TYPE = "application/json"


@dataclass(frozen=True)
class EmbeddedArtifact:
    document: EmbeddedDocument
    object_key: str
    storage_version: str | None


class EmbedStage:
    def __init__(self, embedder: Embedder, storage: ObjectStorage) -> None:
        self._embedder = embedder
        self._storage = storage

    def execute(self, chunked: ChunkedArtifact) -> EmbeddedArtifact:
        try:
            content = self._storage.read_object(
                chunked.object_key,
                version=chunked.storage_version,
            )
            source_document = ChunkedDocument.model_validate_json(content)
        except (
            FileNotFoundError,
            ObjectVersionMismatchError,
            ValidationError,
        ) as error:
            raise EmbeddingError(
                "EMBED_INPUT_INVALID",
                "The persisted chunked artifact is missing or invalid.",
            ) from error
        if source_document != chunked.document:
            raise EmbeddingError(
                "EMBED_INPUT_INVALID",
                "The persisted chunked artifact does not match the stage input.",
            )
        embedded = self._embedder.embed_document(
            source_document,
            source_object_key=chunked.object_key,
            source_storage_version=chunked.storage_version,
        )
        object_key = self.object_key(embedded)
        content = embedded.model_dump_json(indent=2).encode("utf-8")
        metadata = self._storage.write_object(
            object_key,
            content,
            content_type=EMBEDDED_CONTENT_TYPE,
        )
        return EmbeddedArtifact(
            document=embedded,
            object_key=object_key,
            storage_version=metadata.version,
        )

    @staticmethod
    def object_key(document: EmbeddedDocument) -> str:
        source_version = document.source_chunked_storage_version or "unversioned"
        provider = document.configuration.provider.replace("/", "-")
        model = document.configuration.model.replace("/", "-")
        return (
            f"documents/{document.document_id}/embedded/{source_version}/"
            f"{provider}-{model}-{document.configuration_hash}.json"
        )
