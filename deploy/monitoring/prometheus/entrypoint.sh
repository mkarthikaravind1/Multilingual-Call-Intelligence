#!/bin/sh
# Writes the /metrics bearer token (METRICS_TOKEN, may be empty) where
# prometheus.yml reads it, then starts Prometheus.
set -eu

printf '%s' "${METRICS_TOKEN:-}" > /tmp/metrics_token

exec /bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.retention.time="${PROMETHEUS_RETENTION:-30d}" \
  "$@"
