"""Extract validated relations from the exact chunks written to the index."""

from dataclasses import dataclass

from pydantic import ValidationError

from backend.ingestion.chunking import ChunkedDocument
from backend.ingestion.relation_extraction import (
    RelationExtractedDocument,
    RelationExtractionError,
    RelationExtractor,
)
from backend.ingestion.stages.chunk_document import ChunkedArtifact
from backend.ingestion.stages.index_document import IndexedArtifact
from backend.object_storage import ObjectStorage, ObjectVersionMismatchError

RELATIONS_CONTENT_TYPE = "application/json"


@dataclass(frozen=True)
class RelationsArtifact:
    document: RelationExtractedDocument
    object_key: str
    storage_version: str | None


class RelationExtractStage:
    def __init__(self, extractor: RelationExtractor, storage: ObjectStorage) -> None:
        self._extractor = extractor
        self._storage = storage

    def execute(
        self,
        indexed: IndexedArtifact,
        chunked: ChunkedArtifact,
    ) -> RelationsArtifact:
        try:
            content = self._storage.read_object(
                chunked.object_key,
                version=chunked.storage_version,
            )
            source = ChunkedDocument.model_validate_json(content)
        except (
            FileNotFoundError,
            ObjectVersionMismatchError,
            ValidationError,
        ) as error:
            raise RelationExtractionError(
                "RELATION_INPUT_INVALID",
                "The persisted chunked artifact is missing or invalid.",
            ) from error
        if (
            source != chunked.document
            or source.document_id != indexed.document_id
            or len(source.chunks) != indexed.chunk_count
        ):
            raise RelationExtractionError(
                "RELATION_PROVENANCE_MISMATCH",
                "The indexed and chunked artifacts have inconsistent provenance.",
            )
        extracted = self._extractor.extract_document(
            source,
            source_object_key=chunked.object_key,
            source_storage_version=chunked.storage_version,
        )
        object_key = self.object_key(extracted)
        metadata = self._storage.write_object(
            object_key,
            extracted.model_dump_json(indent=2).encode("utf-8"),
            content_type=RELATIONS_CONTENT_TYPE,
        )
        return RelationsArtifact(
            document=extracted,
            object_key=object_key,
            storage_version=metadata.version,
        )

    @staticmethod
    def object_key(document: RelationExtractedDocument) -> str:
        source_version = document.source_chunked_storage_version or "unversioned"
        provider = document.configuration.provider.replace("/", "-")
        model = document.configuration.model.replace("/", "-")
        return (
            f"documents/{document.document_id}/relations/{source_version}/"
            f"{provider}-{model}-{document.configuration_hash}.json"
        )
