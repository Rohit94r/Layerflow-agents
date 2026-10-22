# LayerFlow dashboard (`apps/web`)

Editorial dashboard for The Executive Narrative: Next.js (App Router) + TypeScript + Tailwind v4 + TanStack Query.
It talks only to the FastAPI backend at `/api/v1` (same origin), using the HTTP-only session cookie and a double-submit CSRF header.

```bash
npm install
npm run dev          # http://localhost:3000, proxies /api and /site to API_INTERNAL_URL (default http://localhost:8000)
npm run typecheck
npm run build        # standalone output for the Docker image
npm run test:e2e     # Playwright demo script against a running stack (MODEL_PROVIDER=mock recommended)
```

| Route | Screen |
| --- | --- |
| `/` | Dashboard: live cards, 7-day chart, funnel, agent health, system, activity, failed jobs |
| `/news` | News Feed with filters, score breakdown, dedupe clusters, promote / ignore / bulk promote |
| `/studio`, `/studio/[id]` | Content Studio: stage timeline, editor (sections ⇄ Markdown), versions + diff, research, QA, live log (SSE) |
| `/review` | Review Queue: rendered preview, QA, diff, approve → schedule (dry run), revise, reject · keys `a` `r` `j` `k` |
| `/seo` | SEO Workspace: metadata + previews + JSON-LD, site audit + fix list, inventory, competitors |
| `/calendar` | Month/week calendar, drag to reschedule, publish now, cancel, roll back, bundles |
| `/social` | LinkedIn preview, editor, copy / open / download image, publish when connected |
| `/settings` | General, Sources, Models, Prompts, Persona & Style, Integrations, Evaluations, Danger zone |

Environment: `API_INTERNAL_URL` (build-time rewrite target; `http://api:8000` in Docker Compose).
