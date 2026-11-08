from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

KnowledgeBaseName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: KnowledgeBaseName


class KnowledgeBaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: KnowledgeBaseName


class KnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseListResponse(BaseModel):
    items: list[KnowledgeBaseResponse]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)


class KnowledgeBaseGraphNodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    entity_type: str


class KnowledgeBaseGraphEdgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source: UUID
    target: UUID
    predicate: str
    chunk_id: UUID


class KnowledgeBaseGraphResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_base_id: UUID
    nodes: list[KnowledgeBaseGraphNodeResponse]
    edges: list[KnowledgeBaseGraphEdgeResponse]
