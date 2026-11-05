"""Validate the persisted relation artifact before graph storage."""

from pydantic import ValidationError

from backend.ingestion.graph_storage import (
    GraphStorageError,
    GraphStore,
    GraphWriteResult,
)
from backend.ingestion.relation_extraction import RelationExtractedDocument
from backend.ingestion.stages.extract_relations import RelationsArtifact
from backend.object_storage import ObjectStorage, ObjectVersionMismatchError


class GraphStoreStage:
    def __init__(self, graph_store: GraphStore, storage: ObjectStorage) -> None:
        self._graph_store = graph_store
        self._storage = storage

    def execute(self, artifact: RelationsArtifact) -> GraphWriteResult:
        try:
            content = self._storage.read_object(
                artifact.object_key,
                version=artifact.storage_version,
            )
            persisted = RelationExtractedDocument.model_validate_json(content)
        except (
            FileNotFoundError,
            ObjectVersionMismatchError,
            ValidationError,
        ) as error:
            raise GraphStorageError(
                "GRAPH_INPUT_INVALID",
                "The persisted relation artifact is missing or invalid.",
            ) from error
        if persisted != artifact.document:
            raise GraphStorageError(
                "GRAPH_PROVENANCE_MISMATCH",
                "The in-memory and persisted relation artifacts do not match.",
            )
        return self._graph_store.write(persisted)
