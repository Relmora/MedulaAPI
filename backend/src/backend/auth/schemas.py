from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: SecretStr

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not 3 <= len(value) <= 64 or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789_.-" for char in value
        ):
            raise ValueError("Username must be 3-64 ASCII letters, digits, _, . or -.")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        if not 15 <= len(value.get_secret_value()) <= 128:
            raise ValueError("Password must be 15-128 characters.")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    created_at: datetime
