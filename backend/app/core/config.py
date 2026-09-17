from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration object for the application.

    Values are loaded from environment variables (or a .env file during
    local development). This class only DECLARES what configuration the
    app needs — it does not know HOW those values will be used
    (e.g. which ASR SDK to call). That decision belongs to the
    infrastructure layer, which will read `settings.asr_provider` and
    pick the right adapter.
    """

    # --- Application environment ---
    # Distinguishes local/dev/staging/prod behavior (e.g. logging verbosity,
    # debug flags) without hard-coding environment-specific logic anywhere else.
    app_env: str = "development"

    # --- Provider selectors (string identifiers only) ---
    # These are NOT the provider SDKs or clients themselves — just the name
    # of which provider is currently active. Infrastructure code will use
    # this string to decide which concrete adapter to instantiate.
    # This is what keeps the system provider-agnostic: swapping providers
    # means changing this one value, not touching business logic.
    asr_provider: str = "not_configured"
    llm_provider: str = "not_configured"

    # --- Datastore connection strings ---
    # Stored as plain strings here; the infrastructure layer is responsible
    # for parsing/using them. config.py does not open connections.
    database_url: str = "not_configured"
    redis_url: str = "not_configured"

    # Tells Pydantic Settings to also look for values in a file named
    # ".env" sitting in the working directory, in addition to real
    # environment variables. Real env vars (e.g. set by Docker/CI) always
    # take priority over .env file values.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.

    lru_cache ensures the .env file / environment is only read and
    validated ONCE per process, and the same Settings object is reused
    everywhere it's requested — instead of re-parsing environment
    variables on every import or every function call.
    """
    return Settings()


settings = get_settings()