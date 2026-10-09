#!/bin/sh
# Sends a fake "TestAlert" to Alertmanager so you can see what the alert
# e-mail looks like, without breaking anything.
#
#   sh deploy/monitoring/send-test-alert.sh             fire a warning
#   sh deploy/monitoring/send-test-alert.sh critical    fire a critical alert
#   sh deploy/monitoring/send-test-alert.sh --resolve   mark it resolved now
#                                   (--resolve critical for a critical one)
#
# It talks to the local Alertmanager (deploy/monitoring/local), whose e-mails
# land in Mailpit at http://localhost:8025. The e-mail shows up after about
# 30 s (group_wait). Without --resolve the alert resolves on its own after
# 5 minutes, which sends the "resolved" e-mail.
#
# ALERTMANAGER_URL changes the target, but only to this machine: the
# production Alertmanager sends real e-mail, so it is refused here. To test
# production on purpose, see "E-mail alerts" in DEPLOYMENT.md.
set -eu

ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://localhost:9093}"
ALERTMANAGER_URL="${ALERTMANAGER_URL%/}"

case "$ALERTMANAGER_URL" in
  http://localhost:*|http://127.0.0.1:*|http://localhost|http://127.0.0.1) ;;
  *)
    echo "Refusing to send to $ALERTMANAGER_URL: only a local Alertmanager is allowed." >&2
    exit 1
    ;;
esac

usage="usage: $0 [warning|critical] | --resolve [warning|critical]"

ends_at=""
if [ "${1:-}" = "--resolve" ]; then
  ends_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  shift
fi
severity="${1:-warning}"
case "$severity" in
  warning|critical) ;;
  *) echo "$usage" >&2; exit 2 ;;
esac

# Alertmanager identifies an alert by its labels, so --resolve must be given
# the same severity the alert was fired with. Each run gets its own "run"
# label: Alertmanager does not e-mail an alert it already reported in the
# last repeat_interval (4 h), so re-firing identical labels would send
# nothing. The run is remembered so --resolve clears the latest one.
state_file="${TMPDIR:-/tmp}/call-intelligence-test-alert-$severity"
timing=""
if [ -n "$ends_at" ]; then
  if ! run=$(cat "$state_file" 2>/dev/null) || [ -z "$run" ]; then
    echo "No $severity test alert from this machine to resolve." >&2
    exit 1
  fi
  timing="\"endsAt\": \"$ends_at\","
else
  run="$(date -u +%Y%m%dT%H%M%SZ)"
fi

payload=$(cat <<EOF
[
  {
    "labels": { "alertname": "TestAlert", "test": "true", "severity": "$severity", "run": "$run" },
    "annotations": {
      "summary": "Test alert: ignore this message",
      "description": "Sent by deploy/monitoring/send-test-alert.sh to check that alert e-mails arrive and look right. Nothing is wrong."
    },
    $timing
    "generatorURL": "$ALERTMANAGER_URL"
  }
]
EOF
)

if ! curl --silent --show-error --fail \
    -H "Content-Type: application/json" \
    -d "$payload" \
    "$ALERTMANAGER_URL/api/v2/alerts" > /dev/null; then
  echo "Could not reach Alertmanager at $ALERTMANAGER_URL. Is the local monitoring stack running?" >&2
  echo "  docker compose -f deploy/monitoring/local/docker-compose.yml up -d" >&2
  exit 1
fi

if [ -n "$ends_at" ]; then
  rm -f "$state_file"
  echo "TestAlert marked resolved. The 'resolved' e-mail arrives within ~5 minutes (group_interval)."
else
  echo "$run" > "$state_file"
  echo "TestAlert ($severity) sent to $ALERTMANAGER_URL."
  echo "The e-mail arrives in about 30 s: http://localhost:8025"
fi
