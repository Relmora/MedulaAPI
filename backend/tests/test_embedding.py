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
from backend.ingestion.embedding import (
    DocumentEmbedder,
    EmbeddingError,
    EmbeddingTransientError,
    VertexAIEmbeddingProvider,
)
from backend.ingestion.stages import ChunkedArtifact, EmbedStage
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
        source_normalized_storage_version="4",
        normalized_schema_version=1,
        chunker_name="test",
        chunker_version="1",
        configuration=ChunkingConfig(),
        configuration_hash="0" * 64,
        chunks=chunks,
        warnings=("chunk warning",),
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
    model_name = "fake-embedding-v1"
    dimensions = 3

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        return tuple(
            (float(len(text)), float(index), 1.0) for index, text in enumerate(texts)
        )


def test_document_embedder_batches_in_order_and_preserves_chunk_identity():
    source = chunked_document("first", "second", "third")
    provider = FakeProvider()

    embedded = DocumentEmbedder(provider, batch_size=2).embed_document(
        source,
        source_object_key="chunked.json",
        source_storage_version="7",
    )

    assert provider.calls == [("first", "second"), ("third",)]
    assert embedded.source_chunked_object_key == "chunked.json"
    assert embedded.source_chunked_storage_version == "7"
    assert embedded.configuration.provider == "fake"
    assert embedded.configuration.model == "fake-embedding-v1"
    assert embedded.configuration.dimensions == 3
    assert embedded.statistics.batch_count == 2
    assert [item.chunk_id for item in embedded.embeddings] == [
        chunk.chunk_id for chunk in source.chunks
    ]
    assert [item.source_content_hash for item in embedded.embeddings] == [
        chunk.content_hash for chunk in source.chunks
    ]
    repeated = DocumentEmbedder(FakeProvider(), batch_size=2).embed_document(
        source,
        source_object_key="chunked.json",
        source_storage_version="7",
    )
    assert embedded.configuration_hash == repeated.configuration_hash


@pytest.mark.parametrize(
    ("vectors", "code"),
    [
        ((), "EMBED_PROVIDER_OUTPUT_INVALID"),
        (((1.0, 2.0),), "EMBED_DIMENSION_MISMATCH"),
        (((1.0, float("nan"), 3.0),), "EMBED_PROVIDER_OUTPUT_INVALID"),
        (((1.0, float("inf"), 3.0),), "EMBED_PROVIDER_OUTPUT_INVALID"),
    ],
)
def test_document_embedder_rejects_invalid_provider_output(vectors, code):
    class InvalidProvider(FakeProvider):
        def embed(self, texts):
            return vectors

    with pytest.raises(EmbeddingError) as raised:
        DocumentEmbedder(InvalidProvider(), batch_size=1).embed_document(
            chunked_document("text"),
            source_object_key="chunked.json",
            source_storage_version="1",
        )

    assert raised.value.code == code


def test_embedding_configuration_rejects_invalid_batch_size():
    with pytest.raises(EmbeddingError) as raised:
        DocumentEmbedder(FakeProvider(), batch_size=0)

    assert raised.value.code == "EMBED_PROVIDER_CONFIGURATION_INVALID"


def test_embed_stage_validates_source_and_uploads_versioned_artifact():
    storage = FakeObjectStorage()
    source = chunked_document("first", "second")
    source_key = f"documents/{source.document_id}/chunked/4/chunks.json"
    metadata = storage.write_object(
        source_key,
        source.model_dump_json().encode(),
        content_type="application/json",
    )
    source_artifact = ChunkedArtifact(
        document=source,
        object_key=source_key,
        storage_version=metadata.version,
    )

    artifact = EmbedStage(
        DocumentEmbedder(FakeProvider(), batch_size=2), storage
    ).execute(source_artifact)

    assert artifact.storage_version == "1"
    assert artifact.object_key.startswith(
        f"documents/{source.document_id}/embedded/1/fake-fake-embedding-v1-"
    )
    stored = json.loads(storage.object_contents[artifact.object_key])
    assert stored["schema_version"] == 1
    assert stored["statistics"]["chunk_count"] == 2
    assert stored["configuration"]["dimensions"] == 3


