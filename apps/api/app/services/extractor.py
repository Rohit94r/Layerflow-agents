"""Article extraction (plan §12.2): trafilatura first, readability-lxml fallback, then post-processing
(hidden-text removal, repeated-paragraph dedupe, paywall tail stripping)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from dateutil import parser as dateparser

from app.services.sanitize import clean_text, injection_flags, strip_hidden_html
from app.services.text import looks_english, normalize_space, word_count

log = logging.getLogger(__name__)

PAYWALL_MARKERS = (
    "subscribe to continue",
    "subscribe to read",
    "to continue reading",
    "already a subscriber",
    "this article is for subscribers",
    "sign in to continue",
    "become a member to read",
    "premium content",
    "unlock this article",
)


@dataclass
class Extracted:
    url: str
    title: str | None = None
    byline: str | None = None
    published_at: datetime | None = None
    text: str = ""
    lang: str | None = None
    canonical: str | None = None
    og_image: str | None = None
    sitename: str | None = None
    word_count: int = 0
    paywalled: bool = False
    english: bool = True
    injection_flags: list[str] = field(default_factory=list)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = dateparser.parse(value)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt and dt.tzinfo is None:
        from datetime import UTC

        dt = dt.replace(tzinfo=UTC)
    return dt


def _dedupe_paragraphs(text: str) -> str:
    seen: set[str] = set()
    out = []
    for para in text.split("\n"):
        key = normalize_space(para).lower()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(normalize_space(para))
    return "\n\n".join(out)


def _trafilatura(html: str, url: str) -> dict | None:
    try:
        import trafilatura
    except ImportError:  # pragma: no cover
        return None
    try:
        doc = trafilatura.bare_extraction(
            html,
            url=url,
            with_metadata=True,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
    except Exception as exc:  # trafilatura raises a variety of parser errors on odd markup
        log.debug("trafilatura failed for %s: %s", url, exc)
        return None
    if doc is None:
        return None
    if isinstance(doc, dict):
        return doc
    if hasattr(doc, "as_dict"):
        return doc.as_dict()
    return {k: getattr(doc, k, None) for k in ("title", "author", "date", "text", "language", "url", "image", "sitename")}


def _readability(html: str) -> tuple[str | None, str]:
    try:
        from lxml import html as lxml_html
        from readability import Document
    except ImportError:  # pragma: no cover
        return None, ""
    try:
        doc = Document(html)
        summary = doc.summary(html_partial=True)
        tree = lxml_html.fromstring(summary)
        paras = [normalize_space(el.text_content()) for el in tree.iter("p", "li", "h2", "h3")]
        return doc.short_title(), "\n".join(p for p in paras if p)
    except Exception as exc:
        log.debug("readability failed: %s", exc)
        return None, ""


def extract(html: str, url: str) -> Extracted:
    raw_lower = (html or "").lower()
    flags = injection_flags(html or "")
    cleaned_html = strip_hidden_html(html or "")
    data = _trafilatura(cleaned_html, url) or {}
    text = data.get("text") or ""
    title = data.get("title")
    if word_count(text) < 80:
        r_title, r_text = _readability(cleaned_html)
        if word_count(r_text) > word_count(text):
            text, title = r_text, title or r_title
    text = _dedupe_paragraphs(clean_text(text))
    wc = word_count(text)
    paywalled = wc < 150 and any(m in raw_lower for m in PAYWALL_MARKERS)
    return Extracted(
        url=url,
        title=normalize_space(title) if title else None,
        byline=data.get("author"),
        published_at=_parse_date(data.get("date")),
        text=text,
        lang=data.get("language"),
        canonical=data.get("url"),
        og_image=data.get("image"),
        sitename=data.get("sitename"),
        word_count=wc,
        paywalled=paywalled,
        english=looks_english(text) if text else True,
        injection_flags=sorted(set(flags + injection_flags(text))),
    )
