from typing import Literal

from pydantic import AnyHttpUrl, SecretStr
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )
