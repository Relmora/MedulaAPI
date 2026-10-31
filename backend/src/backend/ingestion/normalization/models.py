"""Versioned, provenance-preserving normalized document representation."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from backend.ingestion.parsing.models import BlockType, BoundingBox, NonEmptyString

NORMALIZED_DOCUMENT_SCHEMA_VERSION = 1


class NormalizedBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_index: int = Field(ge=0)
    source_block_index: int = Field(ge=0)
    block_type: BlockType
    text: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    section_path: tuple[NonEmptyString, ...] = ()
    bounding_box: BoundingBox | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class NormalizationStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_block_count: int = Field(ge=1)
    block_count: int = Field(ge=1)
    removed_block_count: int = Field(ge=0)
    normalized_character_count: int = Field(ge=1)


class NormalizedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[NORMALIZED_DOCUMENT_SCHEMA_VERSION] = (
        NORMALIZED_DOCUMENT_SCHEMA_VERSION
    )
    document_id: UUID
    source_storage_version: str | None = None
    parsed_schema_version: int = Field(ge=1)
    normalizer_name: NonEmptyString
    normalizer_version: NonEmptyString
    blocks: tuple[NormalizedBlock, ...] = Field(min_length=1)
    warnings: tuple[NonEmptyString, ...] = ()
    statistics: NormalizationStatistics

    @model_validator(mode="after")
    def validate_blocks_and_statistics(self) -> Self:
        indexes = [block.block_index for block in self.blocks]
        if indexes != list(range(len(self.blocks))):
            raise ValueError("block indexes must be contiguous and ordered from zero")
        if self.statistics.block_count != len(self.blocks):
            raise ValueError("statistics block_count does not match blocks")
        if (
            self.statistics.source_block_count - self.statistics.block_count
            != self.statistics.removed_block_count
        ):
            raise ValueError("statistics removed_block_count does not match blocks")
        character_count = sum(len(block.text) for block in self.blocks)
        if self.statistics.normalized_character_count != character_count:
            raise ValueError(
                "statistics normalized_character_count does not match blocks"
            )
        return self
