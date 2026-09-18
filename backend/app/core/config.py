from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"

    asr_provider: str = "not_configured"
    llm_provider: str = "not_configured"
    database_url: str = "not_configured"
    redis_url: str = "not_configured"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()