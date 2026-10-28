from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    cors_allowed_origins: list[AnyHttpUrl] = [AnyHttpUrl("http://localhost:5173")]

    log_level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "INFO"

    auth_signing_key: SecretStr = SecretStr("")
    auth_cookie_secure: bool = True
    auth_allowed_origins: list[AnyHttpUrl] = [
        AnyHttpUrl("http://localhost:5173"),
        AnyHttpUrl("http://localhost:8000"),
        AnyHttpUrl("http://127.0.0.1:8000"),
    ]

    registration_enabled: bool = False

    storage_provider: Literal["gcs"] = "gcs"
    storage_bucket: str = ""
    gcp_project_id: str | None = None

    db_host: str = "::1"
    db_port: int = 5432
    db_name: str = "MedullaAPI"
    db_user: str = "medula_app"
    db_password: SecretStr = SecretStr("")

    rabbitmq_host: str = "127.0.0.1"
    rabbitmq_port: int = 5672
    rabbitmq_username: str = "medula_app"
    rabbitmq_password: SecretStr = SecretStr("")
    rabbitmq_vhost: str = "medula"
    rabbitmq_tls: bool = False

    rabbitmq_exchange: str = "medulla.events"
    rabbitmq_ingestion_queue: str = "document.ingestion"
    rabbitmq_ingestion_routing_key: str = "document.ingestion.requested"

    outbox_publisher_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    outbox_publisher_batch_size: int = Field(default=50, gt=0, le=1000)
    outbox_publisher_claim_seconds: int = Field(default=30, gt=0, le=3600)
    outbox_publisher_error_backoff_seconds: float = Field(default=1.0, gt=0, le=60)
    outbox_publisher_max_error_backoff_seconds: float = Field(
        default=30.0, gt=0, le=300
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )
