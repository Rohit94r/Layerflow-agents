# LayerFlow Agents

Agent-powered editorial engine for **The Executive Narrative** — discover, research, write, format, optimize, review, publish.

> **Full plan:** [`plan.md`](./plan.md)
> **Status:** planning. No application code yet — this repo currently holds the plan of record.

---

## The short version

| Question | Answer |
| --- | --- |
| What is this? | A reusable content operations engine ("Powered by LayerFlow") that runs TEN and later other brands. |
| Does it need paid AI APIs? | No. Open-weight models served locally via Ollama. No per-article cost. |
| Can it run on the mentor's VPS? | Yes for the app, DB, queue, and agents. The model needs 8 GB RAM to be useful; smaller boxes split the model onto another machine over Tailscale. |
| Does it publish automatically? | To the website: yes, once site access exists (export bundle until then). To LinkedIn: only with an approved developer app; otherwise draft + one-click copy. |
| Is human approval required? | Yes. Nothing publishes without review. |
| What's the first measurable win? | Fixing the live site: broken sitemap (localhost URLs), duplicate titles on ~168 articles, no meta descriptions, no canonicals, no OG tags, no JSON-LD. |

## Quick start (once code lands)

```bash
cp .env.example .env
docker compose up -d
# dashboard: http://localhost:3000
# api:       http://localhost:8000/api/v1/health
```

## Planned architecture

```
Next.js dashboard ──► FastAPI ──► Postgres (state + job queue)
                         │
                         └──► Worker ──► Ollama (local LLMs + embeddings)
                                  ├──► Fetcher (RSS / GDELT / EDGAR / HTML)
                                  └──► Adapters (TEN · WordPress · webhook · LinkedIn)
```

## The pipeline

```
Discover → Research → Write → Edit → SEO → QA → Review → Schedule → Publish → LinkedIn
```

Each arrow is a persisted, retryable job with logs — not a single mega-prompt.

## Agents

| Agent | Job |
| --- | --- |
| A0 Orchestrator | Deterministic routing, retries, budgets (no LLM) |
| A1 Discovery | Free-source news finding, dedupe, scoring, category routing |
| A2 Research | Source-grounded evidence pack, refuses on thin evidence |
| A3 Writer | Six category playbooks, mentor's voice, section-by-section |
| A4 Editor | Structure, formatting, banned phrases, no new facts |
| A5 SEO | Title, meta, slug, internal links, JSON-LD, OG |
| A6 QA / Critic | Adversarial rubric scoring against the sources |
| A7 Scheduler | Timezone-safe, no duplicate publishing |
| A8 Publisher | Idempotent adapters + guaranteed export bundle |
| A9 Distribution | LinkedIn post generation, publish when permitted |

## Repository layout

```
apps/web        Next.js dashboard
apps/api        FastAPI + agents + worker
packages/contracts  JSON schemas shared by TS and Python
prompts/        Versioned prompts (system, persona, categories, agents)
config/         Sources, competitors, tenant config
templates/ten   HTML template matched to the live site
evals/          Golden set + style samples
scripts/        Benchmarks, evals, crawl, seed, backup
docs/           ADRs, runbook, demo script
```

## Non-goals (v1)

Rebuilding the public TEN site · autonomous publishing without review · fine-tuning on the VPS · keyword volumes/rank tracking · keyword-level paid SEO data · scraping paywalled content · LinkedIn browser automation.

## License

Private project. All rights reserved unless agreed otherwise with the stakeholders.
