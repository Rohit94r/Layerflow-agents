#!/usr/bin/env bash
# LayerFlow Agents — monthly restore drill (plan §17.4)
#
# Restores the newest backup into a scratch database inside the postgres
# container, runs Alembic migrations against it through the api container,
# runs a row-count sanity query, then drops the scratch database.
# Exits non-zero if any step fails. Production data is never touched.
#
# Usage:   ./scripts/restore_check.sh [path/to/layerflow-YYYY-MM-DD-HHMM.dump.gz]
# Cron:    30 3 1 * *  cd /opt/layerflow && ./scripts/restore_check.sh >> /var/log/layerflow-restore-check.log 2>&1
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-layerflow}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/data/backups}"
SCRATCH_DB="layerflow_restore_check"

log() { printf '%s [restore-check] %s\n' "$(date -u +%FT%TZ)" "$*"; }

psql_admin() {
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres "$@"
}

cleanup() {
  log "dropping scratch database $SCRATCH_DB"
  psql_admin -c "drop database if exists $SCRATCH_DB with (force);" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ── 1. Pick the dump ───────────────────────────────────────────────────────
DUMP_FILE="${1:-}"
if [[ -z "$DUMP_FILE" ]]; then
  # shellcheck disable=SC2012
  DUMP_FILE="$(ls -1t "$BACKUP_DIR"/layerflow-*.dump.gz 2>/dev/null | head -n 1 || true)"
fi
if [[ -z "$DUMP_FILE" || ! -f "$DUMP_FILE" ]]; then
  log "ERROR: no backup found in $BACKUP_DIR"
  exit 1
fi
log "using $DUMP_FILE"
gzip -t "$DUMP_FILE"

# ── 2. Restore into a scratch database ─────────────────────────────────────
psql_admin -c "drop database if exists $SCRATCH_DB with (force);" >/dev/null
psql_admin -c "create database $SCRATCH_DB;" >/dev/null
psql_admin -d "$SCRATCH_DB" -c "create extension if not exists pgcrypto; create extension if not exists pg_trgm;" >/dev/null

log "restoring dump"
gunzip -c "$DUMP_FILE" | docker compose exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$SCRATCH_DB" --no-owner --exit-on-error

# ── 3. Run migrations against the restored copy ────────────────────────────
SCRATCH_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${SCRATCH_DB}"
log "running alembic upgrade head against $SCRATCH_DB"
docker compose run --rm -T -e DATABASE_URL="$SCRATCH_URL" api alembic upgrade head

# ── 4. Sanity query ────────────────────────────────────────────────────────
log "row counts:"
COUNTS="$(docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$SCRATCH_DB" -At -F ' ' -c "
  select 'tenants',  count(*) from tenants
  union all select 'users',    count(*) from users
  union all select 'sources',  count(*) from sources
  union all select 'articles', count(*) from articles
  union all select 'jobs',     count(*) from jobs;
")"
printf '%s\n' "$COUNTS" | sed 's/^/    /'

TENANTS="$(printf '%s\n' "$COUNTS" | awk '$1=="tenants"{print $2}')"
if [[ -z "$TENANTS" || "$TENANTS" -lt 1 ]]; then
  log "ERROR: restored database has no tenants — backup is not usable"
  exit 1
fi

log "restore check PASSED"
