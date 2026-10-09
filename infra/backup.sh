#!/usr/bin/env bash
# Daily database backup on the VPS (plan section 13): the ops and marts schemas of the
# warehouse (raw is reproducible from the sources) and the Keycloak database (users, clients).
# Run from cron after the nightly pipeline, e.g.:
#   30 3 * * * /path/to/infra/backup.sh >> $HOME/backups/bis/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"

BACKUP_DIR="${BIS_BACKUP_DIR:-$HOME/backups/bis}"
KEEP_DAYS="${BIS_BACKUP_DAYS:-14}"
STAMP="$(date +%F)"
compose=(docker compose -f docker-compose.vps.yml --env-file .env)

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

dump() {  # dump <name> <pg_dump args...>; written atomically
  local target="$BACKUP_DIR/$1-$STAMP.dump"
  shift
  "${compose[@]}" exec -T postgres pg_dump -U "${BIS_PG_USER:-bis}" -Fc "$@" > "$target.tmp"
  mv "$target.tmp" "$target"
  echo "$(date -Is) wrote $target ($(du -h "$target" | cut -f1))"
}

schemas=(-n ops -n marts)
# The knowledge schema exists from phase K1 on.
if "${compose[@]}" exec -T postgres psql -U "${BIS_PG_USER:-bis}" -d warehouse -tAc \
    "select 1 from pg_namespace where nspname = 'knowledge'" | grep -q 1; then
  schemas+=(-n knowledge)
fi

dump warehouse -d warehouse "${schemas[@]}"
dump keycloak -d keycloak

find "$BACKUP_DIR" -name '*.dump' -mtime "+$KEEP_DAYS" -delete
