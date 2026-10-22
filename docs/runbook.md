# LayerFlow Agents — Operations Runbook

Operational guide for running the LayerFlow agent engine for The Executive Narrative (TEN): first deploy, updates, local development, split model hosting, backups, alerts and troubleshooting.

Services (see `docker-compose.yml`):

| Service | Role | Internal port | Exposed |
| --- | --- | --- | --- |
| `caddy` | Reverse proxy + automatic TLS | 80 / 443 | Yes (only public service) |
| `web` | Next.js dashboard (standalone) | 3000 | Via Caddy |
| `api` | FastAPI (`/api/v1/*`) | 8000 | Via Caddy (`/api/*`) |
| `worker` | Job queue worker + scheduler tick | — | No |
| `postgres` | State + job queue | 5432 | No |
| `ollama` | Local LLM + embeddings | 11434 | No |

Named volumes: `pgdata`, `ollama_models`, `artifacts`, `cache`. All are backed up or reproducible.

---

## 1. First deploy (fresh VPS)

Target: Ubuntu 22.04/24.04, 8 GB RAM recommended (see plan §19.1). Confirm the real vCPU / RAM / disk before choosing a model.

1. **Harden the host.** Log in as a non-root sudo user.
   ```bash
   sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable
   # In /etc/ssh/sshd_config: PasswordAuthentication no, PermitRootLogin no
   sudo systemctl restart ssh
   ```
2. **Install Docker Engine + Compose plugin** (official Docker apt repository), then add your user to the `docker` group and log in again.
3. **Clone the repo.**
   ```bash
   sudo mkdir -p /opt/layerflow && sudo chown "$USER" /opt/layerflow
   git clone https://github.com/Rohit94r/Layerflow-agents.git /opt/layerflow
   cd /opt/layerflow
   ```
4. **Configure secrets.**
   ```bash
   cp .env.example .env
   # Fill at minimum: APP_SECRET_KEY, APP_BASE_URL, POSTGRES_PASSWORD (and DATABASE_URL to match),
   # TOKEN_ENCRYPTION_KEY, FETCH_USER_AGENT (with a real contact email), TEN_SITE_URL.
   # Optional: ADMIN_EMAIL / ADMIN_PASSWORD to create the first owner on bootstrap.
   chmod 600 .env
   ```
   Generate keys:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(48))"                                  # APP_SECRET_KEY
   python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"       # TOKEN_ENCRYPTION_KEY (Fernet)
   ```
5. **Start the stack.**
   ```bash
   docker compose up -d
   ```
   On start, the `api` container runs `alembic upgrade head` and then `python -m app.cli bootstrap` automatically. Bootstrap is idempotent: it creates the `ten` tenant from `config/tenants/ten.json`, seeds sources from `config/sources/feeds.yaml`, and creates the owner account if `ADMIN_EMAIL` / `ADMIN_PASSWORD` are set.
6. **Pull the models** (first time only; stored in the `ollama_models` volume).
   ```bash
   docker compose exec ollama ollama pull qwen2.5:7b-instruct
   docker compose exec ollama ollama pull nomic-embed-text
   # Optional fast model for routing/classification:
   docker compose exec ollama ollama pull qwen2.5:3b-instruct
   ```
   Model names must match `MODEL_WRITER`, `MODEL_FAST`, `MODEL_EMBED` in `.env` (or the per-agent values in Settings → Models).
7. **Create the admin** (if not created by bootstrap).
   ```bash
   docker compose exec api python -m app.cli create-admin --email you@example.com --password 'a-long-passphrase'
   ```
8. **Check health.**
   ```bash
   curl -s https://<domain>/api/v1/health | python3 -m json.tool
   ```
   Expect database `ok`, model provider reachable with the configured models present, a recent worker heartbeat, and free disk.
9. **Smoke test from the dashboard.** Log in → News Feed → **Refresh** → confirm items appear within a few minutes. Promote one item → watch it move through the stages in Content Studio → confirm it reaches the Review Queue.
10. **Schedule backups** (section 6) and run `scripts/restore_check.sh` once.
11. **Benchmark the model** on the real hardware and record the numbers in plan §11.3:
    ```bash
    docker compose exec api python /srv/layerflow/scripts/bench_model.py
    ```

---

## 2. Update runbook

```bash
cd /opt/layerflow
git pull
docker compose build api web
docker compose run --rm api alembic upgrade head
docker compose up -d
curl -s https://<domain>/api/v1/health
```

A ~20-second restart is acceptable for an internal tool. Jobs that were running when the worker stopped are re-queued by the visibility timeout (10 minutes) and complete once; publications are idempotent, so nothing is published twice.

Roll back: `git checkout <previous-tag>` and repeat the steps. Migrations are forward-only; take a backup (`scripts/backup.sh`) before any update that includes a migration.

---

## 3. Local development without Docker

Useful on a laptop for UI or agent work. Uses SQLite instead of Postgres; the queue code path is the same (SQLite simply ignores `SKIP LOCKED`). Use Postgres for anything performance- or concurrency-related.

**Backend**

```bash
cd apps/api
python -m venv .venv
.venv/Scripts/pip install -e .[dev]        # Windows
# .venv/bin/pip install -e .[dev]          # Linux / macOS