def test_embed_stage_rejects_corrupt_chunked_artifact():
    storage = FakeObjectStorage()
    source = chunked_document("text")
    source_key = f"documents/{source.document_id}/chunked/corrupt.json"
    storage.write_object(source_key, b"not-json", content_type="application/json")

    with pytest.raises(EmbeddingError) as raised:
        EmbedStage(DocumentEmbedder(FakeProvider(), batch_size=1), storage).execute(
            ChunkedArtifact(
                document=source,
                object_key=source_key,
                storage_version="1",
            )
        )

    assert raised.value.code == "EMBED_INPUT_INVALID"


def test_embed_stage_rejects_chunked_artifact_that_differs_from_memory():
    storage = FakeObjectStorage()
    source = chunked_document("expected")
    different_source = source.model_copy(
        update={"warnings": ("different persisted artifact",)}
    )
    source_key = f"documents/{source.document_id}/chunked/mismatch.json"
    metadata = storage.write_object(
        source_key,
        different_source.model_dump_json().encode(),
        content_type="application/json",
    )

    with pytest.raises(EmbeddingError) as raised:
        EmbedStage(DocumentEmbedder(FakeProvider(), batch_size=1), storage).execute(
            ChunkedArtifact(
                document=source,
                object_key=source_key,
                storage_version=metadata.version,
            )
        )

    assert raised.value.code == "EMBED_INPUT_INVALID"


class RecordingModels:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.calls = []

    def embed_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def vertex_provider(models: RecordingModels) -> VertexAIEmbeddingProvider:
    return VertexAIEmbeddingProvider(
        project_id="project",
        location="global",
        model_name="gemini-embedding-001",
        dimensions=3,
        timeout_seconds=10,
        client=SimpleNamespace(models=models),
    )


def test_vertex_provider_uses_retrieval_document_without_truncation():
    models = RecordingModels(
        result=SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 2.0, 3.0])])
    )

    vectors = vertex_provider(models).embed(("document text",))

    assert vectors == ((1.0, 2.0, 3.0),)
    call = models.calls[0]
    assert call["model"] == "gemini-embedding-001"
    assert call["contents"] == ["document text"]
    assert call["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert call["config"].output_dimensionality == 3
    assert call["config"].auto_truncate is False


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(),
        SimpleNamespace(embeddings=[SimpleNamespace(values=None)]),
        SimpleNamespace(embeddings=[SimpleNamespace(values=["not-a-number"])]),
    ],
)
def test_vertex_provider_rejects_malformed_output(result):
    with pytest.raises(EmbeddingError) as raised:
        vertex_provider(RecordingModels(result=result)).embed(("document text",))

    assert raised.value.code == "EMBED_PROVIDER_OUTPUT_INVALID"


@pytest.mark.parametrize(
    ("error", "expected_type", "code"),
    [
        (
            genai_errors.ClientError(429, {"message": "secret response"}),
            EmbeddingTransientError,
            "EMBED_PROVIDER_RATE_LIMITED",
        ),
        (
            genai_errors.ServerError(503, {"message": "secret response"}),
            EmbeddingTransientError,
            "EMBED_PROVIDER_UNAVAILABLE",
        ),
        (
            genai_errors.ClientError(400, {"message": "secret response"}),
            EmbeddingError,
            "EMBED_PROVIDER_CONFIGURATION_INVALID",
        ),
    ],
)
def test_vertex_provider_classifies_failures_without_exposing_response(
    error,
    expected_type,
    code,
):
    with pytest.raises(expected_type) as raised:
        vertex_provider(RecordingModels(error=error)).embed(("private text",))

    assert raised.value.code == code
    assert "secret response" not in str(raised.value)
    assert "private text" not in str(raised.value)
