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


def test_default_embedding_settings():
    settings = Settings(_env_file=None)

    assert settings.embedding_provider == "vertex_ai"
    assert settings.embedding_model == "gemini-embedding-001"
    assert settings.embedding_dimensions == 768
    assert settings.embedding_batch_size == 1
    assert settings.embedding_location == "global"
    assert settings.embedding_timeout_seconds == 30


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("embedding_dimensions", 0),
        ("embedding_dimensions", 3073),
        ("embedding_batch_size", 0),
        ("embedding_batch_size", 251),
        ("embedding_timeout_seconds", 0),
    ],
)
def test_invalid_embedding_settings_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
