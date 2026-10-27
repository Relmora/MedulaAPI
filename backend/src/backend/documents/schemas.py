"""Validated values used by the document upload-intent API."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ALLOWED_DECLARED_CONTENT_TYPES = frozenset(
    {"application/pdf", "text/markdown", "text/plain"}
)
MAX_DOCUMENT_SIZE_BYTES = 25 * 1024 * 1024

OriginalFilename = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
DeclaredContentType = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
        max_length=127,
    ),
]


class DocumentUploadIntentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_filename: OriginalFilename
    declared_content_type: DeclaredContentType
    declared_size_bytes: int = Field(gt=0, le=MAX_DOCUMENT_SIZE_BYTES)

    @field_validator("original_filename")
    @classmethod
    def validate_original_filename(cls, value: str) -> str:
        if value in {".", ".."} or any(character in value for character in "/\\\0"):
            raise ValueError("original_filename must be a base filename")
        return value

    @field_validator("declared_content_type")
    @classmethod
    def validate_declared_content_type(cls, value: str) -> str:
        if value not in ALLOWED_DECLARED_CONTENT_TYPES:
            raise ValueError("declared_content_type is not supported")
        return value


class UploadInstructionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    method: Literal["PUT", "POST"]
    headers: dict[str, str]
    form_fields: dict[str, str] | None
    expires_at: datetime


class DocumentUploadIntentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    upload: UploadInstructionsResponse
