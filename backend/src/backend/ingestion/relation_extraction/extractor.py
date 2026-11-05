"""Vertex AI relation provider and deterministic document validation."""

import hashlib
import json
import re
from typing import Protocol
from uuid import UUID, uuid5

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import ValidationError

from backend.ingestion.chunking import ChunkedDocument, DocumentChunk
from backend.ingestion.relation_extraction.interface import (
    RelationExtractionError,
    RelationExtractionProvider,
    RelationExtractionTransientError,
)
from backend.ingestion.relation_extraction.models import (
    DEFAULT_ENTITY_TYPES,
    DEFAULT_RELATION_TYPES,
    CandidateChunkExtraction,
    ChunkRelations,
    ExtractedEntity,
    ExtractedRelation,
    RelationExtractedDocument,
    RelationExtractionConfiguration,
    RelationExtractionStatistics,
)

ENTITY_NAMESPACE = UUID("46dfa34a-8a4a-5f78-9105-8702d35dc73c")
RELATION_NAMESPACE = UUID("77bbc420-9a3d-56ea-a16e-39b509528662")
TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class RelationModels(Protocol):
    def generate_content(self, *, model, contents, config): ...


class RelationClient(Protocol):
    models: RelationModels


class VertexAIRelationProvider:
    """Generate a strict candidate relation payload for one chunk."""

    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        model_name: str,
        timeout_seconds: float,
        client: RelationClient | None = None,
    ) -> None:
        if not project_id.strip() or not location.strip() or not model_name.strip():
            raise ValueError("Vertex AI project, location, and model are required")
        if timeout_seconds <= 0:
            raise ValueError("relation extraction timeout must be positive")
        self._model_name = model_name
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

    def extract(
        self,
        text: str,
        *,
        allowed_entity_types: tuple[str, ...],
        allowed_relation_types: tuple[str, ...],
    ) -> CandidateChunkExtraction:
        if not text.strip():
            raise RelationExtractionError(
                "RELATION_INPUT_INVALID",
                "Relation extraction input must contain nonempty text.",
            )
        prompt = self._prompt(
            text,
            allowed_entity_types=allowed_entity_types,
            allowed_relation_types=allowed_relation_types,
        )
        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=CandidateChunkExtraction,
                ),
            )
        except genai_errors.ServerError as error:
            raise RelationExtractionTransientError(
                "RELATION_PROVIDER_UNAVAILABLE",
                "The relation extraction provider is temporarily unavailable.",
            ) from error
        except genai_errors.ClientError as error:
            if getattr(error, "code", None) == 429:
                raise RelationExtractionTransientError(
                    "RELATION_PROVIDER_RATE_LIMITED",
                    "The relation extraction provider rate limit was reached.",
                ) from error
            raise RelationExtractionError(
                "RELATION_PROVIDER_CONFIGURATION_INVALID",
                "The relation extraction provider rejected the configured request.",
            ) from error
        except (TimeoutError, ConnectionError) as error:
            raise RelationExtractionTransientError(
                "RELATION_PROVIDER_UNAVAILABLE",
                "The relation extraction provider could not be reached.",
            ) from error

        parsed = getattr(response, "parsed", None)
        try:
            if isinstance(parsed, CandidateChunkExtraction):
                return parsed
            if parsed is not None:
                return CandidateChunkExtraction.model_validate(parsed)
            response_text = getattr(response, "text", None)
            if not isinstance(response_text, str):
                raise ValueError("missing response text")
            return CandidateChunkExtraction.model_validate_json(response_text)
        except (ValidationError, ValueError, TypeError) as error:
            raise RelationExtractionError(
                "RELATION_PROVIDER_OUTPUT_INVALID",
                "The relation extraction provider returned malformed output.",
            ) from error

    @staticmethod
    def _prompt(
        text: str,
        *,
        allowed_entity_types: tuple[str, ...],
        allowed_relation_types: tuple[str, ...],
    ) -> str:
        return (
            "Extract only relationships explicitly stated in the source text. "
            "Use exact entity names and copy a short exact evidence span from the "
            "source for every relation. Do not infer unstated facts. Relation "
            "endpoints are zero-based indexes into entities. Return no entities or "
            "relations when the text contains no supported fact.\n\n"
            f"Allowed entity types: {', '.join(allowed_entity_types)}\n"
            f"Allowed relation types: {', '.join(allowed_relation_types)}\n\n"
            f"Source text:\n{text}"
        )


