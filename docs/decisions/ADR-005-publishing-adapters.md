# ADR-005: Adapter pattern for publishing; export bundle as the guaranteed fallback

- **Status:** Accepted
- **Date:** 2026-10-20
- **Deciders:** Rohit Jadhav

## Context

The live TEN site appears to be a static HTML template (jQuery vendor bundle, `assets/imgs/template/*`, no CMS signatures). We do not yet have deploy access (SFTP/SSH, git or an API). Future tenants may run WordPress or have their own pipelines. A demo must never fail because publishing credentials are missing.

## Decision

1. Publishing goes through a `PublishAdapter` interface: `validate`, `publish(dry_run)`, `update(remote_id)`, `unpublish`, `health`. The publisher agent (A8) knows nothing about the target beyond this interface.
2. Adapters:
   - `export_bundle` — **always available.** A ZIP with `index.html`, `meta.json`, `schema.json`, assets and a sitemap entry, downloadable from the dashboard.
   - `ten_static` — renders the article with TEN's own page template (`templates/ten/article.html`), regenerates `sitemap.xml` with real absolute URLs (fixing the current localhost sitemap) and delivers to a local directory or over SFTP.
   - `wordpress_rest` — WordPress REST API with an application password.
   - `webhook` — signed JSON POST to a tenant's deploy pipeline.
3. Safety rules for every adapter:
   - Idempotency key `sha256(tenant + slug + content_hash)`; a repeated publish of the same content returns the existing publication. A re-publish of edited content updates the same remote URL rather than creating a second page.
   - Atomic delivery: render to a temporary location, validate (single H1, no template placeholders, internal links resolve), stage, then rename into place. A failed upload leaves production untouched.
   - Verify after publish: the live URL returns 200 and contains the H1.
   - Keep the previous artifact and sitemap so `unpublish` / rollback restores them.
   - Never delete remote files the engine did not create.
   - Dry-run renders and previews without touching the target.

## Consequences

**Positive**

- The demo always ends with a real, inspectable artifact.
- Switching from export to live publishing is a configuration change once access exists.
- New tenants with different stacks need a new adapter, not a new engine.

**Negative**

- `ten_static` must track the live template precisely; template changes on the site require updating ours.
- Export bundles require a manual upload step until access is granted.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Rebuild TEN on a headless CMS | Out of scope (plan §1.3); the public site stays as-is. |
| Direct FTP writes with no staging | Risk of half-written pages and broken sitemaps. |
| Browser automation of a site admin | Brittle and unnecessary for a static site. |
