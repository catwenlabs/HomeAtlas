"""Application settings assembled from environment variables (and optional .env)."""

from functools import lru_cache
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "HomeAtlas API"
    app_env: str = "development"  # development | test | production
    api_v1_prefix: str = "/api/v1"
    log_level: str = "info"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "homeatlas"
    # Local development default only; deployments must set POSTGRES_PASSWORD via deploy/.env.
    postgres_password: str = "homeatlas"  # noqa: S105
    postgres_db: str = "home_atlas"

    # Data import (Phase 2B-1 sync skeleton). The directory is local to the API
    # process; Phase 2B-2 will move files to a shared worker volume.
    import_storage_dir: str = "/tmp/homeatlas-imports"  # noqa: S108
    import_max_file_mb: int = 10
    import_max_rows: int = 20000

    # Authentication (Phase 2A). Deployments must override JWT_SECRET_KEY.
    jwt_secret_key: str = "dev-insecure-change-me-at-least-32-bytes"  # noqa: S105
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @model_validator(mode="after")
    def _require_production_jwt_secret(self) -> Self:
        if self.app_env == "production" and (
            self.jwt_secret_key == "dev-insecure-change-me-at-least-32-bytes"  # noqa: S105
            or len(self.jwt_secret_key) < 32
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be a unique value of at least 32 characters "
                "when APP_ENV=production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
