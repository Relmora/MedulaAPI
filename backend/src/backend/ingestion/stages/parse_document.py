"""Parse validated source bytes and persist the versioned JSON artifact."""

from dataclasses import dataclass

from backend.ingestion.parsing.models import ParsedDocument
from backend.ingestion.parsing.registry import ParserRegistry
from backend.ingestion.stages.validate_source import ValidatedSource
from backend.object_storage import ObjectStorage

PARSED_CONTENT_TYPE = "application/json"


@dataclass(frozen=True)
class ParsedArtifact:
    document: ParsedDocument
    object_key: str
    storage_version: str | None


class ParseStage:
    def __init__(self, registry: ParserRegistry, storage: ObjectStorage) -> None:
        self._registry = registry
        self._storage = storage

    def execute(self, source: ValidatedSource) -> ParsedArtifact:
        parser = self._registry.resolve(source.content_type)
        parsed = parser.parse(source)
        object_key = self.object_key(source)
        content = parsed.model_dump_json(indent=2).encode("utf-8")
        metadata = self._storage.write_object(
            object_key,
            content,
            content_type=PARSED_CONTENT_TYPE,
        )
        return ParsedArtifact(
            document=parsed,
            object_key=object_key,
            storage_version=metadata.version,
        )

    @staticmethod
    def object_key(source: ValidatedSource) -> str:
        version = source.storage_version or "unversioned"
        return f"documents/{source.document_id}/parsed/{version}.json"
