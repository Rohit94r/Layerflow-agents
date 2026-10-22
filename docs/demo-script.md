# Demo script — 10 minutes

The incubation demo for The Executive Narrative, mapped to the actual dashboard screens (plan §22). Every number shown must come from real database records — no seeded fake data.

## Pre-demo checklist (T–60 minutes)

- [ ] `GET /api/v1/health` is all green: database ok, model provider reachable, configured models present, worker heartbeat < 1 minute old, disk < 85%.
- [ ] Top bar model pill is **green** and does **not** say "Mock provider".
- [ ] The writer and embedding models are pulled (`ollama list`) and one warm-up generation has run (Settings → Models → **Test**), so the first demo call is not a cold load.
- [ ] A discovery run completed **within the last hour** (Dashboard → candidates today > 30; News Feed shows timestamps from today).
- [ ] **Backup article:** at least one Brief and one Deep Dive already sitting in the Review Queue, generated earlier from real sources. CPU generation takes 10–25 minutes; do not rely on generating live.
- [ ] One article **in progress** (researching or drafting) so stage streaming is visible live.
- [ ] Publish target set: `ten_static` to the staging path if site access exists, otherwise `export`. Do a dry run once.
- [ ] Social screen loads; LinkedIn banner shows the honest "not connected" state if there is no token.
- [ ] Live TEN site open in a second tab: `/sitemap.xml` and one article page with "view source" ready.
- [ ] Browser zoom at 100%, 1440 px wide, notifications off, theme chosen.
- [ ] Logged in as the owner account.

## The script

### 1. The problem — 60 s (live TEN site)

- Open `theexecutivenarrative.com/sitemap.xml`: it lists only `http://localhost/` and `http://localhost/about`.
- View source on any article: `<title>TEN - The Executive Narrative</title>` on every page, no meta description, no canonical, no Open Graph tags, no JSON-LD, the headline in an `<h3>`.
- Say: "There are around 168 articles that search engines and LinkedIn can't properly read. That's the first thing this engine fixes."

### 2. Discovery — 90 s (`/` then `/news`)

- **Dashboard `/`:** cards for candidates today, drafts in progress, awaiting review, scheduled, published (7d), failed jobs; the pipeline funnel; the agent health table with real latencies.
- **News Feed `/news`:** today's real items with source, timestamp, region, score bar, suggested category and duplicate badges.
- Click **Refresh** to start a live discovery run; point at the progress indicator.
- Open one item's drawer: summary, entities, source link, similar items. Mention the score formula is transparent and editable in Settings.

### 3. One article — 4 min (`/studio/[id]`)

- Promote a real story from the feed (or open the in-progress article).
- **Content Studio `/studio/[id]`:** stage timeline on the left (Research → Write → Edit → SEO → QA) with the live log streaming.
- Research panel: the fetched sources, every key fact with its source URL, counterpoints and open questions. Mention: "If there are fewer than two usable sources, it refuses and says *Needs more sources* instead of inventing."
- Switch to the backup article if generation is still running: show the draft in its category structure, word count, readability and **0 banned-phrase hits**.
- Open version history → diff between the draft and edited versions: the editor improved flow but added no new numbers.
- **SEO Workspace `/seo`** for this article: title tag with character meter, meta description, slug, keywords, intent, internal links with validity, the LinkedIn and Google previews, and the JSON-LD.

### 4. Control — 90 s (`/review`)

- **Review Queue `/review`:** the rendered preview exactly as it will appear, QA scores, issues list, diff against the previous version.
- **Reject** one article with a reason ("angle too generic") — show it archived with the reason recorded.
- Approve another with the keyboard: **`a`** approves (and opens the schedule modal); mention **`r`** requests a revision with an instruction.

### 5. Publish — 60 s (`/calendar`)

- In the schedule modal, run the **dry run** preview, then **Publish now**.
- **Calendar `/calendar`:** the publication appears with its category colour; mention drag-to-reschedule and the cadence guard.
- Open the live/staging URL: correct `<h1>`, title tag, meta description, canonical, OG tags, JSON-LD.
- Open the regenerated `sitemap.xml`: real absolute URLs, including the new article.
- If there is no site access: download the export bundle and show `index.html`, `meta.json`, `schema.json` and the sitemap entry.

### 6. Distribution — 45 s (`/social`)

- **Social `/social`:** the LinkedIn post rendered as a LinkedIn card with the character counter, hashtags (≤3) and the "what this means for leaders" line.
- **Copy post** → **Open LinkedIn**. Point at the honest connection banner: auto-posting switches on when a LinkedIn developer app is approved.

### 7. Business case — 60 s (`/settings`)

- **Settings `/settings`:** Models tab shows the local model and zero API keys; Sources tab shows the free feeds; Integrations shows configured/missing without exposing secrets.
- Say: "This runs on your VPS with zero model API cost. Discovery, research, writing, editing, SEO and publishing are separate stages with logs and retries, and nothing publishes without your approval. The next client is a new tenant config, not a new build."

### 8. Honesty — 30 s

Say plainly what is not done and why:

- **LinkedIn auto-posting** needs a developer app and permission approval; until then the post is prepared and published in one click by a person.
- **Automatic publishing to the live site** needs SFTP/SSH or git access; until then it produces an export bundle.
- **Multi-tenant UI** is post-demo; the data model is already tenant-scoped.
- **No keyword volumes, rank tracking or backlinks** — that needs paid data; we do on-page and structural SEO only.
- **Accuracy is not guaranteed by software**, which is why a human approves every article.

## If something goes wrong

| Problem | Recovery line and action |
| --- | --- |
| Generation is slow | "On CPU a long article takes 10–25 minutes, which is why it runs in a queue." Switch to the backup article in the Review Queue. |
| Model pill turns red | Show the failed job with its error and the **Retry** button: "Failures are visible and retryable, never silent." Continue with already-generated articles. |
| A feed fails during refresh | Show the per-source error in Settings → Sources; other sources still deliver. |
| Publish to the site fails | Switch the target to `export` and download the bundle: "The export path always works." |
| Internet drops | Everything already in the database (feed, articles, reviews, SEO, social drafts) still works; only refresh and research need the network. |
