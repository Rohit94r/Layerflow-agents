# LayerFlow Agents — VC, Sales & Hosting Explainer

> Companion to `layerflow-architecture.html`. Use this as the talk track for an investor meeting, a sales call, or a technical walkthrough.
>
> **Evidence note:** the architecture page is pinned to committed revision `56452c8`. The current working tree also contains uncommitted source-catalog and lead-image work; do not present those as shipped until they are committed and tested.

---

## 0. The one-liner

**LayerFlow is an editorial operating system for executive content: it discovers real news, grounds every claim in sources, writes in a defined voice, runs SEO and QA, and publishes only after human approval — with no per-token model bill.**

Short variants:

| Context | Line |
| --- | --- |
| VC | “We turn one editor into a full executive-newsroom output — discovery, research, drafting, SEO and publishing — with evidence and approval built in.” |
| Customer | “Your team keeps editorial control; the engine removes the research, drafting and SEO grind.” |
| Technical | “A stateful, retryable agent pipeline on Postgres, local open-weight models, and deterministic gates around every model call.” |
| Honest | “Not another AI writer. A governed content operation that refuses to publish thin evidence.” |

What it is **not**:

- Not a generic chatbot or a one-prompt article generator.
- Not a model lab; the model is swappable and not the moat.
- Not autonomous publishing; a human approves.
- Not a paid-SEO-data product; SEO is on-page and structural.

---

## 1. How to explain it to a VC

### 1.1 The 60-second narrative

> “Executive content is expensive and slow: research, writing, editing, SEO, compliance and publishing are separate handoffs. Generic AI made drafting cheap, but it also made trust scarce — hallucinated numbers, no sourcing, no audit trail, and content that search engines and AI answer engines cannot parse.
>
> LayerFlow is the operating system for trustworthy executive content. It watches real sources, builds an evidence pack, writes in the brand’s voice, runs SEO and QA gates, and routes the result to a human for approval. Every stage is a persisted job with logs and versions, so the output is auditable.
>
> We run open-weight models on our own hardware, so there is no per-article API bill. The first deployment is The Executive Narrative, our own executive publication. The same engine is tenant-scoped, so the next brand is a configuration, not a rebuild.
>
> We are raising **[amount]** to prove the content engine on TEN, sign **[N]** design partners, and productize onboarding and analytics.”

### 1.2 Slide-by-slide story

| Slide | What to say | Evidence to show |
| --- | --- | --- |
| **Problem** | Content teams are judged on volume, quality, speed and search visibility — but the workflow is fragmented and AI output is untrustworthy. | Current TEN site audit: missing titles, meta descriptions, canonicals, OG tags, JSON-LD; ~168 articles that search/social cannot read properly. |
| **Why now** | Open-weight 7B–8B models are good enough for structured editorial work; local inference removes the per-token cost barrier; AI search increases the premium on structured, sourced content. | Working system with local Ollama; no paid model API. |
| **Product** | An end-to-end editorial pipeline: discover → research → write → edit → SEO → QA → review → schedule → publish → distribute. | Live demo: News → Studio → Review → Calendar. |
| **Proof** | It runs on real news, produces real drafts, streams stage logs, versions every change, and refuses thin evidence. | Real database records, real source URLs, QA report, article versions. |
| **Business model** | Platform subscription per brand/tenant, plus optional managed content and setup services. | Pricing worksheet in §3.7; pilot structure in §3.8. |
| **GTM** | Start with our own publication to prove the loop; then boutique media, B2B consultancies, VC/PE content arms and corporate executive communications. | TEN as the reference account; design-partner pipeline. |
| **Moat** | The moat is the governed workflow — source catalog, grounding, QA gates, versioning, SEO repair, publishing adapters — not the model. | Architecture page: deterministic orchestrator + evidence + human approval. |
| **Competition** | Writing assistants stop at text. Agencies stop at labour. LayerFlow owns discovery through publication, with an audit trail and private deployment. | Comparison table in §3.6. |
| **Roadmap** | Multi-tenant onboarding, more publishing targets, analytics/rank feedback, model routing, vertical playbooks. | Current tenant-scoped schema; adapter interface. |
| **Ask** | Fund the proof: TEN output, design partners, reliability and onboarding. | Use of funds: **[team / GPU / GTM / compliance]** with real numbers. |

