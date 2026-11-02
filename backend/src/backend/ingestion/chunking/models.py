"""Versioned chunk artifact with exact normalized-block provenance."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.ingestion.parsing.models import BoundingBox, NonEmptyString

CHUNKED_DOCUMENT_SCHEMA_VERSION = 1


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_chunk_characters: int = Field(default=1500, gt=0)
    overlap_characters: int = Field(default=200, ge=0)
    separator: str = "\n\n"

    @model_validator(mode="after")
    def validate_overlap(self) -> Self:
        if self.overlap_characters >= self.max_chunk_characters:
            raise ValueError(
                "overlap_characters must be less than max_chunk_characters"
            )
        return self


class ChunkSourceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_block_index: int = Field(ge=0)
    normalized_start_offset: int = Field(ge=0)
    normalized_end_offset: int = Field(gt=0)
    page_number: int | None = Field(default=None, ge=1)
    bounding_box: BoundingBox | None = None

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.normalized_end_offset <= self.normalized_start_offset:
            raise ValueError("normalized source span must be nonempty")
        return self


class DocumentChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_index: int = Field(ge=0)
    chunk_id: UUID
    text: str = Field(min_length=1)
    section_path: tuple[NonEmptyString, ...] = ()
    source_spans: tuple[ChunkSourceSpan, ...] = Field(min_length=1)
    page_numbers: tuple[int, ...] = ()
    character_count: int = Field(gt=0)
    content_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if not self.text.strip():
            raise ValueError("chunk text must contain useful text")
        if self.character_count != len(self.text):
            raise ValueError("character_count does not match chunk text")
        if tuple(sorted(set(self.page_numbers))) != self.page_numbers:
            raise ValueError("page_numbers must be sorted and unique")
        return self


class ChunkingStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_block_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    minimum_chunk_characters: int = Field(gt=0)
    maximum_chunk_characters: int = Field(gt=0)
    average_chunk_characters: float = Field(gt=0)


class ChunkedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[CHUNKED_DOCUMENT_SCHEMA_VERSION] = (
        CHUNKED_DOCUMENT_SCHEMA_VERSION
    )
    document_id: UUID
    source_normalized_object_key: NonEmptyString
    source_normalized_storage_version: str | None = None
    normalized_schema_version: int = Field(ge=1)
    chunker_name: NonEmptyString
    chunker_version: NonEmptyString
    configuration: ChunkingConfig
    configuration_hash: str = Field(min_length=64, max_length=64)
    chunks: tuple[DocumentChunk, ...] = Field(min_length=1)
    warnings: tuple[NonEmptyString, ...] = ()
    statistics: ChunkingStatistics

    @model_validator(mode="after")
    def validate_chunks_and_statistics(self) -> Self:
        indexes = [chunk.chunk_index for chunk in self.chunks]
        if indexes != list(range(len(self.chunks))):
            raise ValueError("chunk indexes must be contiguous and ordered from zero")
        if self.statistics.chunk_count != len(self.chunks):
            raise ValueError("statistics chunk_count does not match chunks")
        sizes = [chunk.character_count for chunk in self.chunks]
        if self.statistics.minimum_chunk_characters != min(sizes):
            raise ValueError(
                "statistics minimum_chunk_characters does not match chunks"
            )
        if self.statistics.maximum_chunk_characters != max(sizes):
            raise ValueError(
                "statistics maximum_chunk_characters does not match chunks"
            )
        expected_average = sum(sizes) / len(sizes)
        if abs(self.statistics.average_chunk_characters - expected_average) > 1e-9:
            raise ValueError(
                "statistics average_chunk_characters does not match chunks"
            )
        return self
