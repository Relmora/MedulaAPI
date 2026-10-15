import pytest
from pydantic import ValidationError

from backend.config import Settings


def test_default_origin(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    settings = Settings(_env_file=None)

    assert [str(origin).rstrip("/") for origin in settings.cors_allowed_origins] == [
        "http://localhost:5173"
    ]


def test_origins_from_environment(monkeypatch):
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        '["https://app.example.com","http://localhost:5173"]',
    )

    settings = Settings(_env_file=None)

    assert [str(origin).rstrip("/") for origin in settings.cors_allowed_origins] == [
        "https://app.example.com",
        "http://localhost:5173",
    ]


def test_invalid_origin_is_rejected(monkeypatch):
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        '["not-a-url"]',
    )

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
