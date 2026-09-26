from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

class Settings(BaseSettings):
    app_env: str = "development"

    asr_provider: str = "not_configured"
    llm_provider: str = "not_configured"
    database_url: str = "not_configured"
    redis_url: str = "not_configured"

    groq_api_key: str = "not_configured"
    groq_model: str = "openai/gpt-oss-20b"
    sarvam_api_key: str = "not_configured"
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_stt_model: str = "saaras:v3"
    sarvam_timeout_seconds: float = 30.0
    sarvam_input_audio_codec: str | None = None
    language_provider: str = "not_configured"
    diarization_enabled: bool = True
    diarization_provider: str = "not_configured"
    role_provider: str = "not_configured"
    pyannote_model: str = "pyannote/speaker-diarization-community-1"
    huggingface_token: str = ""
    summary_provider: str = "rule_based"
    redis_key_prefix: str = "conversation_coverage"
    redis_ttl_seconds: float = 86400.0
    redis_socket_timeout_seconds: float = 5.0
    auth_secret_key: str = "not_configured"
    auth_access_token_expire_minutes: int = 30
    coverage_store_provider: str = "in_memory"

    telephony_provider: str = "plivo"
    plivo_auth_id: str = "not_configured"
    plivo_auth_token: str = "not_configured"
    plivo_validate_signatures: bool = True
    plivo_stream_base_url: str = "not_configured"
    plivo_public_base_url: str = ""
    plivo_stream_flush_seconds: float = 4.0
    call_mapping_store_provider: str = "in_memory"
    call_mapping_key_prefix: str = "telephony_call_mapping"
    customer_summary_enabled: bool = False
    customer_summary_delivery_provider: str = "disabled"
    customer_summary_default_channel: str = "sms"
    customer_summary_consent_required: bool = True
    customer_summary_sms_provider: str = "disabled"
    customer_summary_sms_sender_id: str = ""
    customer_summary_sms_timeout_seconds: float = 10.0
    customer_summary_sms_retry_attempts: int = 0
    customer_summary_whatsapp_provider: str = "disabled"
    customer_summary_whatsapp_sender_id: str = ""
    customer_summary_whatsapp_timeout_seconds: float = 10.0
    customer_summary_whatsapp_retry_attempts: int = 0

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()