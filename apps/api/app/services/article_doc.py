"""Helpers for the structured article document stored in article_versions.payload:

    {"article": {title, dek, category, sections[{key, heading, paragraphs[], bullets[], pull_quote, facts_used[]}],
                 takeaway, sources_used[], word_count},
     "seo": {...} | null, "qa": {...} | null, "editor": {change_log, format_report} | null, "stats": {...}}
"""

from __future__ import annotations

import copy
import json
from typing import Any

from app.services import banned as banned_mod
from app.services.playbooks import get_playbook
from app.services.text import readability, sha256, word_count


def section_text(section: dict[str, Any]) -> str:
    parts = list(section.get("paragraphs") or [])
    parts += [f"- {b}" for b in section.get("bullets") or []]
    if section.get("pull_quote"):
        parts.append(section["pull_quote"])
    return "\n\n".join(p for p in parts if p)


def body_text(article: dict[str, Any], *, include_title: bool = False) -> str:
    parts = []
    if include_title:
        parts += [article.get("title") or "", article.get("dek") or ""]
    for s in article.get("sections") or []:
        parts.append(section_text(s))
    if article.get("takeaway"):
        parts.append(article["takeaway"])
    return "\n\n".join(p for p in parts if p)


def prose_text(article: dict[str, Any]) -> str:
    """Body prose only (no bullets/quotes) — for readability scoring."""
    parts = []
    for s in article.get("sections") or []:
        parts += s.get("paragraphs") or []
    return "\n\n".join(parts)


def count_words(article: dict[str, Any]) -> int:
    return word_count(body_text(article))


def compute_stats(article: dict[str, Any], *, banned_phrases: list[str] | None = None) -> dict[str, Any]:
    pb = get_playbook(article.get("category") or "brief")
    wc = count_words(article)
    lo, hi = pb.length_band()
    rd = readability(prose_text(article) or body_text(article))
    hits = banned_mod.scan(body_text(article, include_title=True), banned_phrases)
    present = {s.get("key") for s in article.get("sections") or []}
    return {
        "word_count": wc,
        "target_min": pb.min_words,
        "target_max": pb.max_words,
        "band_min": lo,
        "band_max": hi,
        "in_band": lo <= wc <= hi,
        "readability": rd,
        "banned_hits": hits,
        "sections_present": [k for k in pb.section_keys if k in present],
        "sections_missing": [k for k in pb.section_keys if k not in present],
    }


# Derived/volatile SEO fields: JSON-LD is rebuilt (with dates) at publish time, scores and issues are computed.
_HASH_EXCLUDED_SEO = frozenset({"generated_at", "issues", "score", "json_ld", "fields_complete", "fields_total", "inventory_size", "autosuggest", "overrides"})


def content_hash(payload: dict[str, Any]) -> str:
    """Hash of what readers see (article + editorial SEO fields); stable across re-renders and publish dates."""
    article = payload.get("article") or {}
    seo = {k: v for k, v in (payload.get("seo") or {}).items() if k not in _HASH_EXCLUDED_SEO}
    canonical = json.dumps({"article": article, "seo": seo}, sort_keys=True, ensure_ascii=False, default=str)
    return sha256(canonical)


def to_markdown(article: dict[str, Any]) -> str:
    pb = get_playbook(article.get("category") or "brief")
    lines = [f"# {article.get('title', '')}", ""]
    if article.get("dek"):
        lines += [f"*{article['dek']}*", ""]
    for s in article.get("sections") or []:
        spec = pb.section(s.get("key", ""))
        if spec is None or spec.show_heading:
            lines += [f"## {s.get('heading') or (spec.heading if spec else '')}", ""]
        for p in s.get("paragraphs") or []:
            lines += [p, ""]
        for b in s.get("bullets") or []:
            lines.append(f"- {b}")
        if s.get("bullets"):
            lines.append("")
        if s.get("pull_quote"):
            lines += [f"> {s['pull_quote']}", ""]
    if article.get("takeaway"):
        lines += ["## The takeaway", "", article["takeaway"], ""]
    if article.get("sources_used"):
        lines += ["## Sources", ""] + [f"- {u}" for u in article["sources_used"]] + [""]
    return "\n".join(lines).strip() + "\n"


def clone(payload: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(payload or {})


def normalise_sections(article: dict[str, Any]) -> dict[str, Any]:
    """Order sections by the playbook and fill default headings; unknown keys are kept at the end."""
    pb = get_playbook(article.get("category") or "brief")
    by_key: dict[str, dict[str, Any]] = {}
    extras = []
    for s in article.get("sections") or []:
        key = s.get("key")
        if key in pb.section_keys and key not in by_key:
            by_key[key] = s
        else:
            extras.append(s)
    ordered = []
    for spec in pb.sections:
        if spec.key in by_key:
            s = by_key[spec.key]
            s.setdefault("heading", spec.heading)
            if not s.get("heading"):
                s["heading"] = spec.heading
            s.setdefault("paragraphs", [])
            s.setdefault("bullets", [])
            s.setdefault("facts_used", [])
            ordered.append(s)
    article["sections"] = ordered + extras
    article["word_count"] = count_words(article)
    return article
