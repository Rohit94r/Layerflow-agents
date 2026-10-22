-- LayerFlow Agents — Postgres initialisation
-- Runs once, when the `pgdata` volume is first created (docker-entrypoint-initdb.d).
-- Schema is managed by Alembic migrations, not here.

-- gen_random_uuid() and digest helpers
create extension if not exists pgcrypto;

-- Trigram index support for fast title search on feed_items (plan §7.3)
create extension if not exists pg_trgm;

-- pgvector is OPTIONAL and not required. Dedupe and similarity fall back to
-- SimHash + TF-IDF cosine in Python when it is absent. To enable it, use a
-- Postgres image that ships pgvector (e.g. pgvector/pgvector:pg16) and run:
--   create extension if not exists vector;
