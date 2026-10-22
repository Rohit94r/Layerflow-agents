# ADR-006: Tenant-scoped data model from day one, single-tenant UI

- **Status:** Accepted
- **Date:** 2026-10-20
- **Deciders:** Rohit Jadhav

## Context

The engine is meant to be "Powered by LayerFlow": built once for The Executive Narrative, then reused for other companies. Retrofitting multi-tenancy into a data model later is expensive and error-prone (every query, every unique constraint, every file path). Building a full multi-tenant product now — onboarding, billing, tenant switching, SSO — would blow the demo timeline.

## Decision

1. Every business table carries a `tenant_id` (directly, or through a parent that does), and every query is scoped by the current user's tenant in a shared dependency rather than ad hoc.
2. Uniqueness is per tenant: `(tenant_id, email)` for users, `(tenant_id, canonical_url)` for feed items, per-tenant slugs.
3. Tenant-specific behaviour lives in data, not code: `tenants.settings` (brand, timezone, cadence, scoring weights, watchlist, models, spelling), per-tenant prompt versions, per-tenant integration secrets (encrypted), per-tenant templates under `templates/<tenant>/`.
4. Artifacts, caches and exports are stored under tenant-prefixed paths.
5. The UI ships **single-tenant**: no tenant switcher, no onboarding. The default tenant is `ten` (`TENANT_DEFAULT`).
6. Multi-tenant UI, per-tenant credentials management and isolation tests are Phase 9 (post-demo).

## Consequences

**Positive**

- The B2B story is real at the data level from the first commit.
- Adding a second tenant later is configuration plus a template, not a migration of every table.
- Tenant isolation can be tested by construction (every query goes through the scoped dependency).

**Negative**

- Slightly more verbose models and queries now.
- Risk of a forgotten scope on a new query until isolation tests exist — mitigated by the shared dependency and code review.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Single-tenant schema, migrate later | Every table, constraint and path would need rework; high risk of leakage bugs. |
| Database per tenant | Operational overhead (migrations, backups, connections) not justified for one or two tenants. |
| Postgres row-level security now | Good future hardening; adds complexity before there is a second tenant. Revisit in Phase 9. |
