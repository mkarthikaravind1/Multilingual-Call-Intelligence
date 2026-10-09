"""Shared test setup.

Tests never read the repository's .env: it holds local secrets and points at
real services (Redis, Postgres, Groq, Sarvam). Set before any app module is
imported, because app.core.config reads its settings at import time. Tests
that need a setting pass it explicitly (Settings(_env_file=None, ...)).
"""

import os

os.environ["APP_ENV_FILE"] = ""
