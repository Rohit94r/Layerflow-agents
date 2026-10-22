"""Site audit (plan §3, §13.5): the twelve findings computed from the crawled inventory, plus a deterministic
fix list (title, description, canonical, slug) for every existing page. Before the first crawl, the findings
recorded on 20 Oct 2026 are shown and clearly labelled as a recorded baseline, not live data."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from typing import Any
from urllib.parse import unquote, urlsplit

from app.services.playbooks import PLAYBOOKS, category_from_route
from app.services.seo_rules import META_MAX, META_MIN, fit_meta, fit_title
from app.services.slug import is_malformed_live_slug, slugify
from app.services.text import truncate_words

BASELINE = [
    ("sitemap_broken", "Sitemap is broken", "critical", "/sitemap.xml lists only http://localhost/ and http://localhost/about", "Search engines get no valid URL list"),
    ("duplicate_titles", "Every article shares one title", "critical", "All article pages: <title>TEN - The Executive Narrative</title>", "Duplicate titles across ~168 posts; poor CTR and indexing"),
    ("missing_meta", "No meta description", "major", 'name="description" absent on article pages', "Snippets are auto-generated or empty"),
    ("missing_canonical", "No canonical tags", "major", 'rel="canonical" absent', "Duplicate/parameter URL risk"),
    ("missing_og", "No Open Graph / Twitter cards", "major", "0 og:* tags found", "Poor LinkedIn/WhatsApp previews"),
    ("missing_jsonld", "No structured data", "major", "No application/ld+json", "No Article/Organization rich results"),
    ("missing_h1", "No <h1> on articles", "major", "Headline is rendered as <h3>", "Weak semantic hierarchy"),
    ("placeholder_content", "Template demo content leaking", "major", "Sidebar shows 'Breaking Down the Elements of a Masterpiece Painting'", "Brand credibility issue"),
    ("category_routes", "Category URLs known", "info", "/brief, /thinking, /room, /playbook, /descisions, /deep_dive, /discover", "Adapters and route mapping are unambiguous"),
    ("misspelled_route", "Misspelled route /descisions", "info", "/descisions (should be 'decisions')", "Keep for SEO compatibility; correct label in UI"),
    ("static_stack", "Static-template stack", "info", "jQuery vendor bundle, assets/imgs/template/*, no CMS signatures", "Publish via file/git/SFTP adapter"),
    ("malformed_slugs", "Malformed slugs", "minor", "Title concatenated into slug, e.g. /descisions/Open-AI-Models-Are-Changing-…", "Slug generator enforces length + word boundary"),
]


def _finding(fid: str, title: str, severity: str, evidence: str, impact: str, *, affected: list[str] | None = None, fix: str = "", source: str = "live") -> dict[str, Any]:
    return {
        "id": fid,
        "title": title,
        "severity": severity,
        "evidence": evidence,
        "impact": impact,
        "affected_count": len(affected or []),
        "affected_urls": (affected or [])[:12],
        "fix": fix,
        "source": source,
    }


def baseline_findings() -> list[dict[str, Any]]:
    return [_finding(*row, source="baseline") for row in BASELINE]


def audit(pages: list[Any], inventory_state: dict[str, Any] | None) -> dict[str, Any]:
    if not pages:
        return {
            "findings": baseline_findings(),
            "summary": {"pages": 0, "article_pages": 0, "with_issues": None},
            "crawled_at": None,
            "source": "baseline",
            "note": "Recorded observation from 20 Oct 2026. Run the audit to verify against the live site.",
        }
    ok = [p for p in pages if p.status_code == 200]
    articles = [p for p in ok if category_from_route(urlsplit(p.url).path) and urlsplit(p.url).path.strip("/").count("/") >= 1]
    findings: list[dict[str, Any]] = []
    sm = (inventory_state or {}).get("sitemap", {})
    if sm.get("invalid") or (sm.get("valid", 0) < max(5, len(articles) // 2)):
        findings.append(_finding(
            "sitemap_broken", "Sitemap is broken or incomplete", "critical",
            f"{sm.get('urls', 0)} URL(s) in sitemap, {sm.get('invalid', 0)} invalid (e.g. {', '.join(sm.get('invalid_sample', [])[:2]) or 'none'}); {len(articles)} article pages found by crawling",
            "Search engines get no valid URL list", affected=sm.get("invalid_sample", []),
            fix="First publish through ten_static regenerates sitemap.xml from the live inventory; or download the corrected sitemap below.",
        ))
    by_title: dict[str, list[str]] = defaultdict(list)
    for p in articles:
        by_title[(p.title or "").strip()].append(p.url)
    dup = [u for t, urls in by_title.items() if len(urls) > 1 for u in urls]
    if dup:
        top = max(by_title.items(), key=lambda kv: len(kv[1]))
        findings.append(_finding("duplicate_titles", "Article pages share duplicate titles", "critical",
                                 f"{len(dup)} pages share titles; most common: “{top[0]}” ×{len(top[1])}",
                                 "Poor CTR and indexing", affected=dup, fix="Use the proposed titles in the fix list."))
    checks = [
        ("missing_meta", "Missing meta description", "major", lambda p: not p.meta_description, "Snippets are auto-generated or empty", "Use the proposed descriptions."),
        ("missing_canonical", "Missing canonical tag", "major", lambda p: not p.canonical, "Duplicate/parameter URL risk", "Add <link rel=canonical> with the clean URL."),
        ("missing_og", "Missing Open Graph tags", "major", lambda p: not p.og, "Poor LinkedIn/WhatsApp previews", "Add og:title, og:description, og:image, og:url."),
        ("missing_jsonld", "No structured data", "major", lambda p: not p.has_jsonld, "No Article rich results", "Add Article + BreadcrumbList JSON-LD."),
        ("missing_h1", "No <h1> on the page", "major", lambda p: not p.h1, "Weak semantic hierarchy", "Render the headline as <h1>."),
    ]
    for fid, title, sev, pred, impact, fix in checks:
        hit = [p.url for p in articles if pred(p)]
        if hit:
            findings.append(_finding(fid, title, sev, f"{len(hit)} of {len(articles)} article pages", impact, affected=hit, fix=fix))
    placeholders = [p.url for p in ok if (p.signals or {}).get("placeholders")]
    if placeholders:
        sample = next((p.signals["placeholders"][0] for p in ok if (p.signals or {}).get("placeholders")), "")
        findings.append(_finding("placeholder_content", "Template demo content leaking", "major", f"{len(placeholders)} page(s) contain “{sample}”",
                                 "Brand credibility issue on an executive site", affected=placeholders, fix="Remove template demo widgets from the sidebar."))
    routes = sorted({"/" + urlsplit(p.url).path.strip("/").split("/")[0] for p in ok if urlsplit(p.url).path.strip("/")})
    findings.append(_finding("category_routes", "Category URLs discovered", "info", ", ".join(r for r in routes if category_from_route(r) or r in ("/discover",)) or "none", "Route mapping for adapters"))
    if any("/descisions" in p.url for p in ok):
        findings.append(_finding("misspelled_route", "Misspelled route /descisions", "info", "/descisions is live", "Keep for SEO compatibility; correct label in UI"))
    stack = (inventory_state or {}).get("stack", [])
    if stack:
        findings.append(_finding("static_stack", "Site stack signals", "info", ", ".join(stack), "Determines the publishing adapter"))
    bad_slugs = [p.url for p in articles if is_malformed_live_slug(unquote(urlsplit(p.url).path))]
    if bad_slugs:
        findings.append(_finding("malformed_slugs", "Malformed slugs", "minor", f"{len(bad_slugs)} slug(s) with uppercase, encoded characters or >8 words",
                                 "Long, case-sensitive URLs", affected=bad_slugs, fix="New articles use the slug validator; keep old URLs, add canonicals."))
    with_issues = len({u for f in findings if f["severity"] != "info" for u in f["affected_urls"]})
    return {
        "findings": findings,
        "summary": {"pages": len(pages), "article_pages": len(articles), "with_issues": with_issues},
        "crawled_at": (inventory_state or {}).get("crawled_at"),
        "source": "live",
    }


def fix_list(pages: list[Any], site_url: str, brand_short: str = "TEN") -> list[dict[str, Any]]:
    out = []
    titles_used: set[str] = set()
    for p in pages:
        if p.status_code != 200:
            continue
        path = urlsplit(p.url).path
        cat = category_from_route(path)
        if not cat or path.strip("/").count("/") < 1:
            continue
        headline = (p.headline or p.h1 or "").strip()
        if not headline:
            seg = unquote(path.rstrip("/").split("/")[-1]).replace("-", " ")
            headline = seg.strip().title()
        proposed_title = fit_title(headline)
        if proposed_title.lower() in titles_used:
            proposed_title = fit_title(f"{headline} — {PLAYBOOKS[cat].label}")
        titles_used.add(proposed_title.lower())
        desc_src = p.meta_description or p.first_paragraph or headline
        proposed_desc = fit_meta(desc_src)
        if len(proposed_desc) < META_MIN and p.first_paragraph and p.first_paragraph not in desc_src:
            proposed_desc = fit_meta(f"{desc_src} {p.first_paragraph}")
        issues = []
        if not p.title or brand_short.lower() in (p.title or "").lower() and "executive narrative" in (p.title or "").lower():
            issues.append("generic title")
        if not p.meta_description:
            issues.append("no meta description")
        if not p.canonical:
            issues.append("no canonical")
        if not p.og:
            issues.append("no OG tags")
        if not p.has_jsonld:
            issues.append("no JSON-LD")
        if not p.h1:
            issues.append("no H1")
        clean_url = f"{site_url.rstrip('/')}{path}"
        out.append(
            {
                "url": p.url,
                "category": cat,
                "current_title": p.title,
                "proposed_title": proposed_title,
                "current_description": p.meta_description,
                "proposed_description": proposed_desc if len(proposed_desc) <= META_MAX else truncate_words(proposed_desc, META_MAX),
                "proposed_canonical": clean_url,
                "proposed_slug": slugify(headline) if is_malformed_live_slug(unquote(path)) else None,
                "issues": issues,
            }
        )
    return out


def fix_list_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    fields = ["url", "category", "current_title", "proposed_title", "current_description", "proposed_description", "proposed_canonical", "proposed_slug", "issues"]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow({**{k: r.get(k) for k in fields}, "issues": "; ".join(r.get("issues") or [])})
    return buf.getvalue()