### 1.3 The strongest framing

**“Trust is the bottleneck, not generation.”**

Most competitors sell faster text. LayerFlow sells a **defensible editorial process**:

1. **Evidence before prose** — research refuses when there are fewer than two usable sources.
2. **Deterministic gates around probabilistic models** — state machine, validators, SEO checks, QA rubric, revision cap.
3. **Audit by default** — every job, model call, article version and transition is recorded.
4. **Private and cheap to run** — local open-weight models; no per-token API dependency.
5. **Distribution built in** — canonical URLs, sitemap repair, JSON-LD, OG tags, LinkedIn drafts.

### 1.4 What to say — and what to avoid

| Say | Avoid |
| --- | --- |
| “We use open-weight models locally and can swap in a stronger OpenAI-compatible endpoint.” | “We built our own foundation model.” |
| “The model is commodity; the workflow and evidence layer are the product.” | “The AI writes perfect articles.” |
| “A human approves every publish.” | “Fully autonomous newsroom.” |
| “The data model is tenant-scoped; multi-tenant onboarding is next.” | “We are already multi-tenant SaaS.” |
| “We measure hours saved, cost per published piece, QA pass rate and SEO fixes shipped.” | Invented traction, GMV or customer counts. |
| “No per-token API bill; you pay for compute and review.” | “Zero cost.” |

### 1.5 Due-diligence answers

**“What is defensible?”**
The source catalog, grounding and QA policy, publishing adapters, tenant configuration, and the accumulating editorial/QA data. A competitor can call the same model; reproducing the governed workflow and customer-specific playbooks is harder.

**“Why won’t OpenAI/Google kill you?”**
They improve the model layer, which helps us. They do not own the customer’s editorial policy, source allow-list, approval workflow, SEO repair or publishing integrations. We can route to them when quality demands it.

**“What is the wedge?”**
One owned publication (TEN) proves the full loop. The first external wedge is a content-heavy B2B brand or boutique publisher with an editor already in place — not a company with no editorial function.

**“What are the unit economics?”**
Software gross margin is high because inference is self-hosted; the real cost is compute, support and human review. Model it as: `price per tenant − (VPS + model host + support hours + payment fees)`. Fill in your actual numbers; do not quote a margin you have not measured.

**“What is the biggest risk?”**
Quality and trust. The answer is not a bigger prompt; it is evidence gating, human review, evaluation suites and a narrow category/voice. Show the QA report and the refusal path.

**“What have you actually built?”**
A working end-to-end system: FastAPI + Postgres job queue, two-lane worker, nine agents, local model provider, SEO workspace, review queue, scheduler, publishing adapters, audit log and eval harness. Be explicit about what is still manual: site access, LinkedIn approval, multi-tenant UI.

### 1.6 Metrics to put on the proof slide

Only use measured values. Pull them from the dashboard/database:

- Candidates discovered per day; sources responding successfully.
- Research → draft → approved cycle time.
- Percentage of drafts that pass QA on the first attempt vs after revision.
- Human edit minutes per published piece.
- Cost per published piece (compute + review time).
- SEO defects fixed per article (title, meta, canonical, OG, JSON-LD, internal links).
- Publishing success rate and rollback count.
- Articles published per week per editor.

---

## 2. How to explain the selling side

### 2.1 ICP and buyer

**Best-fit customer**

- A B2B media brand, boutique analyst firm, consultancy, VC/PE content arm, or corporate executive-communications team.
- Publishes 2–20 substantive pieces per week.
- Already has an editor or subject-matter reviewer.
- Cares about brand voice, sourcing, search visibility and approval.
- Is uncomfortable sending unpublished strategy to a public AI API.

