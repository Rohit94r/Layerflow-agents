# SETUP — run LayerFlow Agents end to end

This guide takes a fresh machine (Windows 10/11, macOS or Linux) to a working system: dashboard, API,
agents, local model, real news, real articles. Follow the sections in order the first time.

> **Status of this build (read first).** All code is written: backend (API, 10 agents, worker, queue,
> adapters), dashboard (8 screens), prompts, configs, eval set, Docker deployment, docs. It was written on a
> machine where nothing could be installed, so **the test suite and the frontend build have not been run
> yet**. Step 4 (backend tests) and step 6 (`npm run typecheck`) are therefore the first things to run. If
> anything fails there, fix it before demoing — the failures will point at exact files and lines.

---

## 0. What you are running

```
Browser ──► Next.js dashboard (:3000) ──/api──► FastAPI (:8000) ──► SQLite (dev) / Postgres (prod)
                                                    │
                                     Worker ────────┘──► Ollama (:11434, local model, no API key)
                                                    └──► RSS / GDELT / EDGAR / HN / Reddit / web pages
```

Three processes in development: **API**, **worker**, **web**. Plus **Ollama** for the model.

---

## 1. Install the tools (once per machine)

| Tool | Version | Get it | Check |
| --- | --- | --- | --- |
| Git | any recent | https://git-scm.com | `git --version` |
| Python | **3.12** (3.13 also fine; avoid 3.14 for now) | https://www.python.org/downloads/ — tick "Add to PATH" | `python --version` (Windows: `py -3.12 --version`) |
| Node.js | **22 LTS** or newer | https://nodejs.org | `node --version` |
| Ollama | latest | https://ollama.com/download | `ollama --version` |
| Docker Desktop | optional (only for section 8) | https://www.docker.com/products/docker-desktop | `docker --version` |

College machines sometimes block installers. Python and Node have "zip / no-admin" builds; Ollama installs per-user.

---

## 2. Get the code

```bash
git clone https://github.com/Rohit94r/Layerflow-agents.git
cd Layerflow-agents
git checkout feat/end-to-end-build      # the full build lives here until it is merged into main
```

---

## 3. Backend: Python environment + config

**Windows (PowerShell):**

```powershell
cd apps\api
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

**macOS / Linux:**

```bash
cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

Create **`apps/api/.env`** (local development; never commit it):

```env
APP_ENV=development
APP_SECRET_KEY=dev-only-change-me-to-a-long-random-string-1234567890
APP_BASE_URL=http://localhost:3000
DATABASE_URL=sqlite+aiosqlite:///./data/dev.db

# Model: local Ollama, no API key
MODEL_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
MODEL_WRITER=qwen2.5:7b-instruct
MODEL_FAST=qwen2.5:3b-instruct
MODEL_EMBED=nomic-embed-text

# First login (applied by bootstrap when no users exist yet)
ADMIN_EMAIL=admin@ten.local
ADMIN_PASSWORD=change-this-password

PUBLISH_TARGET=export
TEN_SITE_URL=https://theexecutivenarrative.com
```

All other variables have safe defaults; the full list with explanations is in `.env.example`.

---

## 4. Run the backend tests (first verification)

```bash
# still inside apps/api with the venv active
pytest -q
```

The tests use a temporary SQLite database, the **mock model** and a **mocked internet**, so they need no
Ollama and no network. They cover: slugs, URL canonicalisation, dedupe precision, scoring, routing,
readability, number/quote grounding (10/10 seeded hallucinations caught), formatter, SEO validators,
LinkedIn rules, prompt-injection stripping, SSRF/robots/size guards, feed parsers, queue claim/retry/dead/
visibility-timeout recovery, state machine, auth/CSRF/roles/rate limits, the migration matching the models,
contract schemas, and the **full pipeline** (discover → promote → research → write → edit → SEO → QA →
review → schedule → publish export + staging site with repaired sitemap → LinkedIn draft).

If a test fails, the message names the file and line. Fix, re-run, then continue.

---

## 5. Create the database and start the API + worker

```bash
python -m app.cli migrate          # creates data/dev.db with all tables
python -m app.cli bootstrap        # TEN tenant, ~40 news sources, eval cases, admin from .env
```

Open two terminals (both in `apps/api` with the venv active):

