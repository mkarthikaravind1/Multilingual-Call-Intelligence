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
    # CPU threads for diarization (torch). Torch defaults to every core, which
    # oversubscribes the CPU and can make pyannote 20x+ slower; 0 keeps that default.
    diarization_cpu_threads: int = 4
    summary_provider: str = "rule_based"
    # "rule_based", or "llm" (the rules plus an LLM detector that can only add).
    escalation_provider: str = "rule_based"
    # Emerging-complaint discovery: "rule_based" (same wording across calls)
    # or "llm" (groups differently worded complaints).
    emerging_complaint_provider: str = "rule_based"
    # Re-run discovery in the background whenever a call completes.
    emerging_complaint_auto_discovery: bool = True
    # How many of the most recent completed calls one discovery run reads.
    emerging_complaint_discovery_max_calls: int = 200
    # Background runs start at most this often (a burst of completed calls
    # waits and is covered by one run). Manual runs are not limited.
    emerging_complaint_discovery_min_interval_seconds: float = 300.0
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
    # Live audio is sent for transcription when the speaker pauses: at least
    # PLIVO_STREAM_MIN_SPEECH_SECONDS of speech, then PLIVO_STREAM_PAUSE_SECONDS
    # quieter than PLIVO_STREAM_SILENCE_RMS (16-bit PCM level).
    # PLIVO_STREAM_FLUSH_SECONDS stays the upper limit; pause 0 = fixed chunks.
    plivo_stream_pause_seconds: float = 0.6
    plivo_stream_min_speech_seconds: float = 1.5
    plivo_stream_silence_rms: int = 350
    call_mapping_store_provider: str = "in_memory"
    call_mapping_key_prefix: str = "telephony_call_mapping"
    # CRM boundary: "none" (no CRM connected) or "json_file" (crm_json_path).
    crm_provider: str = "none"
    crm_json_path: str = ""
    # Prefixed to 10-digit national caller numbers so they match the CRM.
    phone_default_country_code: str = "91"
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
    # SMS Gateway for Android (customer_summary_delivery_provider=sms_gate).
    # Cloud relay by default; for the phone's local server use
    # http://<phone-ip>:8080/message.
    sms_gate_url: str = "https://api.sms-gate.app/3rdparty/v1/messages"
    sms_gate_username: str = ""
    sms_gate_password: str = ""
    sms_gate_sim_number: int | None = None
    sms_gate_ttl_seconds: int = 86400

    # --- Production readiness ---
    # Comma-separated browser origins allowed to call the API.
    cors_allowed_origins: str = "http://localhost:5173"
    # Logging: "text" for people, "json" for log collectors.
    log_level: str = "INFO"
    log_format: str = "text"
    # When set, GET /metrics requires "Authorization: Bearer <token>".
    metrics_token: str = ""
    # Where live state shared between API instances lives (open media
    # streams, speaker roles, job locks): "in_memory" (one instance) or "redis".
    live_state_store_provider: str = "in_memory"
    live_state_key_prefix: str = "live_state"
    # How long an active call's live analysis (sentiment, next question,
    # estimate) is kept without new speech.
    live_analysis_ttl_seconds: float = 14400.0
    # Browser live-call WebSockets authenticate with a single-use ticket
    # (POST /api/v1/calls/{call_id}/live-token), never the access token.
    live_call_ws_token_ttl_seconds: int = 60
    # How often an open live-call WebSocket checks for new analysis to push.
    live_call_push_interval_seconds: float = 0.5
    # Telephony media streams must present a signed per-call token.
    telephony_stream_auth_required: bool = True
    telephony_stream_token_ttl_seconds: int = 3600
    # Post-call repair: retries completed calls whose summary was never
    # produced. 0 disables the background sweep (manual retry still works).
    post_call_repair_interval_seconds: float = 300.0
    # A call must stay unprocessed this long before the sweep retries it, so
    # it never races the normal post-call processing.
    post_call_repair_min_age_seconds: float = 120.0
    post_call_repair_max_attempts: int = 5
    post_call_repair_scan_limit: int = 500
    # Creates this admin at startup when no user exists yet.
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()