**Buyer roles**

| Role | What they buy | What they fear |
| --- | --- | --- |
| Founder / CEO | Output without headcount; speed | Brand damage, wasted spend |
| Head of Content / Editor | Research and drafting leverage | Loss of voice, more editing work |
| CMO | Consistent executive thought leadership | Generic AI slop, compliance risk |
| COO / Finance | Lower cost per piece | Unbounded API/tool sprawl |
| IT / Security | Private deployment, audit trail | Data leakage, shadow AI |

### 2.2 Pain → outcome

| Pain today | LayerFlow outcome |
| --- | --- |
| Research eats the week | Source discovery + evidence pack in minutes |
| Writers start from a blank page | Structured draft in the category playbook |
| Every writer sounds different | Persona/style system + editor pass |
| SEO is a separate afterthought | Title, meta, slug, keywords, internal links, OG, JSON-LD in the same flow |
| AI output cannot be trusted | Grounding gate, numeric checks, QA rubric, human approval |
| Publishing is a manual relay | Adapters for static site, WordPress, webhook, export, LinkedIn draft |
| No audit trail | Versions, job events, model runs, transition log |
| Per-seat AI costs explode | Local inference; no per-token API bill |

### 2.3 The 30-second sales pitch

> “Your editors are paid to judge, not to hunt feeds, rebuild context and hand-fix SEO. LayerFlow does the discovery, research, first draft, edit pass, SEO and publishing prep, then puts the result in front of your editor with every claim sourced. You approve; it publishes. It runs privately on your infrastructure, and there is no per-article AI bill.”

### 2.4 Discovery questions

1. How many substantive pieces do you publish per week, and who touches each one?
2. Where does the time actually go: finding stories, research, drafting, editing, SEO, approvals or publishing?
3. What does a published piece cost you today, including agency/editor hours?
4. Which sources are allowed, and which are off-limits?
5. Who has final approval, and what would make them reject a draft?
6. What does “on-brand” mean here? Show me one piece you are proud of and one you are not.
7. How do you measure success: traffic, pipeline, authority, newsletter growth, sales conversations?
8. What AI tools are you using now, and why did they not stick?
9. What are your security constraints for unpublished strategy?
10. If a pilot saved X hours per week, who would need to sign off to expand?

### 2.5 Demo flow mapped to value

Use `docs/demo-script.md` for the full 10-minute version. The sales mapping:

| Demo screen | Say this | Value proven |
| --- | --- | --- |
| News | “These are real items from today, scored and deduplicated.” | Discovery is not a prompt; it is a monitored source portfolio. |
| Studio / Research | “Every fact has a source; if there are fewer than two, it refuses.” | Trust and grounding. |
| Studio / Draft | “It writes to the category structure and brand voice.” | Consistency without a blank page. |
| Studio / Versions | “The editor pass changed flow but added no new numbers.” | Control over hallucination. |
| SEO | “Title, meta, slug, internal links, OG, JSON-LD are generated and validated.” | Distribution is built in. |
| Review | “Your editor approves or sends it back with an instruction.” | Human authority is preserved. |
| Calendar | “Cadence guards prevent category collisions; dry run first.” | Operational reliability. |
| Social | “LinkedIn post is prepared; auto-post only with an approved app.” | Honest distribution path. |
| Settings / Models | “Local model, no API key; swap the endpoint if you want.” | Cost and privacy. |

### 2.6 Objection handling

