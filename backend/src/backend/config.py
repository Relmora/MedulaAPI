from pydantic import AnyHttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    cors_allowed_origins: list[AnyHttpUrl] = [AnyHttpUrl("http://localhost:5173")]

    db_host: str = "::1"
    db_port: int = 5432
    db_name: str = "MedullaAPI"
    db_user: str = "medula_app"
    db_password: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )
