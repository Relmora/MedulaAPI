"""Validated document embedding and the Vertex AI provider adapter."""

import hashlib
import json
from collections.abc import Sequence
from typing import Protocol

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import ValidationError

from backend.ingestion.chunking import ChunkedDocument
from backend.ingestion.embedding.interface import (
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingTransientError,
)
from backend.ingestion.embedding.models import (
    ChunkEmbedding,
    EmbeddedDocument,
    EmbeddingConfiguration,
    EmbeddingStatistics,
)


class EmbeddingModels(Protocol):
    def embed_content(self, *, model, contents, config): ...


class EmbeddingClient(Protocol):
    models: EmbeddingModels


class VertexAIEmbeddingProvider:
    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        model_name: str,
        dimensions: int,
        timeout_seconds: float,
        client: EmbeddingClient | None = None,
    ) -> None:
        if not project_id.strip() or not location.strip() or not model_name.strip():
            raise ValueError("Vertex AI project, location, and model are required")
        if dimensions <= 0 or timeout_seconds <= 0:
            raise ValueError("embedding dimensions and timeout must be positive")
        self._model_name = model_name
        self._dimensions = dimensions
        self._client = client or genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
            http_options=genai_types.HttpOptions(
                api_version="v1",
                timeout=int(timeout_seconds * 1000),
            ),
        )

    @property
    def provider_name(self) -> str:
        return "vertex-ai"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not texts or any(not text.strip() for text in texts):
            raise EmbeddingError(
                "EMBED_INPUT_INVALID",
                "Embedding input must contain nonempty text.",
            )
        try:
            response = self._client.models.embed_content(
                model=self.model_name,
                contents=list(texts),
                config=genai_types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=self.dimensions,
                    auto_truncate=False,
                ),
            )
        except genai_errors.ServerError as error:
            raise EmbeddingTransientError(
                "EMBED_PROVIDER_UNAVAILABLE",
                "The embedding provider is temporarily unavailable.",
            ) from error
        except genai_errors.ClientError as error:
            if getattr(error, "code", None) == 429:
                raise EmbeddingTransientError(
                    "EMBED_PROVIDER_RATE_LIMITED",
                    "The embedding provider rate limit was reached.",
                ) from error
            raise EmbeddingError(
                "EMBED_PROVIDER_CONFIGURATION_INVALID",
                "The embedding provider rejected the configured request.",
            ) from error
        except (TimeoutError, ConnectionError) as error:
            raise EmbeddingTransientError(
                "EMBED_PROVIDER_UNAVAILABLE",
                "The embedding provider could not be reached.",
            ) from error

        response_embeddings: Sequence[object] | None = getattr(
            response, "embeddings", None
        )
        if response_embeddings is None:
            raise EmbeddingError(
                "EMBED_PROVIDER_OUTPUT_INVALID",
                "The embedding provider returned malformed output.",
            )
        vectors: list[tuple[float, ...]] = []
        for embedding in response_embeddings:
            values = getattr(embedding, "values", None)
            if values is None:
                raise EmbeddingError(
                    "EMBED_PROVIDER_OUTPUT_INVALID",
                    "The embedding provider returned malformed output.",
                )
            try:
                vectors.append(tuple(float(value) for value in values))
            except (TypeError, ValueError) as error:
                raise EmbeddingError(
                    "EMBED_PROVIDER_OUTPUT_INVALID",
                    "The embedding provider returned malformed output.",
                ) from error
        return tuple(vectors)


class DocumentEmbedder:
    def __init__(
        self,
        provider: EmbeddingProvider,
        *,
        batch_size: int,
    ) -> None:
        try:
            self.configuration = EmbeddingConfiguration(
                provider=provider.provider_name,
                model=provider.model_name,
                dimensions=provider.dimensions,
                batch_size=batch_size,
            )
        except ValidationError as error:
            raise EmbeddingError(
                "EMBED_PROVIDER_CONFIGURATION_INVALID",
                "Embedding configuration is invalid.",
            ) from error
        self._provider = provider

    def embed_document(
        self,
        document: ChunkedDocument,
        *,
        source_object_key: str,
        source_storage_version: str | None,
    ) -> EmbeddedDocument:
        if not source_object_key.strip():
            raise EmbeddingError(
                "EMBED_INPUT_INVALID",
                "The chunked artifact object key is missing.",
            )
        if not document.chunks:
            raise EmbeddingError("EMBED_NO_CHUNKS", "No chunks are available.")

        configuration_json = json.dumps(
            self.configuration.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        configuration_hash = hashlib.sha256(
            configuration_json.encode("utf-8")
        ).hexdigest()
        embeddings: list[ChunkEmbedding] = []
        for start in range(0, len(document.chunks), self.configuration.batch_size):
            chunks = document.chunks[start : start + self.configuration.batch_size]
            vectors = self._provider.embed(tuple(chunk.text for chunk in chunks))
            if len(vectors) != len(chunks):
                raise EmbeddingError(
                    "EMBED_PROVIDER_OUTPUT_INVALID",
                    "The embedding provider returned an unexpected result count.",
                )
            for chunk, vector in zip(chunks, vectors, strict=True):
                if len(vector) != self.configuration.dimensions:
                    raise EmbeddingError(
                        "EMBED_DIMENSION_MISMATCH",
                        "The embedding provider returned unexpected dimensions.",
                    )
                try:
                    embeddings.append(
                        ChunkEmbedding(
                            chunk_index=chunk.chunk_index,
                            chunk_id=chunk.chunk_id,
                            source_content_hash=chunk.content_hash,
                            vector=vector,
                            dimensions=self.configuration.dimensions,
                        )
                    )
                except ValidationError as error:
                    raise EmbeddingError(
                        "EMBED_PROVIDER_OUTPUT_INVALID",
                        "The embedding provider returned invalid numeric values.",
                    ) from error

        return EmbeddedDocument(
            document_id=document.document_id,
            source_chunked_object_key=source_object_key,
            source_chunked_storage_version=source_storage_version,
            chunked_schema_version=document.schema_version,
            configuration=self.configuration,
            configuration_hash=configuration_hash,
            embeddings=tuple(embeddings),
            warnings=document.warnings,
            statistics=EmbeddingStatistics(
                chunk_count=len(embeddings),
                dimensions=self.configuration.dimensions,
                batch_count=(len(embeddings) + self.configuration.batch_size - 1)
                // self.configuration.batch_size,
            ),
        )
