import os
from typing import Optional
from pydantic import Field

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )

        MODEL_NAME_OR_PATH: str = Field(default="openai/whisper-large-v3-turbo")
        MODEL_BACKEND: str = Field(default="faster-whisper")  # "faster-whisper", "indic-conformer", "fake"
        DEVICE: str = Field(default="auto")  # "cuda", "cpu", "auto"
        COMPUTE_TYPE: str = Field(default="auto")  # "float16", "int8", "float32", "auto"
        SPEECH_SERVER_TOKEN: Optional[str] = Field(default=None)
        PORT: int = Field(default=8090)
        HOST: str = Field(default="0.0.0.0")
        MAX_CONCURRENT_TRANSCRIPTIONS: int = Field(default=10)

except ImportError:
    from pydantic import BaseModel

    class Settings(BaseModel):
        MODEL_NAME_OR_PATH: str = os.getenv("MODEL_NAME_OR_PATH", "openai/whisper-large-v3-turbo")
        MODEL_BACKEND: str = os.getenv("MODEL_BACKEND", "faster-whisper")
        DEVICE: str = os.getenv("DEVICE", "auto")
        COMPUTE_TYPE: str = os.getenv("COMPUTE_TYPE", "auto")
        SPEECH_SERVER_TOKEN: Optional[str] = os.getenv("SPEECH_SERVER_TOKEN") or None
        PORT: int = int(os.getenv("PORT", "8090"))
        HOST: str = os.getenv("HOST", "0.0.0.0")
        MAX_CONCURRENT_TRANSCRIPTIONS: int = int(os.getenv("MAX_CONCURRENT_TRANSCRIPTIONS", "10"))


settings = Settings()


def get_settings() -> Settings:
    return settings

