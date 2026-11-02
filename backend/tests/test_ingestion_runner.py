from backend.config import Settings
from backend.ingestion import runner
from backend.ingestion.chunking import BlockAwareChunker
from backend.ingestion.parsing import MarkdownParser, PdfParser, PlainTextParser
from backend.ingestion.runner import (
    build_chunker,
    build_embedder,
    build_parser_registry,
)


def test_production_registry_contains_all_phase_one_parsers():
    registry = build_parser_registry()

    assert isinstance(registry.resolve("application/pdf"), PdfParser)
    assert isinstance(registry.resolve("text/markdown"), MarkdownParser)
    assert isinstance(registry.resolve("text/plain"), PlainTextParser)


def test_production_worker_uses_the_phase_one_chunker_defaults():
    chunker = build_chunker()

    assert isinstance(chunker, BlockAwareChunker)
    assert chunker.config.max_chunk_characters == 1500
    assert chunker.config.overlap_characters == 200
    assert chunker.config.separator == "\n\n"


def test_production_embedder_uses_explicit_vertex_settings(monkeypatch):
    captured = {}

    class FakeVertexProvider:
        provider_name = "vertex-ai"

        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.model_name = kwargs["model_name"]
            self.dimensions = kwargs["dimensions"]

        def embed(self, texts):
            return ()

    monkeypatch.setattr(runner, "VertexAIEmbeddingProvider", FakeVertexProvider)
    settings = Settings(
        _env_file=None,
        gcp_project_id="project",
        embedding_model="embedding-model",
        embedding_dimensions=512,
        embedding_batch_size=4,
        embedding_location="global",
        embedding_timeout_seconds=15,
    )

    embedder = build_embedder(settings)

    assert embedder.configuration.provider == "vertex-ai"
    assert embedder.configuration.model == "embedding-model"
    assert embedder.configuration.dimensions == 512
    assert embedder.configuration.batch_size == 4
    assert captured == {
        "project_id": "project",
        "location": "global",
        "model_name": "embedding-model",
        "dimensions": 512,
        "timeout_seconds": 15.0,
    }


def test_production_embedder_requires_gcp_project():
    settings = Settings(_env_file=None, gcp_project_id=None)

    try:
        build_embedder(settings)
    except ValueError as error:
        assert (
            str(error) == "GCP_PROJECT_ID must be configured for Vertex AI embeddings"
        )
    else:
        raise AssertionError("build_embedder accepted a missing GCP project")