# Windows PowerShell: $env:DATABASE_URL="sqlite+aiosqlite:///./data/dev.db"
export DATABASE_URL="sqlite+aiosqlite:///./data/dev.db"
export APP_ENV=development
export OLLAMA_BASE_URL="http://localhost:11434"   # or MODEL_PROVIDER=mock (see below)

alembic upgrade head
python -m app.cli bootstrap
python -m app.cli create-admin --email dev@example.com --password 'dev-password-change-me'

uvicorn app.main:app --reload --port 8000     # terminal 1
python -m app.worker                           # terminal 2
```

**Frontend**

```bash
cd apps/web
npm install
npm run dev       # http://localhost:3000 — Next rewrites /api/* to http://localhost:8000
```

**Working without a model.** Set `MODEL_PROVIDER=mock` to use the deterministic mock provider. Every run is then labelled **Mock provider** in the top bar and on generated content, so mock output can never be mistaken for real model output. Use it for UI work and tests only; never for a demo or for content that will be reviewed.

**Tests**

```bash
cd apps/api && .venv/Scripts/python -m pytest          # unit, contract, integration (mock model), adapter
python scripts/eval_agents.py --suite pipeline         # golden set through the REAL model (not CI-gated)
```

---

## 4. Split model hosting (small VPS)

If the VPS has less than 8 GB RAM, keep the app, database and worker on the VPS and run Ollama on a machine with more RAM or a GPU (plan §11.3). The agents still run on the VPS; only the model moves.

1. Install [Tailscale](https://tailscale.com) on both machines and join them to the same tailnet.
2. On the model host:
   ```bash
   # Listen on the Tailscale interface only
   OLLAMA_HOST=<model-host-tailscale-ip>:11434 ollama serve
   ollama pull qwen2.5:7b-instruct && ollama pull nomic-embed-text
   ```
3. On the VPS, in `.env`:
   ```env
   OLLAMA_BASE_URL=http://<model-host-tailscale-ip>:11434
   ```
   and stop the bundled `ollama` service (`docker compose stop ollama`, or remove it with a compose override).
4. `docker compose up -d api worker` and check `/api/v1/health`.

Never expose port 11434 to the public internet. An SSH tunnel (`ssh -N -L 11434:localhost:11434 user@model-host`) is an alternative to Tailscale.

---

## 5. Configuration reference

All variables are documented in `.env.example` (plan Appendix A). Key ones:

| Variable | Purpose |
| --- | --- |
| `APP_SECRET_KEY` | Session signing; 32+ random bytes |
| `APP_BASE_URL` | Public dashboard URL (cookies, links) |
| `DATABASE_URL` | `postgresql+asyncpg://…` in production; `sqlite+aiosqlite:///…` locally |
| `MODEL_PROVIDER` | `ollama` (default) · `openai_compat` (optional) · `mock` (tests/UI only) |
| `OLLAMA_BASE_URL` | Model host; change for split hosting |
| `MODEL_WRITER` / `MODEL_FAST` / `MODEL_EMBED` | Default models; per-agent overrides in Settings → Models |
| `MODEL_TIMEOUT_S` / `MODEL_CONCURRENCY` | Keep concurrency at 1 on CPU |
| `FETCH_USER_AGENT` | Must include a real contact address |
| `PUBLISH_TARGET` | `export` until site access exists; then `ten_static`, `wordpress` or `webhook` |
| `TEN_SFTP_*`, `TEN_PUBLIC_ROOT`, `TEN_SITE_URL` | `ten_static` adapter |
| `LINKEDIN_*`, `TOKEN_ENCRYPTION_KEY` | Optional LinkedIn publishing; tokens encrypted at rest |
| `BACKUP_DIR`, `ALERT_WEBHOOK_URL`, `LOG_LEVEL` | Operations |

The dashboard (Settings → Integrations) shows each integration as **configured** or **missing** — never the secret value.

---

## 6. Backups and restore

