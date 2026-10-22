#!/usr/bin/env bash
# LayerFlow Agents — daily backup (plan §17.4)
#
# Dumps Postgres (pg_dump -Fc, gzipped) into $BACKUP_DIR, copies rendered
# artifacts if present, keeps the newest 14 of each, and optionally pushes the
# backup directory offsite with rclone when BACKUP_RCLONE_REMOTE is set.
#
# Usage:   ./scripts/backup.sh
# Cron:    0 2 * * *  cd /opt/layerflow && ./scripts/backup.sh >> /var/log/layerflow-backup.log 2>&1
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env if present (simple KEY=VALUE lines only).
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-layerflow}"
POSTGRES_DB="${POSTGRES_DB:-layerflow}"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/data/backups}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-$REPO_ROOT/data/artifacts}"
KEEP="${BACKUP_KEEP:-14}"
STAMP="$(date +%F-%H%M)"

log() { printf '%s [backup] %s\n' "$(date -u +%FT%TZ)" "$*"; }

mkdir -p "$BACKUP_DIR"

# ── 1. Postgres ────────────────────────────────────────────────────────────
DUMP_FILE="$BACKUP_DIR/layerflow-$STAMP.dump.gz"
TMP_FILE="$DUMP_FILE.partial"
log "dumping database '$POSTGRES_DB' → $DUMP_FILE"
docker compose exec -T postgres pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$TMP_FILE"

# Refuse to keep an empty or truncated dump.
if [[ ! -s "$TMP_FILE" ]] || ! gzip -t "$TMP_FILE"; then
  rm -f "$TMP_FILE"
  log "ERROR: dump is empty or corrupt"
  exit 1
fi
mv "$TMP_FILE" "$DUMP_FILE"
log "database dump ok ($(du -h "$DUMP_FILE" | cut -f1))"

# ── 2. Artifacts ───────────────────────────────────────────────────────────
if [[ -d "$ARTIFACTS_DIR" ]] && [[ -n "$(ls -A "$ARTIFACTS_DIR" 2>/dev/null)" ]]; then
  ART_FILE="$BACKUP_DIR/artifacts-$STAMP.tar.gz"
  log "archiving artifacts → $ART_FILE"
  tar -czf "$ART_FILE.partial" -C "$(dirname "$ARTIFACTS_DIR")" "$(basename "$ARTIFACTS_DIR")"
  mv "$ART_FILE.partial" "$ART_FILE"
else
  log "no artifacts directory at $ARTIFACTS_DIR (skipped)"
fi

# ── 3. Retention ───────────────────────────────────────────────────────────
prune() {
  local pattern="$1"
  # shellcheck disable=SC2012
  ls -1t "$BACKUP_DIR"/$pattern 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
    log "pruning $old"
    rm -f -- "$old"
  done
}
prune 'layerflow-*.dump.gz'
prune 'artifacts-*.tar.gz'

# ── 4. Offsite (optional) ──────────────────────────────────────────────────
if [[ -n "${BACKUP_RCLONE_REMOTE:-}" ]]; then
  if command -v rclone >/dev/null 2>&1; then
    log "copying backups offsite → $BACKUP_RCLONE_REMOTE"
    rclone copy "$BACKUP_DIR" "$BACKUP_RCLONE_REMOTE" --include 'layerflow-*.dump.gz' --include 'artifacts-*.tar.gz'
  else
    log "WARNING: BACKUP_RCLONE_REMOTE is set but rclone is not installed; offsite copy skipped"
  fi
fi

log "done"