| Objection | Response |
| --- | --- |
| “AI content is generic slop.” | “Agreed — that is why the product is a governed pipeline, not a prompt. It grounds claims, enforces the brand voice, runs QA and requires human approval.” |
| “It will hallucinate numbers.” | “The writer checks numbers against the evidence pack; the editor is rejected if it adds a number; QA blocks on grounding. It also refuses when evidence is thin.” |
| “Our editors will hate it.” | “It removes the work they dislike — feed hunting, context rebuilding, SEO plumbing — and leaves judgment and approval with them. Start with one editor as design partner.” |
| “We can just use ChatGPT.” | “You can, but you will rebuild the source policy, QA, versioning, SEO repair, scheduling and publishing around it. That workflow is the product.” |
| “Is our data safe?” | “The model can run on your VPS or a private GPU host; no per-token third-party API is required. Access is role-based and every action is audited.” |
| “We do not have site access.” | “Start with the export bundle and local staging; connect SFTP/WordPress/webhook when access is available.” |
| “LinkedIn automation?” | “We prepare the post and copy/open it today. Official auto-posting turns on when the LinkedIn developer app is approved.” |
| “What about SEO rank tracking?” | “We do on-page and structural SEO, not paid keyword/backlink data. We can integrate a data provider later.” |
| “Lock-in?” | “Content exports as HTML/JSON with schema and sitemap entries; publishing adapters are pluggable.” |
| “Can it handle our categories?” | “Categories are playbooks with structure and word ranges; a new vertical is configuration plus prompts, not a new codebase.” |

### 2.7 Pricing and packaging talk track

Do **not** quote a number you cannot defend. Use a packaging frame:

1. **Platform licence** — per brand/tenant, monthly or annual. Covers the engine, sources, pipeline, SEO, review, publishing adapters and updates.
2. **Setup / onboarding** — source catalog, brand voice, templates, integrations, first category calibration.
3. **Managed content** — optional human editorial layer (review, fact-check, publishing) priced per piece or as a retainer.
4. **Private model host** — optional GPU box or dedicated inference; pass through compute or bundle it.

Value anchor:

> “Compare it with one content hire or one agency retainer. The engine does not replace the editor; it removes the research, drafting and SEO hours around the editor.”

Cost worksheet (fill in):

| Line                               | Monthly                  |
| ---------------------------------- | ------------------------ |
| VPS (app + Postgres)               | `[your cost]`            |
| Model host (local GPU or CPU)      | `[your cost]`            |
| Backups / monitoring               | `[your cost]`            |
| Support / editorial review hours   | `[hours × rate]`         |
| Payment / admin                    | `[your cost]`            |
| **Total cost to serve one tenant** | `[sum]`                  |
| Proposed price                     | `[price]`                |
| **Gross margin**                   | `[price − cost] / price` |

### 2.8 Pilot → expansion

**30-day pilot**

- One brand, one or two categories, 3–5 pieces per week.
- Baseline: hours per piece, cost per piece, SEO defects, publish cycle time.
- Success criteria agreed in writing: e.g. 40% reduction in research/drafting hours, 90% QA pass after one revision, 100% of published pieces with valid metadata and schema.
- Weekly review with the editor; capture objections as product backlog.

**Expansion**

- Add categories → add seats/editors → add brands/tenants → add distribution channels.
- Land with an editor, expand to the content team, then to other brands in the same group.

---

## 3. Backend model stack

### 3.1 Provider architecture

The model layer is abstracted behind `ModelProvider` and wrapped by `GuardedProvider` with a circuit breaker (3 failures → 60-second cooldown). Supported providers:

| Provider | Use | Notes |
| --- | --- | --- |
| `ollama` (default) | Local open-weight models | No API key, no per-token bill; runs on CPU or GPU |
| `openai_compat` | Any OpenAI-compatible endpoint (vLLM, llama.cpp server, LM Studio, hosted API) | Set `OPENAI_COMPAT_BASE_URL` and `OPENAI_COMPAT_API_KEY` |
| `mock` | Tests and offline demos | Deterministic extractive output; labelled in the UI |

### 3.2 Exact default models

From `apps/api/app/core/config.py`:

