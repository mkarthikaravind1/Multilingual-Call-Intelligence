#!/bin/sh
# Applies database migrations (unless RUN_MIGRATIONS=false), then starts the
# API. One worker per container: live telephony streams and background jobs
# live in the process, so scale by running more containers with
# LIVE_STATE_STORE_PROVIDER=redis rather than more workers.
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "Applying database migrations..."
    alembic upgrade head
fi

exec uvicorn main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
    --no-access-log
