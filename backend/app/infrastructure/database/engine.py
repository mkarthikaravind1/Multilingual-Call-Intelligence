from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings

NOT_CONFIGURED = "not_configured"


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when PostgreSQL persistence is required but DATABASE_URL is unset."""


def build_engine(settings: Settings | None = None) -> Engine:
    """Create the SQLAlchemy engine for the configured DATABASE_URL.

    Never falls back to an in-memory database: if DATABASE_URL is missing,
    this raises rather than silently degrading production persistence.
    """
    settings = settings or get_settings()
    url = settings.database_url.strip()

    if not url or url == NOT_CONFIGURED:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL is not configured. Set it in the environment "
            "(see .env.example) before starting the application."
        )

    return create_engine(url, pool_pre_ping=True, future=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to the given engine.

    Sessions are created per-operation by repositories, not held globally.
    """
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)