| Setting | Default | Role |
| --- | --- | --- |
| `MODEL_PROVIDER` | `ollama` | Local inference |
| `MODEL_WRITER` | `qwen2.5:7b-instruct` | Research, writing, editing, SEO, QA, LinkedIn |
| `MODEL_FAST` | `qwen2.5:3b-instruct` | Discovery enrichment/classification |
| `MODEL_EMBED` | `nomic-embed-text` | Embeddings for dedupe/similarity; optional (TF-IDF fallback) |
| `MODEL_NUM_CTX` | `8192` | Context window |
| `MODEL_TIMEOUT_S` | `600` | Per-call timeout |
| `MODEL_CONCURRENCY` | `1` | One model job at a time on CPU |

### 3.3 Per-agent routing

From `apps/api/app/services/tenant_settings.py`:

| Agent | Model | Temperature | Max tokens | Why |
| --- | --- | --- | --- | --- |
| Discovery enrichment | `qwen2.5:3b-instruct` | 0.1 | 400 | Cheap classification of many headlines |
| Research | `qwen2.5:7b-instruct` | 0.2 | 1,800 | Extract facts, entities, counterpoints |
| Writer | `qwen2.5:7b-instruct` | 0.5 | 1,400 | Category-structured draft |
| Editor | `qwen2.5:7b-instruct` | 0.3 | 1,400 | Flow/clarity pass; no new numbers |
| SEO | `qwen2.5:7b-instruct` | 0.3 | 600 | Title, meta, slug, keywords, links |
| Critic / QA | `qwen2.5:7b-instruct` | 0.1 | 1,200 | Adversarial rubric + gates |
| LinkedIn | `qwen2.5:7b-instruct` | 0.6 | 700 | Platform-native post |

Models can be overridden per tenant/agent in **Settings → Models** without a code change.

### 3.4 Why this stack

- **No per-token cost.** The marginal cost is compute/electricity, not API usage. This is the core economic argument.
- **Privacy.** Unpublished strategy and source packs stay on infrastructure you control.
- **Structured output, not free-form.** Every call is schema-constrained; invalid output gets a repair loop (max 2), then a deterministic fallback or a clean failure.
- **Auditable.** Every model call is recorded in `model_runs`; every stage is a job with events.
- **Swappable.** The same code can use a stronger hosted model when quality matters more than cost.

### 3.5 Quality controls around the model

1. **Grounding:** research builds an evidence pack; QA blocks when grounding is insufficient.
2. **Numeric checks:** the writer verifies numbers against evidence; the editor is rejected if it introduces a number.
3. **Deterministic validators:** slug, title length, meta length, banned phrases, duplication, readability, structure, SEO.
4. **Revision cap:** QA can send work back to write/edit, capped by `quality.max_revisions` (default 2).
5. **Human approval:** nothing publishes without review.
6. **Evaluation harness:** deterministic, critic and pipeline suites; golden cases.

### 3.6 Hardware and performance reality

| Setup | Experience |
| --- | --- |
| CPU-only, 8 GB RAM | Works; expect roughly 10–25 minutes per article; keep one model loaded and concurrency at 1 |
| Small VPS (< 8 GB) | Run app/DB/worker on the VPS; run Ollama on a larger machine over Tailscale |
| NVIDIA GPU | Ollama uses it automatically; roughly 1–3 minutes per article in the documented setup |
| Hosted OpenAI-compatible endpoint | Fastest path to higher quality; reintroduces per-token cost |

Do not promise “instant.” Promise **throughput with review**, and measure your own hardware with `scripts/bench_model.py`.

### 3.7 How to switch models

1. Pull the model in Ollama: `ollama pull <model>`.
2. Set `MODEL_WRITER` / `MODEL_FAST` / `MODEL_EMBED` in `.env`, or change per-agent models in **Settings → Models**.
3. Restart API and worker.
4. Run **Settings → Models → Test**, then a real article and the evaluation suite.
5. For a hosted endpoint: set `MODEL_PROVIDER=openai_compat`, `OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPAT_API_KEY`; no agent code changes.

---

## 4. Hosting and deployment

### 4.1 Runtime topology

