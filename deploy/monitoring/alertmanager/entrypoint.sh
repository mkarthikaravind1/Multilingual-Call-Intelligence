#!/bin/sh
# Fills alertmanager.yml and the e-mail template from the environment, keeps
# the SMTP password in a file of its own, then starts Alertmanager.
#
#   entrypoint.sh            start Alertmanager
#   entrypoint.sh --check    only validate the rendered config and render the
#                            e-mail template with sample data (sends nothing)
set -eu

: "${ALERT_EMAIL_TO:?set ALERT_EMAIL_TO}"
: "${SMTP_SMARTHOST:?set SMTP_SMARTHOST (host:port)}"

SMTP_REQUIRE_TLS="${SMTP_REQUIRE_TLS:-true}"
case "$SMTP_REQUIRE_TLS" in
  true|false) ;;
  *) echo "SMTP_REQUIRE_TLS must be true or false, got '$SMTP_REQUIRE_TLS'" >&2; exit 1 ;;
esac

# No trailing slash, so the template can append /d/<dashboard>.
GRAFANA_URL="${GRAFANA_URL:-}"
GRAFANA_URL="${GRAFANA_URL%/}"

printf '%s' "${SMTP_PASSWORD:-}" > /tmp/smtp_password

escape() { printf '%s' "$1" | sed -e 's/[\\|&]/\\&/g'; }

sed \
  -e "s|\${SMTP_SMARTHOST}|$(escape "$SMTP_SMARTHOST")|g" \
  -e "s|\${ALERT_EMAIL_FROM}|$(escape "${ALERT_EMAIL_FROM:-$ALERT_EMAIL_TO}")|g" \
  -e "s|\${SMTP_USERNAME}|$(escape "${SMTP_USERNAME:-}")|g" \
  -e "s|\${SMTP_REQUIRE_TLS}|$SMTP_REQUIRE_TLS|g" \
  -e "s|\${ALERT_EMAIL_TO}|$(escape "$ALERT_EMAIL_TO")|g" \
  /etc/alertmanager/alertmanager.template.yml > /tmp/alertmanager.yml

mkdir -p /tmp/templates
for template in /etc/alertmanager/templates/*.tmpl; do
  sed -e "s|\${GRAFANA_URL}|$(escape "$GRAFANA_URL")|g" \
    "$template" > "/tmp/templates/$(basename "$template")"
done

if [ "${1:-}" = "--check" ]; then
  /bin/amtool check-config /tmp/alertmanager.yml
  for name in email.subject email.text email.html; do
    echo "--- $name (sample data) ---"
    /bin/amtool template render \
      --template.glob='/tmp/templates/*.tmpl' \
      --template.text="{{ template \"$name\" . }}" > /dev/null
    echo "ok"
  done
  exit 0
fi

exec /bin/alertmanager \
  --config.file=/tmp/alertmanager.yml \
  --storage.path=/alertmanager \
  "$@"
