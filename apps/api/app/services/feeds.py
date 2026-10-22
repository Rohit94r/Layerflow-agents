"""Source parsers for keyless discovery (plan §10.1). Each returns normalised RawItems; malformed input never
raises past `parse_source` except as FeedParseError with a readable message."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from time import struct_time

import feedparser
from dateutil import parser as dateparser

from app.services.canonical import canonicalize, publisher_from_url, unwrap
from app.services.text import normalize_space, truncate_words

_TAG_RE = re.compile(r"<[^>]+>")


class FeedParseError(Exception):
    pass


@dataclass
class RawItem:
    title: str
    url: str
    summary: str = ""
    published_at: datetime | None = None
    publisher: str | None = None
    lang: str | None = None
    extra: dict | None = None

    @property
    def canonical_url(self) -> str:
        return canonicalize(self.url)


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return normalize_space(html.unescape(_TAG_RE.sub(" ", text)))


def _dt_from_struct(st: struct_time | None) -> datetime | None:
    if not st:
        return None
    try:
        return datetime(*st[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = dateparser.parse(value)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def parse_rss(text: str) -> list[RawItem]:
    parsed = feedparser.parse(text)
    if not parsed.entries:
        if parsed.bozo:
            raise FeedParseError(f"Malformed feed: {str(parsed.get('bozo_exception', 'unknown error'))[:200]}")
        return []
    feed_title = strip_html(parsed.feed.get("title")) if parsed.get("feed") else None
    items = []
    for e in parsed.entries:
        title = strip_html(e.get("title"))
        link = e.get("link") or ""
        if not title or not link.startswith("http"):
            continue
        source = e.get("source") or {}
        publisher = strip_html(source.get("title")) if isinstance(source, dict) and source.get("title") else None
        # Google News titles end with " - Publisher"
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].strip()
        link = unwrap(link)
        summary = strip_html(e.get("summary") or e.get("description") or "")
        if summary.startswith(title):
            summary = summary[len(title) :].strip(" -–—")
        items.append(
            RawItem(
                title=title,
                url=link,
                summary=truncate_words(summary, 600),
                published_at=_dt_from_struct(e.get("published_parsed") or e.get("updated_parsed")),
                publisher=publisher or feed_title or publisher_from_url(link),
                lang=(e.get("language") or parsed.feed.get("language") or None) if parsed.get("feed") else None,
            )
        )
    if not items and parsed.bozo:
        raise FeedParseError(f"Malformed feed: {str(parsed.get('bozo_exception', 'no valid entries'))[:200]}")
    return items


def parse_gdelt(text: str) -> list[RawItem]:
    try:
        data = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as exc:
        # GDELT returns plain-text errors for bad queries
        raise FeedParseError(f"GDELT returned non-JSON: {text[:160]}") from exc
    items = []
    for a in data.get("articles", []) or []:
        url, title = a.get("url"), normalize_space(a.get("title") or "")
        if not url or not title:
            continue
        seen = a.get("seendate")
        published = None
        if seen:
            try:
                published = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            except ValueError:
                published = _dt(seen)
        lang = (a.get("language") or "").lower()
        items.append(
            RawItem(
                title=title,
                url=url,
                published_at=published,
                publisher=a.get("domain") or publisher_from_url(url),
                lang="en" if lang in ("english", "en") else (lang[:8] or None),
                extra={"sourcecountry": a.get("sourcecountry")},
            )
        )
    return items


def parse_hn(text: str) -> list[RawItem]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FeedParseError("HN Algolia returned non-JSON") from exc
    items = []
    for h in data.get("hits", []) or []:
        title = normalize_space(h.get("title") or h.get("story_title") or "")
        url = h.get("url") or (f"https://news.ycombinator.com/item?id={h.get('objectID')}" if h.get("objectID") else None)
        if not title or not url:
            continue
        items.append(
            RawItem(
                title=title,
                url=url,
                summary=truncate_words(strip_html(h.get("story_text") or ""), 400),
                published_at=_dt(h.get("created_at")),
                publisher=publisher_from_url(url) if h.get("url") else "Hacker News",
                extra={"points": h.get("points"), "comments": h.get("num_comments")},
            )
        )
    return items


def parse_reddit(text: str) -> list[RawItem]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FeedParseError("Reddit returned non-JSON") from exc
    items = []
    for child in (data.get("data") or {}).get("children", []) or []:
        d = child.get("data") or {}
        if d.get("stickied") or d.get("over_18"):
            continue
        title = normalize_space(d.get("title") or "")
        permalink = f"https://www.reddit.com{d.get('permalink')}" if d.get("permalink") else None
        url = d.get("url_overridden_by_dest") or d.get("url") or permalink
        if d.get("is_self"):
            url = permalink
        if not title or not url:
            continue
        created = d.get("created_utc")
        items.append(
            RawItem(
                title=title,
                url=url,
                summary=truncate_words(strip_html(d.get("selftext") or ""), 400),
                published_at=datetime.fromtimestamp(created, UTC) if created else None,
                publisher=f"r/{d.get('subreddit')}" if d.get("is_self") else publisher_from_url(url),
                extra={"score": d.get("score"), "subreddit": d.get("subreddit"), "permalink": permalink},
            )
        )
    return items


def parse_source(kind: str, text: str) -> list[RawItem]:
    if kind in ("rss", "ir", "edgar", "manual"):
        stripped = text.lstrip()
        if kind == "ir" and stripped[:15].lower().startswith(("<!doctype html", "<html")):
            return parse_ir_html(text)
        return parse_rss(text)
    if kind == "gdelt":
        return parse_gdelt(text)
    if kind == "hn":
        return parse_hn(text)
    if kind == "reddit":
        return parse_reddit(text)
    raise FeedParseError(f"Unknown source kind '{kind}'")


_PRESS_HINT = re.compile(r"(press|news|release|announce|media|investor|stories)", re.I)


def parse_ir_html(text: str, base_url: str = "") -> list[RawItem]:
    """Fallback for newsroom pages without a feed: links whose path looks like a press release."""
    from urllib.parse import urljoin

    from lxml import html as lxml_html

    try:
        tree = lxml_html.fromstring(text)
    except Exception as exc:
        raise FeedParseError("Newsroom page could not be parsed") from exc
    items = []
    seen = set()
    for a in tree.xpath("//a[@href]"):
        title = normalize_space(a.text_content())
        href = urljoin(base_url, a.get("href"))
        if len(title.split()) < 5 or href in seen or not _PRESS_HINT.search(href):
            continue
        seen.add(href)
        items.append(RawItem(title=title[:300], url=href, publisher=publisher_from_url(href) if href.startswith("http") else None))
        if len(items) >= 30:
            break
    return items
