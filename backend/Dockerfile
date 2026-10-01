# API server image. Python 3.12: the telephony audio path uses the stdlib
# audioop module, which Python 3.13 removed.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

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

RUN useradd --system --uid 10001 --home-dir /app appuser \
    && chmod +x docker-entrypoint.sh \
    && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
