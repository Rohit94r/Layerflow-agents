#!/bin/sh
# api:    migrate + bootstrap (idempotent), then serve
# worker: wait for migrations (the api runs them), then process jobs
set -eu

case "${1:-api}" in
  api)
    python -m app.cli migrate
    python -m app.cli bootstrap
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --log-level "${LOG_LEVEL:-info}"
    ;;
  worker)
    exec python -m app.worker
    ;;
  migrate)
    exec python -m app.cli migrate
    ;;
  *)
    exec "$@"
    ;;
esac
