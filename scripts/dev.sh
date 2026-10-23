#!/usr/bin/env bash
# Run the whole LayerFlow stack (API + worker + dashboard) with one command.
#
#   ./scripts/dev.sh              # dashboard on http://localhost:3100
#   WEB_PORT=3000 ./scripts/dev.sh  # if port 3000 is free
#   API_PORT=8001 ./scripts/dev.sh  # if port 8000 is taken
#
# Ctrl+C stops all three. Logs from all processes are printed to this terminal.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT/apps/api"
WEB_DIR="$ROOT/apps/web"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3100}"
PY="$API_DIR/.venv/bin/python"

say() { printf '%s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

# ---- one-time prerequisites -------------------------------------------------
[ -x "$PY" ] || die "Python venv missing. First-time setup:
  cd apps/api && python3.12 -m venv .venv && .venv/bin/pip install -e \".[dev]\""
[ -d "$WEB_DIR/node_modules" ] || die "Frontend dependencies missing. First-time setup:
  cd apps/web && npm install"
[ -f "$API_DIR/.env" ] || say "WARNING: apps/api/.env not found — using defaults (see SETUP.md §3)."

port_busy "$API_PORT" && die "Port $API_PORT is already in use. Try: API_PORT=8001 ./scripts/dev.sh"
port_busy "$WEB_PORT" && die "Port $WEB_PORT is already in use. Try: WEB_PORT=3000 ./scripts/dev.sh"

# ---- database (created on first run) ---------------------------------------
if [ ! -f "$API_DIR/data/dev.db" ]; then
  say "First run: creating the database…"
  (cd "$API_DIR" && .venv/bin/python -m app.cli migrate) || die "migrate failed"
  (cd "$API_DIR" && .venv/bin/python -m app.cli bootstrap) || die "bootstrap failed"
fi

# ---- model hint (not fatal) -------------------------------------------------
PROVIDER="$(grep -E '^MODEL_PROVIDER=' "$API_DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
PROVIDER="${PROVIDER:-ollama}"
if [ "$PROVIDER" = "ollama" ] && ! curl -s -m 2 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
  say "NOTE: MODEL_PROVIDER=ollama but Ollama is not reachable — the UI works, generation will fail."
  say "      Start Ollama and pull a model, or set MODEL_PROVIDER=mock in apps/api/.env."
fi

pids=()
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}
cleanup() {
  trap - INT TERM EXIT
  say ""
  say "Stopping API, worker and dashboard…"
  for pid in "${pids[@]}"; do kill_tree "$pid"; done
  wait 2>/dev/null || true
  say "Stopped."
}
trap cleanup INT TERM EXIT

say "Starting LayerFlow"
say "  API       http://localhost:$API_PORT"
say "  Dashboard http://localhost:$WEB_PORT/login"
say "  Worker    background agent lane"
say "  Ctrl+C stops everything"
say ""

(cd "$API_DIR" && exec .venv/bin/uvicorn app.main:app --reload --port "$API_PORT") &
pids+=($!)

(cd "$API_DIR" && exec .venv/bin/python -m app.worker) &
pids+=($!)

(cd "$WEB_DIR" && exec ./node_modules/.bin/next dev --port "$WEB_PORT") &
pids+=($!)

wait
