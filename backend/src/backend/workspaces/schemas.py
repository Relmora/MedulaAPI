from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

WorkspaceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: WorkspaceName


class WorkspaceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: WorkspaceName


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class WorkspaceListResponse(BaseModel):
    items: list[WorkspaceResponse]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)
