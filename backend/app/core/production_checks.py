"""Configuration mistakes that are harmless on a laptop but unsafe in
production. With APP_ENV=production the app refuses to start on any of
them; elsewhere they are logged as warnings."""

from app.core.config import Settings

_UNSET = {"", "not_configured", "change-me-in-development"}
MIN_SECRET_LENGTH = 32
# Prefix of every placeholder in deploy/.env.production.example.
PLACEHOLDER_PREFIX = "replace-with-"


class UnsafeConfigurationError(RuntimeError):
    pass


def configuration_problems(settings: Settings) -> list[str]:
    problems: list[str] = []

    secret = settings.auth_secret_key.strip()
    if secret in _UNSET or len(secret) < MIN_SECRET_LENGTH:
        problems.append(
            f"AUTH_SECRET_KEY must be a random value of at least {MIN_SECRET_LENGTH} characters."
        )
    if settings.database_url.strip() in _UNSET:
        problems.append("DATABASE_URL is not configured.")

    origins = settings.cors_origins
    if not origins:
        problems.append("CORS_ALLOWED_ORIGINS is empty; the web app could not call the API.")
    if "*" in origins:
        problems.append("CORS_ALLOWED_ORIGINS must list origins explicitly, not '*'.")

    telephony_on = settings.plivo_auth_token.strip() not in _UNSET
    if telephony_on:
        if not settings.plivo_validate_signatures:
            problems.append("PLIVO_VALIDATE_SIGNATURES must be true when telephony is enabled.")
        if not settings.telephony_stream_auth_required:
            problems.append(
                "TELEPHONY_STREAM_AUTH_REQUIRED must be true when telephony is enabled."
            )
        if not settings.plivo_stream_base_url.strip().startswith("wss://"):
            problems.append("PLIVO_STREAM_BASE_URL must be a wss:// URL.")
        if not settings.plivo_icr_dial_targets.strip():
            problems.append(
                "PLIVO_ICR_DIAL_TARGETS is empty: incoming calls would not be connected to an ICR."
            )

    if settings.customer_summary_enabled:
        delivery = settings.customer_summary_delivery_provider.strip().lower()
        if delivery in {"disabled", "none", "null", "noop"}:
            problems.append(
                "CUSTOMER_SUMMARY_ENABLED is true but CUSTOMER_SUMMARY_DELIVERY_PROVIDER "
                f"is {delivery!r}: no customer would receive a summary."
            )
        elif delivery == "sms_gate" and (
            settings.sms_gate_username.strip() in _UNSET
            or settings.sms_gate_password.strip() in _UNSET
        ):
            problems.append(
                "SMS_GATE_USERNAME and SMS_GATE_PASSWORD are required to send customer "
                "summaries through the SMS gateway."
            )

    if settings.role_provider.strip().lower() != "session":
        problems.append("ROLE_PROVIDER must be session (static is for tests).")

    shared = settings.live_state_store_provider.strip().lower() == "redis"
    if shared and settings.call_mapping_store_provider.strip().lower() != "redis":
        problems.append(
            "CALL_MAPPING_STORE_PROVIDER must be redis when LIVE_STATE_STORE_PROVIDER is redis "
            "(several instances must share the telephony call mapping)."
        )

    placeholders = sorted(
        name.upper()
        for name, value in settings.model_dump().items()
        if isinstance(value, str) and value.strip().lower().startswith(PLACEHOLDER_PREFIX)
    )
    if placeholders:
        problems.append(
            "These settings still hold example placeholders: " + ", ".join(placeholders) + "."
        )

    if settings.bootstrap_admin_password and len(settings.bootstrap_admin_password) < 12:
        problems.append("BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters.")

    return problems


def check_configuration(settings: Settings, logger) -> None:
    problems = configuration_problems(settings)
    if not problems:
        return
    if settings.is_production:
        raise UnsafeConfigurationError(
            "Refusing to start with an unsafe production configuration:\n- "
            + "\n- ".join(problems)
        )
    for problem in problems:
        logger.warning("Configuration: %s", problem)
