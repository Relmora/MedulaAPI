import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from google.genai import errors as genai_errors

from backend.ingestion.chunking import (
    ChunkedDocument,
    ChunkingConfig,
    ChunkingStatistics,
    ChunkSourceSpan,
    DocumentChunk,
)
from backend.ingestion.relation_extraction import (
    CandidateChunkExtraction,
    CandidateEntity,
    CandidateRelation,
    DocumentRelationExtractor,
    RelationExtractionError,
    RelationExtractionTransientError,
    VertexAIRelationProvider,
)
from backend.ingestion.stages import (
    ChunkedArtifact,
    IndexedArtifact,
    RelationExtractStage,
)
from backend.object_storage.fake import FakeObjectStorage


def chunked_document(*texts: str) -> ChunkedDocument:
    chunks = tuple(
        DocumentChunk(
            chunk_index=index,
            chunk_id=uuid4(),
            text=text,
            source_spans=(
                ChunkSourceSpan(
                    source_block_index=index,
                    normalized_start_offset=0,
                    normalized_end_offset=len(text),
                ),
            ),
            character_count=len(text),
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        for index, text in enumerate(texts)
    )
    sizes = [len(text) for text in texts]
    return ChunkedDocument(
        document_id=uuid4(),
        source_normalized_object_key="normalized.json",
        source_normalized_storage_version="3",
        normalized_schema_version=1,
        chunker_name="test",
        chunker_version="1",
        configuration=ChunkingConfig(),
        configuration_hash="a" * 64,
        chunks=chunks,
        statistics=ChunkingStatistics(
            source_block_count=len(chunks),
            chunk_count=len(chunks),
            minimum_chunk_characters=min(sizes),
            maximum_chunk_characters=max(sizes),
            average_chunk_characters=sum(sizes) / len(sizes),
        ),
    )


class FakeProvider:
    provider_name = "fake"
    model_name = "fake-relations-v1"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def extract(self, text, *, allowed_entity_types, allowed_relation_types):
        self.calls.append((text, allowed_entity_types, allowed_relation_types))
        return self.outputs.pop(0)


def valid_candidates() -> CandidateChunkExtraction:
    return CandidateChunkExtraction(
        entities=(
            CandidateEntity(name="Sanjay", type="person"),
            CandidateEntity(name="MedulaAPI", type="project"),
        ),
        relations=(
            CandidateRelation(
                source_entity_index=0,
                target_entity_index=1,
                type="created",
                evidence="Sanjay created MedulaAPI",
                confidence=0.98,
            ),
        ),
    )


def test_extractor_produces_stable_grounded_entities_and_relations():
    source = chunked_document("Sanjay created MedulaAPI in 2026.")
    provider = FakeProvider([valid_candidates(), valid_candidates()])
    extractor = DocumentRelationExtractor(provider)

    first = extractor.extract_document(
        source,
        source_object_key="chunks.json",
        source_storage_version="7",
    )
    repeated = extractor.extract_document(
        source,
        source_object_key="chunks.json",
        source_storage_version="7",
    )

    assert first == repeated
    assert first.statistics.entity_count == 2
    assert first.statistics.relation_count == 1
    assert first.chunks[0].entities[0].name == "Sanjay"
    relation = first.chunks[0].relations[0]
    assert relation.type == "CREATED"
    assert relation.evidence == "Sanjay created MedulaAPI"
    assert relation.source_entity_id == first.chunks[0].entities[0].entity_id
    assert relation.target_entity_id == first.chunks[0].entities[1].entity_id


def test_extractor_drops_unsupported_unstructured_and_duplicate_results():
    source = chunked_document("Sanjay created MedulaAPI.")
    candidates = CandidateChunkExtraction(
        entities=(
            CandidateEntity(name="Sanjay", type="PERSON"),
            CandidateEntity(name="MedulaAPI", type="PROJECT"),
            CandidateEntity(name="Sanjay", type="PERSON"),
            CandidateEntity(name="Unknown", type="PERSON"),
        ),
        relations=(
            CandidateRelation(
                source_entity_index=0,
                target_entity_index=1,
                type="CREATED",
                evidence="Sanjay created MedulaAPI",
            ),
            CandidateRelation(
                source_entity_index=0,
                target_entity_index=1,
                type="CREATED",
                evidence="Sanjay created MedulaAPI",
            ),
            CandidateRelation(
                source_entity_index=0,
                target_entity_index=1,
                type="UNSUPPORTED",
                evidence="Sanjay created MedulaAPI",
            ),
            CandidateRelation(
                source_entity_index=0,
                target_entity_index=1,
                type="CREATED",
                evidence="invented evidence",
            ),
            CandidateRelation(
                source_entity_index=0,
                target_entity_index=99,
                type="CREATED",
                evidence="Sanjay created MedulaAPI",
            ),
        ),
    )

    result = DocumentRelationExtractor(FakeProvider([candidates])).extract_document(
        source,
        source_object_key="chunks.json",
        source_storage_version="1",
    )

    assert result.statistics.entity_count == 2
    assert result.statistics.relation_count == 1
    assert result.statistics.dropped_entity_count == 2
    assert result.statistics.dropped_relation_count == 4
    assert set(result.chunks[0].warnings) == {
        "DROPPED_DUPLICATE_ENTITY",
        "DROPPED_DUPLICATE_RELATION",
        "DROPPED_INVALID_OR_UNGROUNDED_RELATION",
        "DROPPED_UNGROUNDED_OR_UNSUPPORTED_ENTITY",
    }


def test_extractor_accepts_an_empty_grounded_result():
    source = chunked_document("A paragraph without a supported relation.")

    result = DocumentRelationExtractor(
        FakeProvider([CandidateChunkExtraction()])
    ).extract_document(
        source,
        source_object_key="chunks.json",
        source_storage_version="1",
    )

    assert result.statistics.entity_count == 0
    assert result.statistics.relation_count == 0
    assert result.chunks[0].entities == ()
    assert result.chunks[0].relations == ()


def test_relation_stage_validates_provenance_and_writes_versioned_artifact():
    storage = FakeObjectStorage()
    source = chunked_document("Sanjay created MedulaAPI.")
    source_key = f"documents/{source.document_id}/chunked/4/chunks.json"
    metadata = storage.write_object(
        source_key,
        source.model_dump_json().encode(),
        content_type="application/json",
    )
    chunked = ChunkedArtifact(
        document=source,
        object_key=source_key,
        storage_version=metadata.version,
    )
    indexed = IndexedArtifact(
        document_id=source.document_id,
        chunk_count=1,
        embedding_config_hash="b" * 64,
    )

    artifact = RelationExtractStage(
        DocumentRelationExtractor(FakeProvider([valid_candidates()])),
        storage,
    ).execute(indexed, chunked)

    assert artifact.storage_version == "1"
    assert artifact.object_key.startswith(
        f"documents/{source.document_id}/relations/1/fake-fake-relations-v1-"
    )
    stored = json.loads(storage.object_contents[artifact.object_key])
    assert stored["schema_version"] == 1
    assert stored["statistics"]["relation_count"] == 1


def test_relation_stage_rejects_index_and_chunk_provenance_mismatch():
    storage = FakeObjectStorage()
    source = chunked_document("Sanjay created MedulaAPI.")
    source_key = "chunks.json"
    metadata = storage.write_object(
        source_key,
        source.model_dump_json().encode(),
        content_type="application/json",
    )
    chunked = ChunkedArtifact(source, source_key, metadata.version)
    indexed = IndexedArtifact(uuid4(), 1, "a" * 64)

    with pytest.raises(RelationExtractionError) as raised:
        RelationExtractStage(
            DocumentRelationExtractor(FakeProvider([valid_candidates()])),
            storage,
        ).execute(indexed, chunked)

    assert raised.value.code == "RELATION_PROVENANCE_MISMATCH"


class RecordingModels:
    def __init__(self, *, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def vertex_provider(models: RecordingModels) -> VertexAIRelationProvider:
    return VertexAIRelationProvider(
        project_id="project",
        location="global",
        model_name="relation-model",
        timeout_seconds=10,
        client=SimpleNamespace(models=models),
    )


def test_vertex_provider_requests_strict_json_output():
    models = RecordingModels(result=SimpleNamespace(parsed=valid_candidates()))

    result = vertex_provider(models).extract(
        "Sanjay created MedulaAPI.",
        allowed_entity_types=("PERSON", "PROJECT"),
        allowed_relation_types=("CREATED",),
    )

    assert result == valid_candidates()
    call = models.calls[0]
    assert call["model"] == "relation-model"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema is CandidateChunkExtraction
    assert "Sanjay created MedulaAPI" in call["contents"]


@pytest.mark.parametrize(
    ("error", "expected_type", "code"),
    [
        (
            genai_errors.ClientError(429, {"message": "private provider text"}),
            RelationExtractionTransientError,
            "RELATION_PROVIDER_RATE_LIMITED",
        ),
        (
            genai_errors.ServerError(503, {"message": "private provider text"}),
            RelationExtractionTransientError,
            "RELATION_PROVIDER_UNAVAILABLE",
        ),
        (
            genai_errors.ClientError(400, {"message": "private provider text"}),
            RelationExtractionError,
            "RELATION_PROVIDER_CONFIGURATION_INVALID",
        ),
    ],
)
def test_vertex_provider_classifies_failures_without_leaking_details(
    error,
    expected_type,
    code,
):
    with pytest.raises(expected_type) as raised:
        vertex_provider(RecordingModels(error=error)).extract(
            "private source text",
            allowed_entity_types=("PERSON",),
            allowed_relation_types=("RELATED_TO",),
        )

    assert raised.value.code == code
    assert "private provider text" not in str(raised.value)
    assert "private source text" not in str(raised.value)


def test_vertex_provider_rejects_malformed_output():
    models = RecordingModels(result=SimpleNamespace(text="not-json", parsed=None))

    with pytest.raises(RelationExtractionError) as raised:
        vertex_provider(models).extract(
            "source text",
            allowed_entity_types=("PERSON",),
            allowed_relation_types=("RELATED_TO",),
        )

    assert raised.value.code == "RELATION_PROVIDER_OUTPUT_INVALID"
