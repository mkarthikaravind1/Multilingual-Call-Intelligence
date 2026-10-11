#!/bin/sh
# Starts a read-only copy of the primary database that follows it
# continuously. The first start copies the whole primary (pg_basebackup);
# later starts carry on from where the copy stopped.
set -e

: "${PRIMARY_HOST:=postgres}"
: "${REPLICATION_USER:=replicator}"
: "${REPLICATION_PASSWORD:?set REPLICATION_PASSWORD}"
: "${REPLICA_SLOT:=replica_1}"
PGDATA="${PGDATA:-/var/lib/postgresql/data}"
export PGPASSWORD="$REPLICATION_PASSWORD"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "replica: waiting for the primary at $PRIMARY_HOST"
  until pg_isready -h "$PRIMARY_HOST" -q; do sleep 2; done
  mkdir -p "$PGDATA"
  chown postgres:postgres "$PGDATA"
  chmod 700 "$PGDATA"
  echo "replica: copying the primary"
  # -R: start as a standby of the primary. The slot makes the primary keep
  # what this replica has not received yet while it is down; it is created
  # with the first copy and reused by a copy made again later.
  if ! gosu postgres pg_basebackup -h "$PRIMARY_HOST" -U "$REPLICATION_USER" -D "$PGDATA" \
         -R -X stream -C -S "$REPLICA_SLOT"; then
    echo "replica: the slot exists already; copying again with it"
    rm -rf "${PGDATA:?}"/*
    gosu postgres pg_basebackup -h "$PRIMARY_HOST" -U "$REPLICATION_USER" -D "$PGDATA" \
      -R -X stream -S "$REPLICA_SLOT"
  fi
  echo "replica: copy finished"
fi

unset PGPASSWORD
exec docker-entrypoint.sh postgres -c hot_standby=on