```bash
# terminal 1 — API
uvicorn app.main:app --reload --port 8000

# terminal 2 — worker (runs the agents)
python -m app.worker
```

Check: http://localhost:8000/api/v1/health — `database` should be `ok`; `model` turns `ok` after step 7.

---

## 6. Frontend: install, type-check, run

```bash
cd apps/web
npm install
npm run typecheck      # must finish with no errors
npm run dev            # http://localhost:3000
```

Sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from your `.env`.

Before a demo also run `npm run build` once (production build; catches anything `dev` mode tolerates).

---

## 7. The model (Ollama)

```bash
ollama pull qwen2.5:3b-instruct      # ~1.9 GB — fast; routing, short copy
ollama pull qwen2.5:7b-instruct      # ~4.7 GB — the writer; needs ~8 GB free RAM
ollama pull nomic-embed-text         # ~0.3 GB — dedupe embeddings (optional)
```

Ollama runs in the background after install (check http://localhost:11434). Then in the dashboard:
**Settings → Models → Test** should show a latency and a sample reply.

**Speed on a CPU-only i7:** 7B ≈ 4–8 tokens/s → one 1,200-word article ≈ 10–20 min end to end. For a
quicker demo set `MODEL_WRITER=qwen2.5:3b-instruct` in `.env` (restart API + worker), or change the model
per agent in **Settings → Models**. With an NVIDIA GPU Ollama uses it automatically (1–3 min per article).
No embedding model? Leave `MODEL_EMBED=` empty — dedupe falls back to TF-IDF.

Measure the machine once: `python ../../scripts/bench_model.py --model qwen2.5:7b-instruct` (from `apps/api`).

**No model at all?** Set `MODEL_PROVIDER=mock`: every screen works with deterministic extractive text and
the top bar shows a **Mock provider** badge. Use it for UI work only, never for real content.

---

## 8. Alternative: everything in Docker (the VPS path)

```bash
cp .env.example .env     # set APP_SECRET_KEY, POSTGRES_PASSWORD, ADMIN_EMAIL, ADMIN_PASSWORD, DOMAIN=localhost
docker compose up -d --build
docker compose exec ollama ollama pull qwen2.5:7b-instruct
docker compose exec ollama ollama pull qwen2.5:3b-instruct
docker compose exec ollama ollama pull nomic-embed-text
```

Dashboard: http://localhost:3000 (dev override exposes ports) or https://localhost via Caddy.
Postgres replaces SQLite; the API container runs migrations + bootstrap on every start.
Full production runbook (VPS, TLS, backups, restore drill, alerts): `docs/runbook.md`.

---

## 9. First end-to-end run (what to click)

1. **Dashboard** `/` — cards show real counts; "Model ready" and "Worker 1 live" pills are green.
2. **News Feed** `/news` → **Refresh**. In 1–3 minutes real stories from ~40 sources appear with scores,
   categories and duplicate clusters. (The worker also refreshes every 30 minutes on its own.)
3. Open a story → **Promote** (category pre-filled, *auto* on). You land in the **Studio**.
4. Watch the timeline: Research → Write → Edit → SEO → QA, with the live log on the right.
   - Thin coverage → **Needs more sources** (by design: no filler articles).
   - QA failing twice → **Pipeline stopped** with the reasons; owner can **Send to review anyway**.
5. **Review** `/review` → read the rendered preview, QA scores, diff → **Approve** (`a`) → schedule modal →
   **Dry run** → **Schedule** (or publish now from the **Calendar**).
6. **Calendar** `/calendar` → **Publish now** → download the export bundle, or open the staging page
   (target `ten_static` without SFTP writes to `/site/ten/<route>/<slug>/` with a repaired `sitemap.xml`).
7. **Social** `/social` → the LinkedIn draft → **Copy post** → **Open LinkedIn**.
8. **SEO** `/seo` → **Site audit** → **Run audit** crawls the live TEN site and produces the fix list for
   the existing articles (CSV) and a corrected sitemap.
9. **Settings → Evaluations** → run **deterministic** (seconds), then **critic** / **pipeline** with the real model.

The 10-minute pitch version of this flow is `docs/demo-script.md`.

---

## 10. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `pip install` fails building a package | You are on Python 3.13/3.14 without wheels — use Python 3.12. |
| API exits: `APP_SECRET_KEY must be set` | `APP_ENV=production` needs a 32+ char secret; for local use `APP_ENV=development`. |
| Dashboard says "Cannot reach the API" | API not running on :8000, or started from the wrong folder (run from `apps/api`). |
| Worker pill red / "No worker has reported in" | Start `python -m app.worker` (terminal 2). |
| Model pill amber "Models not pulled" | `ollama pull <name>` for the names listed, or change models in Settings → Models. |
| Jobs stay `queued` | Worker not running, or it is busy with a long generation (model lane runs one job at a time). |
| A source shows errors / auto-disabled | Feed URL changed. Settings → Sources → Test, fix the URL, re-enable. |
| Article stuck in `failed` | Studio shows the error; **Retry** the failed stage after fixing the cause. |
| LinkedIn **Publish** says not connected | Expected without a LinkedIn developer app. Use **Copy post** (see plan §15). |
| Want a clean start | Stop everything, delete `apps/api/data/`, then `migrate` + `bootstrap` again. |

Logs: API and worker print structured JSON to their terminals; every job's progress lines are also in the
Studio log and in **Dashboard → failed jobs**.

---

## 11. Where things are

| Path | What |
| --- | --- |
| `apps/api/app/agents/` | A0 orchestrator · A1 discovery · A2 research · A3 writer · A4 editor · A5 SEO · A6 critic · A7 scheduler · A8 publisher · A9 distribution · evals · crawl |
| `apps/api/app/services/` | fetcher (SSRF/robots/cache), extractor, feeds, dedupe, scoring, grounding gates, SEO rules, formatter, render, sitemap |
| `apps/api/app/routers/` | REST API (`/api/v1/...`), docs at http://localhost:8000/api/v1/docs in development |
| `apps/api/app/worker.py` | queue lanes, retries, scheduler tick, heartbeats, alerts, retention |
| `apps/web/app/(app)/` | dashboard screens |
| `prompts/` | versioned prompts (editable in Settings → Prompts; edits are new versions, one-click rollback) |
| `config/` | `sources/feeds.yaml`, `competitors.yaml`, `tenants/ten.json` |
| `templates/ten/article.html` | published page template (matches the live site's CSS) |
| `evals/cases/` | 20 golden cases (fictional companies) |
| `docs/` | runbook, demo script, ADRs |
| `plan.md` | the plan of record |

---

## 12. What to do next

**Tomorrow (make it green):**
1. `pytest -q` passes (step 4). Fix anything that fails.
2. `npm run typecheck` and `npm run build` pass (step 6).
3. One real article per category end to end with the real model (step 9); note timings.
4. Run `scripts/bench_model.py` and record real numbers in `plan.md` §11.3 (Phase 0 exit criterion).
5. Run Settings → Evaluations → **deterministic** and **critic**; keep the baseline.

**This week (demo quality):**
6. Settings → Sources → **Test** every source; switch on the `# verify` feeds that work, drop dead ones.
7. Put 8–12 mentor-approved TEN articles in `evals/style/good/` and run
   `python scripts/eval_agents.py --style-profile` so the writer gets measured style targets.
8. Read 5 generated articles per category; tune `prompts/categories/*.md` and `prompts/persona/ten.md`
   (save as new versions in Settings, re-run evals after each change).
9. Run the Playwright demo test: `cd apps/web && npx playwright install chromium && npm run test:e2e`
   (needs the stack running with `MODEL_PROVIDER=mock` and `E2E_EMAIL` / `E2E_PASSWORD` set).
10. Rehearse `docs/demo-script.md` twice in a row without touching the database.

**Needs the mentor (plan §25):**
11. VPS specs → choose model size (8 GB RAM = 7B; less → run Ollama on another machine via Tailscale).
12. Site access (SFTP / git deploy) → set `TEN_SFTP_*` in `.env`, publish to the real site with `ten_static`.
    Until then the export bundle + staging site are the honest fallback.
13. LinkedIn developer app + page admin → Settings → Integrations → Connect LinkedIn.
14. Brand assets (OG image, author bio) → Settings → General.

**Deploy (plan §19):** `docs/runbook.md` → Docker Compose on the VPS, Caddy TLS, daily backups
(`infra/systemd/layerflow-backup.timer` or cron), monthly `scripts/restore_check.sh`.
