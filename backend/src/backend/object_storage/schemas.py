"""Values exchanged between document services and storage adapters."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UploadInstructions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1)
    method: Literal["PUT", "POST"]
    headers: dict[str, str] = Field(default_factory=dict)
    form_fields: dict[str, str] | None = None
    expires_at: datetime


class StoredObjectMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    size_bytes: int = Field(ge=0)
    content_type: str | None = None
    version: str | None = None
    checksum: str | None = None
    checksum_algorithm: str | None = None
