"""Normalize a parsed document and persist its versioned JSON artifact."""

from dataclasses import dataclass

from backend.ingestion.normalization import NormalizedDocument, Normalizer
from backend.ingestion.parsing import ParsedDocument
from backend.object_storage import ObjectStorage

NORMALIZED_CONTENT_TYPE = "application/json"


@dataclass(frozen=True)
class NormalizedArtifact:
    document: NormalizedDocument
    object_key: str
    storage_version: str | None


class NormalizeStage:
    def __init__(self, normalizer: Normalizer, storage: ObjectStorage) -> None:
        self._normalizer = normalizer
        self._storage = storage

    def execute(self, parsed: ParsedDocument) -> NormalizedArtifact:
        normalized = self._normalizer.normalize(parsed)
        object_key = self.object_key(normalized)
        content = normalized.model_dump_json(indent=2).encode("utf-8")
        metadata = self._storage.write_object(
            object_key,
            content,
            content_type=NORMALIZED_CONTENT_TYPE,
        )
        return NormalizedArtifact(
            document=normalized,
            object_key=object_key,
            storage_version=metadata.version,
        )

    @staticmethod
    def object_key(document: NormalizedDocument) -> str:
        source_version = document.source_storage_version or "unversioned"
        return (
            f"documents/{document.document_id}/normalized/{source_version}/"
            f"{document.normalizer_name}-v{document.normalizer_version}.json"
        )
