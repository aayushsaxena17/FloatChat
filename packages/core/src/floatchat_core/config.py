from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: SecretStr
    redis_url: SecretStr
    object_storage_endpoint: str
    object_storage_access_key: SecretStr
    object_storage_secret_key: SecretStr
    object_storage_bucket: str = "floatchat-dev"
    object_storage_region: str = "us-east-1"
    readiness_timeout_seconds: float = Field(default=4.0, gt=0, le=4.0)
    # Stage 2 (ADR-0058): the read-only query login and the verified part cache. Both are
    # optional so the Stage 0 health endpoints keep working on a database without Stage 2.
    query_database_url: SecretStr | None = None
    query_object_cache_dir: str | None = None
    application_commit: str = "unknown"
