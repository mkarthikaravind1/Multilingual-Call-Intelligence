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
    # GPT-OSS models reason before answering, and the reasoning counts
    # towards Groq's token limits: "low" keeps it short (also avoids empty
    # replies). Empty: Groq's default. Ignored for other models.
    groq_reasoning_effort: str = "low"
    # Retries on rate limits (429) and server errors, waiting as long as
    # Groq asks ("try again in ...") between them.
    groq_max_retries: int = 4
    sarvam_api_key: str = "not_configured"
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_stt_model: str = "saaras:v3"
    # saaras:v3 output mode. "codemix" keeps English words in Latin script
    # inside Indic text (the default "transcribe" spells them in the native
    # script, which hides English keywords such as "brake" from the
    # estimator). Empty: don't send a mode (needed for models without one).
    sarvam_stt_mode: str | None = "codemix"
    sarvam_timeout_seconds: float = 30.0
    # Live audio: once ASR_LANGUAGE_LOCK_AFTER chunks in a row of a speaker
    # are heard in the same Indian language, the ASR is told that language
    # instead of guessing it from each few-second chunk. Released after
    # ASR_LANGUAGE_UNLOCK_AFTER empty or other-language chunks in a row.
    # 0 turns it off.
    asr_language_lock_after: int = 2
    asr_language_unlock_after: int = 2
    # After the call, transcribe its recorded audio again in windows of up
    # to POST_CALL_RETRANSCRIPTION_WINDOW_SECONDS (Sarvam's limit is 30 s),
    # in each speaker's language, and keep that transcript instead of the
    # live one (which was heard a few seconds at a time). About doubles the
    # ASR cost of a call. Recordings stay in memory (on the instance that
    # streamed the call) until then: at most CALL_RECORDING_MAX_CALLS calls,
    # each cut at CALL_RECORDING_MAX_SECONDS.
    post_call_retranscription_enabled: bool = False
    post_call_retranscription_window_seconds: float = 25.0
    post_call_retranscription_workers: int = 4
    call_recording_max_seconds: float = 3600.0
    call_recording_max_calls: int = 20
    sarvam_input_audio_codec: str | None = None
    language_provider: str = "not_configured"
    diarization_enabled: bool = True
    diarization_provider: str = "not_configured"
    # Speaker roles (ICR / customer): "session" learns them per call (the
    # call's tracks when both sides are streamed separately, otherwise voice
    # tracking plus what each speaker says); "static" is for tests.
    role_provider: str = "session"
    # Also ask the LLM (LLM_PROVIDER) when the phrases leave roles unclear.
    role_llm_enabled: bool = False
    # Comma-separated phrases only the ICR says (the call-opening script,
    # e.g. "welcome to ABC Motors"); each one heard is strong evidence.
    role_icr_phrases: str = ""
    # Voice tracking on mixed audio: how alike (cosine, -1..1) a voice must
    # be to an earlier speaker's to be that speaker, and how many speakers
    # a call has at most.
    speaker_match_threshold: float = 0.45
    speaker_max_per_call: int = 2
    pyannote_model: str = "pyannote/speaker-diarization-community-1"
    huggingface_token: str = ""
    # CPU threads for diarization (torch). Torch defaults to every core, which
    # oversubscribes the CPU and can make pyannote 20x+ slower; 0 keeps that default.
    diarization_cpu_threads: int = 4
    summary_provider: str = "rule_based"
    # Which price-list services a call needs: "llm" (reads the whole call,
    # any supported language, understands "the battery is fine"; falls back
    # to the keywords when the LLM fails) or "rule_based" (English keywords).
    estimation_provider: str = "llm"
    # How long an API instance keeps the price list before re-reading it, so
    # a supervisor's save reaches every instance within this time.
    price_list_cache_seconds: float = 30.0
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
    # Live audio format asked of Plivo: "l16_16k" (16 kHz linear PCM, best
    # for transcription), "l16_8k" or "mulaw_8k" (phone quality).
    plivo_stream_audio: str = "l16_16k"
    # Live audio is sent for transcription when the speaker pauses: at least
    # PLIVO_STREAM_MIN_SPEECH_SECONDS of speech, then PLIVO_STREAM_PAUSE_SECONDS
    # quieter than PLIVO_STREAM_SILENCE_RMS (16-bit PCM level).
    # PLIVO_STREAM_FLUSH_SECONDS stays the upper limit; pause 0 = fixed chunks.
    plivo_stream_pause_seconds: float = 0.5
    # 2.5 s rather than shorter: a few seconds of speech is where the ASR
    # mishears words and the language most.
    plivo_stream_min_speech_seconds: float = 2.5
    plivo_stream_silence_rms: int = 350
    # Who an incoming call is connected to: comma-separated phone numbers
    # (E.164) and/or SIP endpoints (sip:icr@example.com), rung together.
    # When set, both sides are streamed as separate tracks: the caller
    # (inbound) is the customer and the dialled party (outbound) the ICR,
    # so speaker roles need no guessing. Empty: the caller is only streamed.
    plivo_icr_dial_targets: str = ""
    plivo_icr_caller_id: str = ""
    plivo_icr_dial_timeout_seconds: int = 30
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
    # A call's live AI analysis (complaints, sentiment, next question,
    # escalation, estimate) starts at most this often; speech in between is
    # covered by the next run. Each run makes several LLM calls. 0 = no limit.
    live_analysis_min_interval_seconds: float = 5.0
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