"""Validated client metadata used to create a document upload intent."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ALLOWED_DECLARED_CONTENT_TYPES = frozenset(
    {"application/pdf", "text/markdown", "text/plain"}
)

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
    declared_size_bytes: int = Field(gt=0)

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