| What | How | When |
| --- | --- | --- |
| Postgres | `scripts/backup.sh` → `pg_dump -Fc` → gzip into `$BACKUP_DIR`, keeps the last 14 | Daily 02:00 |
| Artifacts | Copied by `scripts/backup.sh` if the artifacts directory is present | Daily, and with each publish |
| Offsite | `rclone copy` to `$BACKUP_RCLONE_REMOTE` if set (B2/S3 free tier or the mentor's server) | Daily |
| Prompts / config | In git | Every change |
| Restore drill | `scripts/restore_check.sh` restores the latest dump into a scratch DB, runs migrations and a sanity query, then drops it | Monthly |

Cron (as the deploy user):

```cron
0 2 * * *  cd /opt/layerflow && ./scripts/backup.sh >> /var/log/layerflow-backup.log 2>&1
30 3 1 * * cd /opt/layerflow && ./scripts/restore_check.sh >> /var/log/layerflow-restore-check.log 2>&1
```

**Full restore** (disaster recovery):

```bash
docker compose stop api worker web
gunzip -c "$BACKUP_DIR/layerflow-<date>.dump.gz" | \
  docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists
docker compose run --rm api alembic upgrade head
docker compose up -d
```

---

## 7. Alerts

Set `ALERT_WEBHOOK_URL` to a webhook (Telegram bot, Slack-compatible, or any JSON endpoint). Alerts fire on:

- 3 consecutive job failures,
- model provider unreachable,
- disk usage above 85%,
- a publish failure.

Without a webhook, the same conditions are shown on the Dashboard "System" card and in `/api/v1/health`.

---

## 8. Logs and resource limits

- Structured JSON logs (request id, job id, tenant, agent, latency) on stdout:
  ```bash
  docker compose logs -f api worker
  docker compose logs --since 1h worker | grep '"level":"error"'
  ```
- Docker log rotation: 50 MB × 5 files per container (configured in compose).
- Job history, errors and model runs are also visible in the dashboard (job logs in Content Studio, agent health on the Dashboard) and in the `jobs`, `job_events` and `model_runs` tables.
- Memory limits are set in compose for `web`, `api` and `worker`. Ollama gets the remainder; keep `OLLAMA_MAX_LOADED_MODELS=1` and `MODEL_CONCURRENCY=1` on CPU hosts.
- Feed items are capped at 300 per discovery run; generated artifacts that were never published are pruned after 90 days.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Model status pill red; jobs fail with connection errors | Ollama down or unreachable | `docker compose ps ollama`; `docker compose restart ollama`; for split hosting check Tailscale (`tailscale status`) and `OLLAMA_BASE_URL`. Jobs retry with backoff (30 s, 2 min, 10 min). |
| Health shows "model not found" / jobs fail with `model ... not found` | Configured model not pulled | `docker compose exec ollama ollama list`; pull the model named in `.env` or Settings → Models. |
| Generation extremely slow or OOM-killed | Model too large for RAM, or two models loaded | Use a smaller model (7B → 3B), keep concurrency at 1, or move the model to a bigger host (section 4). |
| Job shows **dead** | Exhausted 3 attempts | Open the job in the dashboard, read `last_error`, fix the cause, click **Retry**. Dead jobs are never silently dropped. |
| Job stuck **running** for > 10 minutes after a worker crash | Stale lock | The visibility timeout re-queues it automatically; restart the worker if it is not running (`docker compose restart worker`). |
| Article in **needs_sources** | Research found fewer than 2 usable sources | Expected behaviour. Add source links in Content Studio and re-run Research, or archive the topic. |
| A source shows an error and is greyed out | Feed failing; auto-disabled after 5 consecutive failures | Settings → Sources → **Test**. Fix or replace the URL, then re-enable. |
| Discovery returns few items | Sources inactive, rate-limited (429) or blocked | Check per-source `last_error`; tier-B feeds (Google/Bing News) back off automatically. |
| Disk > 85% alert | Model files, cache or artifacts | `docker system df`; prune old images; the fetch cache expires after 7 days; old unpublished artifacts are pruned after 90 days. |
| Social post status **draft_ready**, Publish disabled | No LinkedIn token / app not approved | Expected. Use **Copy post** + **Open LinkedIn**. Connect LinkedIn in Settings → Integrations once a developer app exists. |
| Publish **failed** with 4xx | Bad credentials or target rejects content | Not retried automatically. Read the exact error on the publication, fix credentials or content, then **Publish now**. |
| Publish **failed** with 5xx | Target temporarily down | Retried 3×, then marked failed with an alert. |
| Login returns 429 | Login rate limit (5 attempts / 15 min / IP) | Wait 15 minutes. |
| `/health` shows worker heartbeat stale | Worker not running | `docker compose logs worker`; `docker compose up -d worker`. |
