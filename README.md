# LayerFlow Agents

Agent-powered editorial engine for **The Executive Narrative** — discover, research, write, format, optimize, review, publish.

> **Start here:** [`SETUP.md`](./SETUP.md) · **Plan of record:** [`plan.md`](./plan.md) · **Runbook:** [`docs/runbook.md`](./docs/runbook.md) · **Demo:** [`docs/demo-script.md`](./docs/demo-script.md) · **ADRs:** [`docs/decisions/`](./docs/decisions/)

---

## The short version

| Question | Answer |
| --- | --- |
| What is this? | A reusable content operations engine ("Powered by LayerFlow") that runs TEN and later other brands. |
| Does it need paid AI APIs? | No. Open-weight models served locally via Ollama. No per-article cost. |
| Can it run on the mentor's VPS? | Yes for the app, DB, queue, and agents. The model needs 8 GB RAM to be useful; smaller boxes split the model onto another machine over Tailscale. |
| Does it publish automatically? | To the website: yes, once site access exists (export bundle + local staging site until then). To LinkedIn: only with an approved developer app; otherwise draft + one-click copy. |
| Is human approval required? | Yes. Nothing publishes without review. |
| What's the first measurable win? | Fixing the live site: broken sitemap (localhost URLs), duplicate titles, no meta descriptions, canonicals, OG tags or JSON-LD — the SEO workspace produces the fix list and a corrected sitemap. |

## Quick start (Docker, the VPS path)

```bash
cp .env.example .env          # set APP_SECRET_KEY, POSTGRES_PASSWORD, ADMIN_EMAIL, ADMIN_PASSWORD, DOMAIN
docker compose up -d          # api runs migrations + bootstrap (tenant, ~40 sources, admin) on start
docker compose exec ollama ollama pull qwen2.5:7b-instruct
docker compose exec ollama ollama pull qwen2.5:3b-instruct
docker compose exec ollama ollama pull nomic-embed-text
# dashboard: https://$DOMAIN   (local: http://localhost:3000 via docker-compose.override.yml)
# health:    https://$DOMAIN/api/v1/health
```

## Local development without Docker

```bash
# backend (Python 3.12)
cd apps/api
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"      # Linux/macOS: .venv/bin/pip
set DATABASE_URL=sqlite+aiosqlite:///./data/dev.db                 # export … on Linux/macOS
set MODEL_PROVIDER=ollama                                          # or mock (labelled in the UI)
python -m app.cli migrate
python -m app.cli bootstrap
python -m app.cli create-admin --email you@example.com --password "a-long-password"
uvicorn app.main:app --reload --port 8000                          # API
python -m app.worker                                               # agents (separate terminal)
pytest                                                             # tests (mock model, mocked internet)

# frontend (Node 22+)
cd apps/web && npm install && npm run dev                          # http://localhost:3000 (proxies /api to :8000)
```

## Architecture

```
Next.js dashboard ──► FastAPI ──► Postgres (state + job queue, FOR UPDATE SKIP LOCKED)
                         │
                         └──► Worker ──► Ollama (local LLMs + embeddings)   [model lane: 1 job at a time]
                                  ├──► Fetcher (RSS / GDELT / EDGAR / HN / Reddit / HTML)  [io lane]
                                  └──► Adapters (export bundle · ten_static · WordPress · webhook · LinkedIn)
```

## The pipeline

```
Discover → Research → Write → Edit → SEO → QA → Review → Schedule → Publish → LinkedIn
```

Each arrow is a persisted, retryable job with logs (streamed to the Studio over SSE) — not a single mega-prompt.
Every stage writes an immutable article version; every model call is recorded in `model_runs`.

## Agents

| Agent | Module | Job |
| --- | --- | --- |
| A0 Orchestrator | `apps/api/app/agents/orchestrator.py` | Deterministic routing, revise loop (max 2), state machine — no LLM |
| A1 Discovery | `agents/discovery.py` | Keyless sources, canonical URLs, SimHash + TF-IDF/embedding dedupe, transparent scoring, rules-first routing |
| A2 Research | `agents/research.py` | Robots-respecting fetch + extraction, injection defence, evidence pack; refuses on thin evidence |
| A3 Writer | `agents/writer.py` | Six category playbooks, section-by-section, numbers checked against evidence inside the repair loop |
| A4 Editor | `agents/editor.py` | Deterministic formatting + model pass rejected if it adds a number |
| A5 SEO | `agents/seo.py` | Title/meta/slug validators, keywords, verified internal links, OG/Twitter, JSON-LD |
| A6 QA / Critic | `agents/critic.py` | Hard gates (grounding, structure, length, banned phrases, duplication, SEO) + adversarial rubric |
| A7 Scheduler | `agents/scheduler.py` | Timezone/DST-safe cadence slots, missed windows publish once (flagged late) |
| A8 Publisher | `agents/publisher.py` | Idempotent adapters, atomic writes, sitemap repair, rollback, export bundle backup |
| A9 Distribution | `agents/distribution.py` | LinkedIn post rules; official API only; copy/open fallback |

## Repository layout

```
apps/web            Next.js dashboard (Dashboard · News · Studio · Review · SEO · Calendar · Social · Settings)
apps/api            FastAPI + agents + worker + CLI + Alembic + tests
prompts/            Versioned prompts (system, persona, style, categories, agents)
config/             Sources (feeds.yaml), competitors, tenant seed (tenants/ten.json)
templates/ten       Article template matched to the live site's markup
evals/              Golden set (20 cases) + style samples
scripts/            bench_model, eval_agents, crawl_site, seed_demo, backup, restore_check
infra/              Postgres init
docs/               ADRs, runbook, demo script
```

## Non-goals (v1)

Rebuilding the public TEN site · autonomous publishing without review · fine-tuning on the VPS · keyword volumes/rank tracking · paid SEO data · scraping paywalled content · LinkedIn browser automation.

## License

Private project. All rights reserved unless agreed otherwise with the stakeholders.
