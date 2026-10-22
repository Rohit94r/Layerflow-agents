"""Tenant settings: defaults, deep merge and typed accessors. Stored in tenants.settings (JSON)."""

from __future__ import annotations

import copy
from typing import Any

from app.core.config import get_settings

AGENT_KEYS = ("discovery", "research", "writer", "editor", "seo", "critic", "linkedin")


def default_settings() -> dict[str, Any]:
    s = get_settings()
    return {
        "brand": {
            "name": "The Executive Narrative",
            "short_name": "TEN",
            "site_url": s.ten_site_url,
            "logo_url": f"{s.ten_site_url.rstrip('/')}/assets/imgs/template/logo/logo-dark.png",
            "og_image_url": f"{s.ten_site_url.rstrip('/')}/assets/imgs/template/logo/logo-dark.png",
            "author_name": "The Executive Narrative Editorial",
            "author_bio": "",
            "powered_by": "Powered by LayerFlow",
        },
        "spelling": "en-US",
        "cadence": {
            "per_day": 2,
            "slots": ["08:30", "17:30"],
            "weekdays_only": True,
            "max_per_category_per_day": 1,
        },
        "scoring": {"recency": 0.30, "entity": 0.25, "signal": 0.20, "source": 0.15, "novelty": 0.10},
        "watchlist": {"companies": [], "people": [], "sectors": [], "regions": []},
        "avoid": {"companies": [], "topics": []},
        "discovery": {
            "lookback_hours": 24,
            "max_items": 300,
            "llm_enrich": True,
            "enrich_top_k": 12,
            "auto_disable_after_failures": 5,
        },
        "research": {"max_fetches": 6, "min_sources": 2, "max_facts": 12},
        "quality": {"max_revisions": 2, "duplication_max": 0.08, "flesch_min": 45, "flesch_max": 65, "avg_sentence_max": 24},
        "models": {
            "agents": {
                "discovery": {"model": s.model_fast, "temperature": 0.1, "max_tokens": 400},
                "research": {"model": s.model_writer, "temperature": 0.2, "max_tokens": 1800},
                "writer": {"model": s.model_writer, "temperature": 0.5, "max_tokens": 1400},
                "editor": {"model": s.model_writer, "temperature": 0.3, "max_tokens": 1400},
                "seo": {"model": s.model_writer, "temperature": 0.3, "max_tokens": 600},
                "critic": {"model": s.model_writer, "temperature": 0.1, "max_tokens": 1200},
                "linkedin": {"model": s.model_writer, "temperature": 0.6, "max_tokens": 700},
            }
        },
        "publishing": {"default_target": s.publish_target},
        "social": {"emoji": False, "link_in_post": True, "author_type": "organization"},
    }


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def effective(tenant_settings: dict[str, Any] | None) -> dict[str, Any]:
    return deep_merge(default_settings(), tenant_settings or {})


def agent_model(tenant_settings: dict[str, Any] | None, agent: str) -> dict[str, Any]:
    eff = effective(tenant_settings)
    cfg = dict(eff["models"]["agents"].get(agent) or {})
    s = get_settings()
    cfg.setdefault("model", s.model_writer)
    cfg.setdefault("temperature", 0.4)
    cfg.setdefault("max_tokens", 1200)
    cfg.setdefault("num_ctx", s.model_num_ctx)
    return cfg


def validate_scoring(weights: dict[str, float]) -> dict[str, float]:
    keys = ("recency", "entity", "signal", "source", "novelty")
    cleaned = {k: max(0.0, float(weights.get(k, 0))) for k in keys}
    total = sum(cleaned.values()) or 1.0
    return {k: round(v / total, 4) for k, v in cleaned.items()}
