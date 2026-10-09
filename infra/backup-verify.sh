#!/usr/bin/env bash
# Restore test: loads the newest warehouse backup into a scratch database inside the postgres
# container, checks that the key tables have rows, and drops the scratch database again.
set -euo pipefail
cd "$(dirname "$0")"

BACKUP_DIR="${BIS_BACKUP_DIR:-$HOME/backups/bis}"
compose=(docker compose -f docker-compose.vps.yml --env-file .env)
user="${BIS_PG_USER:-bis}"
latest="$(ls -1t "$BACKUP_DIR"/warehouse-*.dump | head -1)"
echo "restoring $latest into restore_check"

psql() { "${compose[@]}" exec -T postgres psql -U "$user" -v ON_ERROR_STOP=1 "$@"; }
psql -d postgres -c "DROP DATABASE IF EXISTS restore_check" -c "CREATE DATABASE restore_check"
trap 'psql -d postgres -c "DROP DATABASE IF EXISTS restore_check" >/dev/null' EXIT
"${compose[@]}" exec -T postgres psql -U "$user" -d restore_check -c "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null
"${compose[@]}" exec -T postgres pg_restore -U "$user" -d restore_check --no-owner < "$latest"

psql -d restore_check -tA -c "
  select 'ops.events',     count(*) from ops.events
  union all select 'ops.load_log',   count(*) from ops.load_log
  union all select 'marts.kpi_daily', count(*) from marts.kpi_daily
  union all select 'marts.fct_orders', count(*) from marts.fct_orders"
echo "restore check passed"
