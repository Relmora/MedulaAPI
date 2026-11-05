"""Strict versioned models for relation-extraction input and artifacts."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.ingestion.parsing.models import NonEmptyString

RELATION_EXTRACTED_DOCUMENT_SCHEMA_VERSION = 1
DEFAULT_ENTITY_TYPES = (
    "PERSON",
    "ORGANIZATION",
    "LOCATION",
    "PROJECT",
    "PRODUCT",
    "TECHNOLOGY",
    "EVENT",
    "DOCUMENT",
    "CONCEPT",
    "ROLE",
    "OTHER",
)
DEFAULT_RELATION_TYPES = (
    "CREATED",
    "WORKS_AT",
    "LOCATED_IN",
    "PART_OF",
    "USES",
    "OWNS",
    "DEVELOPED_BY",
    "RELATED_TO",
    "HAS_ROLE",
    "MENTIONS",
    "PARTICIPATED_IN",
    "OCCURRED_AT",
    "LEADS",
)


class CandidateEntity(BaseModel):
    """Untrusted structured entity returned by the LLM provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=64)


class CandidateRelation(BaseModel):
    """Untrusted relationship using indexes into the candidate entity list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_entity_index: int = Field(ge=0)
    target_entity_index: int = Field(ge=0)
    type: str = Field(min_length=1, max_length=64)
    evidence: str = Field(min_length=1, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)


class CandidateChunkExtraction(BaseModel):
    """Provider response parsed before deterministic validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entities: tuple[CandidateEntity, ...] = ()
    relations: tuple[CandidateRelation, ...] = ()


class RelationExtractionConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: NonEmptyString
    model: NonEmptyString
    prompt_version: NonEmptyString = "v1"
    allowed_entity_types: tuple[NonEmptyString, ...] = DEFAULT_ENTITY_TYPES
    allowed_relation_types: tuple[NonEmptyString, ...] = DEFAULT_RELATION_TYPES


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: UUID
    name: NonEmptyString
    type: NonEmptyString


class ExtractedRelation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relation_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    type: NonEmptyString
    evidence: NonEmptyString
    confidence: float | None = Field(default=None, ge=0, le=1)


class ChunkRelations(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_index: int = Field(ge=0)
    chunk_id: UUID
    source_content_hash: str = Field(min_length=64, max_length=64)
    entities: tuple[ExtractedEntity, ...] = ()
    relations: tuple[ExtractedRelation, ...] = ()
    dropped_entity_count: int = Field(default=0, ge=0)
    dropped_relation_count: int = Field(default=0, ge=0)
    warnings: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def validate_relation_endpoints(self) -> Self:
        entity_ids = {entity.entity_id for entity in self.entities}
        if len(entity_ids) != len(self.entities):
            raise ValueError("entity identifiers must be unique within a chunk")
        relation_ids = {relation.relation_id for relation in self.relations}
        if len(relation_ids) != len(self.relations):
            raise ValueError("relation identifiers must be unique within a chunk")
        if any(
            relation.source_entity_id not in entity_ids
            or relation.target_entity_id not in entity_ids
            for relation in self.relations
        ):
            raise ValueError("relation endpoints must reference extracted entities")
        return self


class RelationExtractionStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_count: int = Field(ge=1)
    entity_count: int = Field(ge=0)
    relation_count: int = Field(ge=0)
    dropped_entity_count: int = Field(ge=0)
    dropped_relation_count: int = Field(ge=0)


class RelationExtractedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[RELATION_EXTRACTED_DOCUMENT_SCHEMA_VERSION] = (
        RELATION_EXTRACTED_DOCUMENT_SCHEMA_VERSION
    )
    document_id: UUID
    source_chunked_object_key: NonEmptyString
    source_chunked_storage_version: str | None = None
    chunked_schema_version: int = Field(ge=1)
    configuration: RelationExtractionConfiguration
    configuration_hash: str = Field(min_length=64, max_length=64)
    chunks: tuple[ChunkRelations, ...] = Field(min_length=1)
    statistics: RelationExtractionStatistics

    @model_validator(mode="after")
    def validate_chunks_and_statistics(self) -> Self:
        indexes = [chunk.chunk_index for chunk in self.chunks]
        if indexes != list(range(len(self.chunks))):
            raise ValueError("relation chunk indexes must be contiguous and ordered")
        if self.statistics.chunk_count != len(self.chunks):
            raise ValueError("statistics chunk_count does not match chunks")
        totals = {
            "entity_count": sum(len(chunk.entities) for chunk in self.chunks),
            "relation_count": sum(len(chunk.relations) for chunk in self.chunks),
            "dropped_entity_count": sum(
                chunk.dropped_entity_count for chunk in self.chunks
            ),
            "dropped_relation_count": sum(
                chunk.dropped_relation_count for chunk in self.chunks
            ),
        }
        if any(getattr(self.statistics, key) != value for key, value in totals.items()):
            raise ValueError("relation extraction statistics do not match chunks")
        return self
