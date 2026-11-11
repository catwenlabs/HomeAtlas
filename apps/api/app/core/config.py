"""Application settings assembled from environment variables (and optional .env)."""

from functools import lru_cache

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

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
