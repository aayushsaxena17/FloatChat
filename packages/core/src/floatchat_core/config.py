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
