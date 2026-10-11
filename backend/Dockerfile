# API server image. Python 3.12: the telephony audio path uses the stdlib
# audioop module, which Python 3.13 removed.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# pg_dump, for the automatic database backups (BACKUP_ENABLED). It must be
# at least as new as the database server: Debian 13 ships version 17, which
# backs up the PostgreSQL 16 of the compose file.
RUN apt-get update     && apt-get install -y --no-install-recommends postgresql-client     && rm -rf /var/lib/apt/lists/*

COPY requirements-api.txt ./
RUN pip install -r requirements-api.txt

# Local pyannote diarization needs the (large) ML stack; hosted providers
# don't. Build with --build-arg INSTALL_DIARIZATION=true to include it.
ARG INSTALL_DIARIZATION=false
COPY requirements-diarization.txt ./
RUN if [ "$INSTALL_DIARIZATION" = "true" ]; then pip install -r requirements-diarization.txt; fi

COPY alembic.ini main.py docker-entrypoint.sh ./
COPY alembic ./alembic
COPY app ./app
# For scripts/restore_backup.py (fetching a database backup back).
COPY scripts ./scripts

# /app/data is where recordings go: made here so that the volume mounted
# over it starts out owned by the user the server runs as.
RUN useradd --system --uid 10001 --home-dir /app appuser \
    && chmod +x docker-entrypoint.sh \
    && mkdir -p /app/data \
    && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
