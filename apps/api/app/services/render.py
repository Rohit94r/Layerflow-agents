"""Render the final article to static HTML with the tenant template (plan §14.3). All model text is
autoescaped; JSON-LD goes through `tojson` (escapes <, >, &), so generated content cannot inject markup."""

from __future__ import annotations

import math
import re
from datetime import datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import escape

from app.core.config import get_settings
from app.services.article_doc import count_words
from app.services.playbooks import get_playbook

FORBIDDEN_MARKUP = re.compile(r"<\s*(script(?!\s+type=\"application/ld\+json\")|iframe|object|embed)\b|\son\w+\s*=", re.I)
PLACEHOLDER = re.compile(r"\{\{|\}\}|\{%|%\}|(?i:lorem ipsum)|\bTODO\b|\bPLACEHOLDER\b")


@lru_cache
def _env(templates_dir: str) -> Environment:
    return Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render_context(
    payload: dict[str, Any], *, brand: dict[str, Any], published_at: datetime | None, timezone: str, spelling: str = "en-US"
) -> dict[str, Any]:
    art = payload.get("article") or {}
    seo = payload.get("seo") or {}
    pb = get_playbook(art.get("category") or "brief")
    site_url = (brand.get("site_url") or get_settings().ten_site_url).rstrip("/")
    local = published_at.astimezone(ZoneInfo(timezone)) if published_at else None
    sections = []
    for s in art.get("sections") or []:
        spec = pb.section(s.get("key", ""))
        sections.append(
            {
                "heading": s.get("heading") or (spec.heading if spec else ""),
                "show_heading": spec.show_heading if spec else True,
                "paragraphs": s.get("paragraphs") or [],
                "bullets": s.get("bullets") or [],
                "pull_quote": s.get("pull_quote"),
            }
        )
    research_sources = {s.get("url"): s for s in payload.get("sources_meta") or []}
    sources = [
        {
            "url": u,
            "title": (research_sources.get(u) or {}).get("title"),
            "publisher": (research_sources.get(u) or {}).get("publisher"),
        }
        for u in art.get("sources_used") or []
    ]
    return {
        "lang": "en-GB" if spelling == "en-GB" else "en",
        "brand": {
            "name": brand.get("name", "The Executive Narrative"),
            "short_name": brand.get("short_name", "TEN"),
            "site_url": site_url,
            "logo_url": brand.get("logo_url", ""),
            "author_name": brand.get("author_name", "Editorial"),
            "powered_by": brand.get("powered_by", "Powered by LayerFlow"),
        },
        "page": {
            "title_tag": seo.get("title_tag") or art.get("title", ""),
            "meta_description": seo.get("meta_description") or art.get("dek", ""),
            "canonical_url": seo.get("canonical_url") or f"{site_url}{pb.route}/{seo.get('slug', '')}",
        },
        "og": {k: v for k, v in (seo.get("og") or {}).items()},
        "twitter": {k: v for k, v in (seo.get("twitter") or {}).items()},
        "json_ld": seo.get("json_ld") or [],
        "article": {
            "title": seo.get("h1") or art.get("title", ""),
            "dek": art.get("dek"),
            "category_label": pb.label,
            "category_url": f"{site_url}{pb.route}",
            "sections": sections,
            "takeaway": art.get("takeaway"),
            "read_minutes": max(1, math.ceil(count_words(art) / 230)),
            "published_iso": local.isoformat() if local else None,
            "published_display": local.strftime("%d %b %Y") if local else None,
        },
        "sources": sources,
        "related": [
            {"url": link.get("url"), "title": link.get("title") or link.get("anchor") or link.get("url")}
            for link in seo.get("internal_links") or []
            if link.get("valid")
        ],
        "tags": [seo.get("primary_keyword")] + list(seo.get("secondary_keywords") or [])[:3] if seo.get("primary_keyword") else [],
    }


def render_article(
    payload: dict[str, Any],
    *,
    brand: dict[str, Any],
    published_at: datetime | None,
    timezone: str = "Asia/Kolkata",
    spelling: str = "en-US",
    template: str = "ten/article.html",
) -> str:
    env = _env(str(get_settings().templates_dir))
    ctx = render_context(payload, brand=brand, published_at=published_at, timezone=timezone, spelling=spelling)
    return env.get_template(template).render(**ctx)


def validate_html(html: str, *, expected_h1: str | None = None) -> list[str]:
    issues = []
    h1s = re.findall(r"<h1\b", html, re.I)
    if len(h1s) != 1:
        issues.append(f"Rendered page has {len(h1s)} <h1> elements; exactly one is required")
    if FORBIDDEN_MARKUP.search(html):
        issues.append("Rendered page contains forbidden markup (script/iframe/inline handler)")
    body = html.split("<body", 1)[-1]
    if PLACEHOLDER.search(body):
        issues.append("Rendered page still contains template placeholders")
    if expected_h1 and str(escape(expected_h1)) not in html and expected_h1 not in html:
        issues.append("H1 text missing from rendered page")
    for tag in ('name="description"', 'rel="canonical"', 'property="og:title"', "application/ld+json"):
        if tag not in html:
            issues.append(f"Missing head tag: {tag}")
    return issues