```
Browser
  │ HTTPS 443
  ▼
Caddy  ──────────────► Next.js web :3000
  │  /api/*, /site/*
  ▼
FastAPI API :8000 ─────────► PostgreSQL 16 :5432
  │                              ▲
  │ enqueue jobs                 │ claim jobs (FOR UPDATE SKIP LOCKED)
  ▼                              │
Worker ──────────────────────────┘
  ├──► Ollama :11434 (local model / embeddings)
  ├──► Fetcher ──► public RSS / APIs / article pages
  └──► Publisher ──► static site / WordPress / webhook / export / LinkedIn
```

### 4.2 Services and ports

| Service | Role | Internal port | Public |
| --- | --- | --- | --- |
| `caddy` | TLS termination, reverse proxy | 80 / 443 | **Yes — only public service** |
| `web` | Next.js dashboard (standalone) | 3000 | Via Caddy |
| `api` | FastAPI `/api/v1/*`, SSE, `/site` staging | 8000 | Via Caddy |
| `worker` | Agent jobs, scheduler, housekeeping | none | No |
| `postgres` | Content, queue, audit, versions | 5432 | No |
| `ollama` | Local models (optional `local-model` profile) | 11434 | No |

### 4.3 VPS sizing

- **OS:** Ubuntu 22.04/24.04.
- **Recommended:** 8 GB RAM for the app + a useful 7B model; confirm real vCPU/RAM/disk before choosing a model.
- **Disk:** leave room for Postgres, model weights, fetch cache, artifacts, backups and staged site.
- **CPU-only:** fine for a pilot; slower generation.
- **GPU:** best demo experience; 1–3 minutes per article in the documented setup.

### 4.4 Split model hosting (small VPS)

If the VPS has less than ~8 GB RAM:

1. Keep Caddy, web, API, worker and Postgres on the VPS.
2. Put Ollama on a GPU/larger machine.
3. Join both to a Tailscale tailnet.
4. Bind Ollama to the Tailscale interface only.
5. Set `OLLAMA_BASE_URL=http://<tailscale-ip>:11434` on the VPS.
6. **Never expose port 11434 to the public internet.** An SSH tunnel is an alternative.

### 4.5 Storage, backups and retention

Docker named volumes:

- `pgdata` — PostgreSQL data.
- `ollama_models` — model weights.
- `artifacts` — export bundles and publish artifacts.
- `cache` — fetch cache (7-day default).
- `site` — local staging site for the static adapter.
- `backups` — database dumps.
- `caddy_data`, `caddy_config` — TLS certificates/config.

Backups:

- Daily `pg_dump -Fc` → gzip, keep the last 14.
- Artifacts copied with the backup.
- Monthly restore drill into a scratch database.
- Run `scripts/backup.sh` and `scripts/restore_check.sh`.
- Schedule with the provided systemd timer or cron.

Retention (worker housekeeping):

- Model-run outputs trimmed after 90 days.
- Feed items older than 60 days pruned unless promoted.
- Completed jobs pruned after 30 days.
- Audit logs kept for 365 days.
- Expired sessions deleted.

### 4.6 Security posture

- Only Caddy publishes ports; Postgres and Ollama stay internal.
- HTTPS with automatic certificates; HSTS, `nosniff`, `same-origin` referrer policy, frame denial outside `/site`.
- Session cookie is HTTP-only; mutations use CSRF double-submit.
- Role-based access (`admin`, `content`) and rate limits on login/mutations/reads.
- Integration secrets encrypted with `TOKEN_ENCRYPTION_KEY`.
- Fetcher: SSRF guard (public IPs only), DNS checks, robots.txt for page fetches, per-domain concurrency 1 and configurable minimum interval, 7-day cache, size/time limits.
- Audit log for auth, jobs, article transitions, publishing and settings changes.

### 4.7 Scaling path