class DocumentRelationExtractor:
    """Extract and deterministically validate relations for every source chunk."""

    def __init__(
        self,
        provider: RelationExtractionProvider,
        *,
        allowed_entity_types: tuple[str, ...] = DEFAULT_ENTITY_TYPES,
        allowed_relation_types: tuple[str, ...] = DEFAULT_RELATION_TYPES,
    ) -> None:
        try:
            self.configuration = RelationExtractionConfiguration(
                provider=provider.provider_name,
                model=provider.model_name,
                allowed_entity_types=self._normalize_allowed(allowed_entity_types),
                allowed_relation_types=self._normalize_allowed(allowed_relation_types),
            )
        except ValidationError as error:
            raise RelationExtractionError(
                "RELATION_PROVIDER_CONFIGURATION_INVALID",
                "Relation extraction configuration is invalid.",
            ) from error
        if not self.configuration.allowed_entity_types:
            raise RelationExtractionError(
                "RELATION_PROVIDER_CONFIGURATION_INVALID",
                "At least one entity type must be configured.",
            )
        if not self.configuration.allowed_relation_types:
            raise RelationExtractionError(
                "RELATION_PROVIDER_CONFIGURATION_INVALID",
                "At least one relation type must be configured.",
            )
        self._provider = provider

    def extract_document(
        self,
        document: ChunkedDocument,
        *,
        source_object_key: str,
        source_storage_version: str | None,
    ) -> RelationExtractedDocument:
        if not source_object_key.strip() or not document.chunks:
            raise RelationExtractionError(
                "RELATION_INPUT_INVALID",
                "A persisted chunk artifact with chunks is required.",
            )
        chunks = tuple(
            self._extract_chunk(document.document_id, chunk)
            for chunk in document.chunks
        )
        configuration_hash = hashlib.sha256(
            json.dumps(
                self.configuration.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return RelationExtractedDocument(
            document_id=document.document_id,
            source_chunked_object_key=source_object_key,
            source_chunked_storage_version=source_storage_version,
            chunked_schema_version=document.schema_version,
            configuration=self.configuration,
            configuration_hash=configuration_hash,
            chunks=chunks,
            statistics=RelationExtractionStatistics(
                chunk_count=len(chunks),
                entity_count=sum(len(chunk.entities) for chunk in chunks),
                relation_count=sum(len(chunk.relations) for chunk in chunks),
                dropped_entity_count=sum(
                    chunk.dropped_entity_count for chunk in chunks
                ),
                dropped_relation_count=sum(
                    chunk.dropped_relation_count for chunk in chunks
                ),
            ),
        )

    def _extract_chunk(self, document_id: UUID, chunk: DocumentChunk) -> ChunkRelations:
        candidate = self._provider.extract(
            chunk.text,
            allowed_entity_types=tuple(self.configuration.allowed_entity_types),
            allowed_relation_types=tuple(self.configuration.allowed_relation_types),
        )
        allowed_entities = set(self.configuration.allowed_entity_types)
        allowed_relations = set(self.configuration.allowed_relation_types)
        normalized_text = self._normalize_text(chunk.text).casefold()
        entities: list[ExtractedEntity] = []
        entity_by_key: dict[tuple[str, str], ExtractedEntity] = {}
        candidate_entities: dict[int, ExtractedEntity] = {}
        dropped_entities = 0
        warning_codes: set[str] = set()

        for index, raw_entity in enumerate(candidate.entities):
            name = self._normalize_text(raw_entity.name)
            entity_type = self._normalize_type(raw_entity.type)
            if (
                not name
                or entity_type not in allowed_entities
                or name.casefold() not in normalized_text
            ):
                dropped_entities += 1
                warning_codes.add("DROPPED_UNGROUNDED_OR_UNSUPPORTED_ENTITY")
                continue
            key = (entity_type, name.casefold())
            entity = entity_by_key.get(key)
            if entity is None:
                entity = ExtractedEntity(
                    entity_id=uuid5(
                        ENTITY_NAMESPACE,
                        f"{document_id}:{chunk.chunk_id}:{entity_type}:{name.casefold()}",
                    ),
                    name=name,
                    type=entity_type,
                )
                entity_by_key[key] = entity
                entities.append(entity)
            else:
                dropped_entities += 1
                warning_codes.add("DROPPED_DUPLICATE_ENTITY")
            candidate_entities[index] = entity

        relations: list[ExtractedRelation] = []
        seen_relations: set[tuple[UUID, str, UUID, str]] = set()
        dropped_relations = 0
        for raw_relation in candidate.relations:
            source = candidate_entities.get(raw_relation.source_entity_index)
            target = candidate_entities.get(raw_relation.target_entity_index)
            relation_type = self._normalize_type(raw_relation.type)
            evidence = self._normalize_text(raw_relation.evidence)
            if (
                source is None
                or target is None
                or source.entity_id == target.entity_id
                or relation_type not in allowed_relations
                or not evidence
                or evidence.casefold() not in normalized_text
            ):
                dropped_relations += 1
                warning_codes.add("DROPPED_INVALID_OR_UNGROUNDED_RELATION")
                continue
            key = (
                source.entity_id,
                relation_type,
                target.entity_id,
                evidence.casefold(),
            )
            if key in seen_relations:
                dropped_relations += 1
                warning_codes.add("DROPPED_DUPLICATE_RELATION")
                continue
            seen_relations.add(key)
            relations.append(
                ExtractedRelation(
                    relation_id=uuid5(
                        RELATION_NAMESPACE,
                        ":".join(str(value) for value in key),
                    ),
                    source_entity_id=source.entity_id,
                    target_entity_id=target.entity_id,
                    type=relation_type,
                    evidence=evidence,
                    confidence=raw_relation.confidence,
                )
            )

        return ChunkRelations(
            chunk_index=chunk.chunk_index,
            chunk_id=chunk.chunk_id,
            source_content_hash=chunk.content_hash,
            entities=tuple(entities),
            relations=tuple(relations),
            dropped_entity_count=dropped_entities,
            dropped_relation_count=dropped_relations,
            warnings=tuple(sorted(warning_codes)),
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def _normalize_type(value: str) -> str:
        normalized = re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")
        return normalized if TYPE_PATTERN.fullmatch(normalized) else ""

    @classmethod
    def _normalize_allowed(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(cls._normalize_type(value) for value in values)
        return tuple(dict.fromkeys(value for value in normalized if value))
