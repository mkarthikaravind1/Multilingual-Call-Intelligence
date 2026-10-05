#!/bin/sh
# Fills alertmanager.yml from the environment, keeps the SMTP password in a
# file of its own, then starts Alertmanager.
set -eu

: "${ALERT_EMAIL_TO:?set ALERT_EMAIL_TO}"
: "${SMTP_SMARTHOST:?set SMTP_SMARTHOST (host:port)}"

printf '%s' "${SMTP_PASSWORD:-}" > /tmp/smtp_password

escape() { printf '%s' "$1" | sed -e 's/[\\|&]/\\&/g'; }

sed \
  -e "s|\${SMTP_SMARTHOST}|$(escape "$SMTP_SMARTHOST")|g" \
  -e "s|\${ALERT_EMAIL_FROM}|$(escape "${ALERT_EMAIL_FROM:-$ALERT_EMAIL_TO}")|g" \
  -e "s|\${SMTP_USERNAME}|$(escape "${SMTP_USERNAME:-}")|g" \
  -e "s|\${ALERT_EMAIL_TO}|$(escape "$ALERT_EMAIL_TO")|g" \
  /etc/alertmanager/alertmanager.template.yml > /tmp/alertmanager.yml

exec /bin/alertmanager \
  --config.file=/tmp/alertmanager.yml \
  --storage.path=/alertmanager \
  "$@"
