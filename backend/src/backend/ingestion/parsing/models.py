"""Versioned, parser-independent representation of extracted structure."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

PARSED_DOCUMENT_SCHEMA_VERSION = 1

NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
BlockType = Literal[
    "heading",
    "paragraph",
    "list_item",
    "table",
    "code",
    "caption",
    "page_header",
    "page_footer",
]


class BoundingBox(BaseModel):
    """Optional source coordinates, in the parser's declared coordinate space."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    left: float
    top: float
    right: float
    bottom: float

    @model_validator(mode="after")
    def validate_extents(self) -> Self:
        if self.right < self.left or self.bottom < self.top:
            raise ValueError("bounding box extents must be ordered")
        return self


class ParsedBlock(BaseModel):
    """One ordered structural unit with source provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    block_index: int = Field(ge=0)
    block_type: BlockType
    text: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    section_path: tuple[NonEmptyString, ...] = ()
    bounding_box: BoundingBox | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ParseStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_count: int = Field(ge=1)
    extracted_character_count: int = Field(ge=1)


class ParsedDocument(BaseModel):
    """Stable artifact schema consumed by normalization and chunking."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[PARSED_DOCUMENT_SCHEMA_VERSION] = (
        PARSED_DOCUMENT_SCHEMA_VERSION
    )
    document_id: UUID
    source_storage_version: str | None = None
    parser_name: NonEmptyString
    parser_version: NonEmptyString
    content_type: NonEmptyString
    page_count: int | None = Field(default=None, ge=1)
    blocks: tuple[ParsedBlock, ...] = Field(min_length=1)
    warnings: tuple[NonEmptyString, ...] = ()
    statistics: ParseStatistics

    @model_validator(mode="after")
    def validate_blocks_and_statistics(self) -> Self:
        actual_indexes = [block.block_index for block in self.blocks]
        expected_indexes = list(range(len(self.blocks)))
        if actual_indexes != expected_indexes:
            raise ValueError("block indexes must be contiguous and ordered from zero")

        if self.statistics.block_count != len(self.blocks):
            raise ValueError("statistics block_count does not match blocks")
        extracted_character_count = sum(len(block.text) for block in self.blocks)
        if self.statistics.extracted_character_count != extracted_character_count:
            raise ValueError(
                "statistics extracted_character_count does not match blocks"
            )
        return self
