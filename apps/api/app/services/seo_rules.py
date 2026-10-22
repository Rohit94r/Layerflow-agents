"""SEO rules enforced in code (plan §13.3) + JSON-LD / Open Graph builders. The model only proposes phrasing."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

from app.services.playbooks import get_playbook
from app.services.slug import validate_slug
from app.services.text import STOPWORDS, ascii_fold, truncate_words, words

TITLE_MIN, TITLE_MAX = 30, 60
META_MIN, META_MAX = 140, 158
H1_MAX = 70
CLICKBAIT = re.compile(
    r"\b(you won'?t believe|shocking|mind-?blowing|this one trick|what happens next|insane|jaw-?dropping|must see|epic)\b|!{2,}",
    re.I,
)
WEAK_META = re.compile(r"\b(learn more|click here|read more|find out more|in this article)\b", re.I)
REQUIRED_FIELDS = (
    "title_tag",
    "meta_description",
    "slug",
    "canonical_url",
    "primary_keyword",
    "og_title",
    "og_description",
    "json_ld",
)


def validate_title_tag(title: str, *, h1: str | None = None, brand: str = "TEN", taken: set[str] | None = None) -> list[str]:
    issues = []
    n = len(title or "")
    if n < TITLE_MIN or n > TITLE_MAX:
        issues.append(f"Title tag is {n} chars; use {TITLE_MIN}–{TITLE_MAX}")
    if CLICKBAIT.search(title or ""):
        issues.append("Title tag reads as clickbait")
    if re.search(rf"\|\s*{re.escape(brand)}\s*$", title or "", re.I) or re.search(r"\|\s*the executive narrative\s*$", title or "", re.I):
        issues.append("Do not append the brand suffix; the template adds it")
    if h1 and title and title.strip().lower() == h1.strip().lower():
        issues.append("Title tag must differ from the H1")
    if taken and title.strip().lower() in taken:
        issues.append("Title tag duplicates an existing page title")
    return issues


def validate_meta(desc: str) -> list[str]:
    issues = []
    n = len(desc or "")
    if n < META_MIN or n > META_MAX:
        issues.append(f"Meta description is {n} chars; use {META_MIN}–{META_MAX}")
    if WEAK_META.search(desc or ""):
        issues.append("Meta description uses filler like 'learn more'")
    if desc and not re.search(r"\d|[A-Z][a-z]+ [A-Z][a-z]+", desc):
        issues.append("Meta description lacks a specific detail (number or named entity)")
    return issues


def validate_h1(h1: str) -> list[str]:
    return [f"H1 is {len(h1)} chars; keep it under {H1_MAX}"] if len(h1 or "") > H1_MAX else []


def keyword_stuffed(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    return (text or "").lower().count(keyword.lower()) > 2


def fit_meta(text: str) -> str:
    """Deterministic fallback: trim/extend a sentence into the 140–158 window at a word boundary."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) > META_MAX:
        t = truncate_words(t, META_MAX - 1).rstrip(",;:") + "."
    return t


