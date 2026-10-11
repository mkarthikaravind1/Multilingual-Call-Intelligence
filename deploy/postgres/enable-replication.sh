#!/bin/sh
# Lets a replica connect to this PostgreSQL server: makes the replication
# user and allows its connections. Safe to run again.
#
# On a new database it runs by itself (the replica compose file mounts it
# into /docker-entrypoint-initdb.d). On a database that already holds data,
# run it once by hand:
#
#   docker compose -f deploy/docker-compose.prod.yml -f deploy/docker-compose.replica.yml \
#     --env-file deploy/.env.production exec postgres sh /docker-entrypoint-initdb.d/10-replication.sh
set -e

: "${REPLICATION_USER:=replicator}"
: "${REPLICATION_PASSWORD:?set REPLICATION_PASSWORD}"
PGDATA="${PGDATA:-/var/lib/postgresql/data}"

# psql variables keep the password out of the SQL text and quote it safely.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v user="$REPLICATION_USER" -v password="$REPLICATION_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I WITH REPLICATION LOGIN', :'user')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'user') \gexec
SELECT format('ALTER ROLE %I WITH REPLICATION LOGIN PASSWORD %L', :'user', :'password') \gexec
SQL

LINE="host replication $REPLICATION_USER all scram-sha-256"
if ! grep -qxF "$LINE" "$PGDATA/pg_hba.conf"; then
  echo "$LINE" >> "$PGDATA/pg_hba.conf"
fi
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "SELECT pg_reload_conf()" > /dev/null
echo "Replication is allowed for $REPLICATION_USER."
