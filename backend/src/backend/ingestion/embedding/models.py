"""Versioned embedding artifact with chunk identity and model provenance."""

import math
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.ingestion.parsing.models import NonEmptyString

EMBEDDED_DOCUMENT_SCHEMA_VERSION = 1


class EmbeddingConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: NonEmptyString
    model: NonEmptyString
    dimensions: int = Field(gt=0, le=8192)
    batch_size: int = Field(gt=0, le=250)
    task_type: Literal["RETRIEVAL_DOCUMENT"] = "RETRIEVAL_DOCUMENT"


class ChunkEmbedding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_index: int = Field(ge=0)
    chunk_id: UUID
    source_content_hash: str = Field(min_length=64, max_length=64)
    vector: tuple[float, ...] = Field(min_length=1)
    dimensions: int = Field(gt=0, le=8192)

    @model_validator(mode="after")
    def validate_vector(self) -> Self:
        if len(self.vector) != self.dimensions:
            raise ValueError("embedding vector dimensions do not match")
        if not all(math.isfinite(value) for value in self.vector):
            raise ValueError("embedding vector values must be finite")
        return self


class EmbeddingStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_count: int = Field(ge=1)
    dimensions: int = Field(gt=0, le=8192)
    batch_count: int = Field(ge=1)


class EmbeddedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[EMBEDDED_DOCUMENT_SCHEMA_VERSION] = (
        EMBEDDED_DOCUMENT_SCHEMA_VERSION
    )
    document_id: UUID
    source_chunked_object_key: NonEmptyString
    source_chunked_storage_version: str | None = None
    chunked_schema_version: int = Field(ge=1)
    configuration: EmbeddingConfiguration
    configuration_hash: str = Field(min_length=64, max_length=64)
    embeddings: tuple[ChunkEmbedding, ...] = Field(min_length=1)
    warnings: tuple[NonEmptyString, ...] = ()
    statistics: EmbeddingStatistics

    @model_validator(mode="after")
    def validate_embeddings_and_statistics(self) -> Self:
        indexes = [embedding.chunk_index for embedding in self.embeddings]
        if indexes != list(range(len(self.embeddings))):
            raise ValueError(
                "embedding indexes must be contiguous and ordered from zero"
            )
        if self.statistics.chunk_count != len(self.embeddings):
            raise ValueError("statistics chunk_count does not match embeddings")
        if self.statistics.dimensions != self.configuration.dimensions:
            raise ValueError("statistics dimensions do not match configuration")
        if any(
            embedding.dimensions != self.configuration.dimensions
            for embedding in self.embeddings
        ):
            raise ValueError("embedding dimensions do not match configuration")
        expected_batches = (
            len(self.embeddings) + self.configuration.batch_size - 1
        ) // self.configuration.batch_size
        if self.statistics.batch_count != expected_batches:
            raise ValueError("statistics batch_count does not match embeddings")
        return self