def fit_title(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip().rstrip(".")
    if len(t) > TITLE_MAX:
        t = truncate_words(t, TITLE_MAX)
        t = re.sub(r"\s+(and|or|of|the|to|for|in|on|with|a|an)$", "", t, flags=re.I)
    return t


def extract_keywords(title: str, body: str, *, top: int = 6) -> list[str]:
    """Rank unigram/bigram/trigram candidates by frequency, boosted when they appear in the title."""
    def toks(t: str) -> list[str]:
        return [w.lower() for w in words(ascii_fold(t))]

    title_t, body_t = toks(title), toks(body)
    counts: Counter[str] = Counter()
    for seq, weight in ((title_t, 3.0), (body_t, 1.0)):
        for n in (1, 2, 3):
            for i in range(len(seq) - n + 1):
                gram = seq[i : i + n]
                if gram[0] in STOPWORDS or gram[-1] in STOPWORDS or any(g.isdigit() for g in gram):
                    continue
                if n == 1 and (len(gram[0]) < 4):
                    continue
                counts[" ".join(gram)] += weight * (1.0 + 0.6 * (n - 1))
    ranked = [k for k, _ in counts.most_common(60)]
    picked: list[str] = []
    for k in ranked:
        if any(k in p or p in k for p in picked):
            continue
        picked.append(k)
        if len(picked) >= top:
            break
    return picked


def search_intent(category: str, title: str) -> str:
    t = title.lower()
    if re.search(r"\b(vs\.?|versus|should|which|or)\b", t) or category == "decisions":
        return "decision"
    if re.search(r"\b(price|pricing|buy|best|review|cost)\b", t):
        return "commercial"
    return get_playbook(category).search_intent or "informational"


def canonical_for(site_url: str, category: str, slug: str) -> str:
    return f"{site_url.rstrip('/')}{get_playbook(category).route}/{slug}"


def build_json_ld(
    *,
    headline: str,
    description: str,
    url: str,
    category: str,
    site_url: str,
    brand_name: str,
    logo_url: str,
    image_url: str | None,
    author_name: str,
    published_at: datetime | None,
    modified_at: datetime | None,
    keywords: list[str],
) -> list[dict[str, Any]]:
    pb = get_playbook(category)
    published = (published_at.isoformat() if published_at else None)
    article = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline[:110],
        "description": description,
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "url": url,
        "articleSection": pb.label,
        "keywords": ", ".join(keywords),
        "author": {"@type": "Person" if author_name and "editorial" not in author_name.lower() else "Organization", "name": author_name},
        "publisher": {"@type": "Organization", "name": brand_name, "logo": {"@type": "ImageObject", "url": logo_url}},
        "isAccessibleForFree": True,
    }
    if published:
        article["datePublished"] = published
        article["dateModified"] = (modified_at or published_at).isoformat()  # type: ignore[union-attr]
    if image_url:
        article["image"] = [image_url]
    breadcrumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": brand_name, "item": site_url.rstrip("/") + "/"},
            {"@type": "ListItem", "position": 2, "name": pb.label, "item": site_url.rstrip("/") + pb.route},
            {"@type": "ListItem", "position": 3, "name": headline[:110], "item": url},
        ],
    }
    return [article, breadcrumbs]


def validate_json_ld(blocks: Any) -> list[str]:
    issues = []
    items = blocks if isinstance(blocks, list) else [blocks]
    article = next((b for b in items if isinstance(b, dict) and b.get("@type") in ("Article", "NewsArticle")), None)
    if article is None:
        return ["JSON-LD has no Article block"]
    for key in ("@context", "headline", "description", "author", "publisher", "mainEntityOfPage"):
        if not article.get(key):
            issues.append(f"JSON-LD Article missing '{key}'")
    if len(article.get("headline", "")) > 110:
        issues.append("JSON-LD headline exceeds 110 chars")
    pub = article.get("publisher") or {}
    if not (pub.get("logo") or {}).get("url"):
        issues.append("JSON-LD publisher logo missing")
    return issues


def completeness(seo: dict[str, Any]) -> tuple[int, list[str]]:
    missing = []
    for f in REQUIRED_FIELDS:
        if f in ("og_title", "og_description"):
            val = (seo.get("og") or {}).get(f.split("_", 1)[1])
        else:
            val = seo.get(f)
        if not val:
            missing.append(f)
    return len(REQUIRED_FIELDS) - len(missing), missing


def full_issues(seo: dict[str, Any], *, taken_titles: set[str] | None = None) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    def add(field: str, msgs: list[str], severity: str = "major") -> None:
        issues.extend({"field": field, "severity": severity, "message": m} for m in msgs)

    add("title_tag", validate_title_tag(seo.get("title_tag", ""), h1=seo.get("h1"), taken=taken_titles))
    add("meta_description", validate_meta(seo.get("meta_description", "")))
    add("slug", validate_slug(seo.get("slug", "")))
    add("h1", validate_h1(seo.get("h1", "")), "minor")
    add("json_ld", validate_json_ld(seo.get("json_ld") or []))
    if keyword_stuffed(seo.get("title_tag", "") + " " + seo.get("meta_description", ""), seo.get("primary_keyword", "")):
        add("primary_keyword", ["Primary keyword repeated more than twice in title + meta"])
    bad_links = [l for l in seo.get("internal_links") or [] if not l.get("valid")]
    if bad_links:
        add("internal_links", [f"{len(bad_links)} internal link(s) not verified in the site inventory"])
    if not seo.get("internal_links"):
        add("internal_links", ["No internal links (crawl the site inventory in SEO → Site audit)"], "minor")
    _, missing = completeness(seo)
    if missing:
        add("completeness", [f"Missing: {', '.join(missing)}"], "critical")
    return issues


def seo_score(seo: dict[str, Any], issues: list[dict[str, str]]) -> int:
    penalty = {"critical": 25, "major": 10, "minor": 4}
    total = 100 - sum(penalty.get(i["severity"], 5) for i in issues)
    return max(0, min(100, total))
