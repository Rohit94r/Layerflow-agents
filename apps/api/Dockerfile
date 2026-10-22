# LayerFlow API + worker image (same image, different command). Build context: repository root.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CONTENT_ROOT=/srv/layerflow \
    SITE_ROOT=/data/site \
    ARTIFACTS_DIR=/data/artifacts \
    FETCH_CACHE_DIR=/data/cache \
    BACKUP_DIR=/data/backups

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 layerflow

WORKDIR /app
COPY apps/api/pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py && pip install . && rm -rf app build *.egg-info

COPY apps/api/ ./
RUN pip install --no-deps . && chmod +x /app/docker-entrypoint.sh

# Versioned editorial content the agents read at runtime.
COPY prompts/ /srv/layerflow/prompts/
COPY config/ /srv/layerflow/config/
COPY templates/ /srv/layerflow/templates/
COPY evals/ /srv/layerflow/evals/
COPY scripts/ /srv/layerflow/scripts/

RUN mkdir -p /data/site /data/artifacts /data/cache /data/backups \
    && chown -R layerflow:layerflow /data /srv/layerflow/evals
USER layerflow

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker-entrypoint.sh"]
CMD ["api"]