1. **Vertical first:** more RAM/CPU, keep one model loaded.
2. **Move the model:** GPU box over Tailscale; app stays small.
3. **More workers:** the Postgres queue supports multiple workers with `SKIP LOCKED`; keep model concurrency at 1 per model host.
4. **More tenants:** tenant-scoped schema already exists; the next work is onboarding, billing and per-tenant isolation UX.
5. **More channels:** add a publishing adapter; the interface is `validate / publish / update / unpublish / health`.

### 4.8 Hosting cost worksheet

| Item                   | Monthly | Notes                                         |
| ---------------------- | ------- | --------------------------------------------- |
| VPS (app + DB)         | `[ ]`   | 8 GB RAM target                               |
| Model host (if split)  | `[ ]`   | GPU or high-RAM CPU                           |
| Object storage/backups | `[ ]`   | Off-box backup copy                           |
| Monitoring/alerts      | `[ ]`   | Webhook + uptime check                        |
| Domain/TLS             | `[ ]`   | Caddy certificates are free                   |
| **Total**              | `[ ]`   | Compare with one content hire/agency retainer |

---

## 5. Plain-English architecture walkthrough

Use this when a non-technical buyer asks “how does it actually work?”

1. **Front door — Caddy.** It terminates HTTPS and sends dashboard traffic to Next.js and `/api` traffic to FastAPI.
2. **Dashboard — Next.js.** The editor sees News, Studio, Review, SEO, Calendar, Social and Settings.
3. **API — FastAPI.** It handles login, tenant scoping, CRUD, and starts jobs. It does not generate articles inside the request.
4. **Queue — PostgreSQL.** A job row is the unit of work. The database is also the content store, audit log and version store. Using the database as the queue means no extra broker to operate.
5. **Worker.** It claims jobs safely, runs one model job at a time plus parallel IO jobs, retries failures with backoff, and recovers stale jobs if a worker dies.
6. **Agents.** Each stage has one job: discovery, research, write, edit, SEO, QA, publish, distribute. The orchestrator is deterministic and decides what runs next; it is not an LLM.
7. **Model endpoint.** Ollama serves open-weight models locally, or an OpenAI-compatible endpoint can be used. A circuit breaker prevents a dead model from hanging every job.
8. **Fetcher.** It pulls feeds and article pages with SSRF protection, robots.txt, rate limits and a cache.
9. **Publisher.** Adapters write the approved article to a static site, WordPress, a webhook or an export bundle; LinkedIn is prepared as a draft unless the official API is connected.
10. **Human review.** The editor approves, rejects or requests a revision. Nothing bypasses this gate.

**Analogy:** it is a newsroom with a desk queue, not a single chatbot. The reporter, fact-checker, copy editor, SEO editor and publisher are separate jobs with their own logs; the editor-in-chief still signs off.

---

## 6. Condensed 10-minute demo

Full version: `docs/demo-script.md`.

1. **Problem (1 min):** open the live site’s sitemap and an article’s source — missing titles, meta, canonical, OG, JSON-LD.
2. **Discovery (1.5 min):** dashboard + News; real items, scores, duplicates, regions.
3. **One article (4 min):** promote a story; show stage timeline, research sources, draft structure, version diff, SEO workspace.
4. **Control (1.5 min):** Review queue; reject one with a reason, approve another; show QA scores.
5. **Publish (1 min):** dry run, schedule/publish, live/staging URL, corrected sitemap.
6. **Distribution (45 s):** LinkedIn draft; honest connection state.
7. **Business case (45 s):** Settings → Models (local, no API key), Sources (curated feeds), Integrations; “next brand is a tenant config.”
8. **Honesty (30 s):** what is manual today — site access, LinkedIn approval, multi-tenant UI, paid SEO data, human fact-check.

---

## 7. Honest gaps and how to frame them

| Gap | Frame |
| --- | --- |
| No multi-tenant onboarding UI yet | “The data model is tenant-scoped; onboarding is the next product layer, not a schema rewrite.” |
| LinkedIn auto-post needs API approval | “We prepare the post and support one-click copy/open today; auto-post switches on with the approved app.” |
| Live-site publishing needs access | “Export bundle and local staging work today; SFTP/WordPress/webhook connects when access exists.” |
| 7B model is not frontier quality | “The workflow compensates with grounding, structure and QA; the model is swappable when quality matters more than cost.” |
| CPU generation is slow | “Pilot on CPU; move the model to a GPU box for production throughput. Measure before promising SLAs.” |
| No paid keyword/backlink data | “We fix on-page and structural SEO; paid data is an integration, not a dependency.” |
| Human review is still required | “That is the product, not a limitation: trust is the bottleneck, and the editor owns the judgment.” |
| Uncommitted image/source work | “Current working tree adds lead-image collection and the curated source catalog; it is not in the committed architecture page yet.” |

---

## 8. Copy-paste assets

### 8.1 VC intro email

> Subject: **LayerFlow — the editorial OS for trustworthy executive content**
>
> Hi `[name]`,
>
> We built LayerFlow: an editorial operating system that takes executive content from real-source discovery to grounded research, drafting, SEO, QA and human-approved publishing. It runs open-weight models locally, so there is no per-article API bill, and every claim, version and stage is auditable.
>
> The first deployment is The Executive Narrative, our own executive publication. The same engine is tenant-scoped, so the next brand is configuration, not a rebuild.
>
> We are raising `[amount]` to prove the content loop on TEN and sign `[N]` design partners. Would you be open to a 20-minute walkthrough?
>
> `[name]`

### 8.2 Sales intro email

> Subject: **A faster research-to-publish loop — with your editor in control**
>
> Hi `[name]`,
>
> Your team publishes `[N]` substantive pieces a week. The bottleneck is rarely the writing itself — it is finding the story, rebuilding context, fixing SEO and coordinating approval.
>
> LayerFlow does discovery, research, first draft, edit pass, SEO and publishing prep, then puts the result in front of your editor with every claim sourced. You approve; it publishes. It runs privately, and there is no per-article AI bill.
>
> If I mapped your current workflow to a 30-day pilot, would that be useful?
>
> `[name]`

### 8.3 30-second elevator pitch

> “LayerFlow is an editorial operating system for executive content. It discovers real news, grounds every claim in sources, writes in your voice, runs SEO and QA, and publishes after your editor approves. It runs on open-weight models locally, so there is no per-token API bill. The first brand is live; the next one is a tenant configuration.”

### 8.4 One-slide architecture caption

> “Caddy is the front door. Next.js is the newsroom UI. FastAPI owns access and starts jobs. Postgres is both the content store and the job queue. The worker runs separate, retryable agent jobs. Ollama serves the local model. Publisher adapters deliver approved work. The orchestrator is deterministic; the model only writes inside evidence and validation gates.”

---

## 9. Glossary

| Term | Meaning |
| --- | --- |
| **Tenant** | One brand/publication configuration (TEN is the first). |
| **Feed item** | A discovered news candidate before promotion. |
| **Article** | A promoted story moving through the pipeline. |
| **Stage** | Research, write, edit, SEO or QA — a persisted job. |
| **Orchestrator** | Deterministic router; validates transitions and enqueues the next stage. |
| **Evidence pack** | Facts, sources, counterpoints and open questions used to ground the draft. |
| **QA / critic** | Hard gates + adversarial rubric; returns pass, revise or block. |
| **Playbook** | Category-specific structure, word range and voice rules. |
| **Adapter** | Publishing target implementation (static, WordPress, webhook, export, LinkedIn). |
| **Model lane / IO lane** | Worker concurrency split: one heavy model job at a time; fetch/publish jobs in parallel. |
| **Mock provider** | Deterministic offline model for tests/demos. |

---

### Final advice

- Lead with the **trust problem**, not the model.
- Show a **real refusal** (thin evidence) and a **real QA report**; they prove the product more than a polished draft.
- Never quote traction, margins or SLAs you have not measured.
- Sell the **editor’s leverage**, not the editor’s replacement.
- For hosting, promise a **measured** throughput on a named machine, not “instant.”
