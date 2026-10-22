"""Keyless related-coverage search used by the research agent: GDELT DOC API (publisher URLs) and Bing News
RSS (redirects unwrapped). Google News links are JS redirects, so they are used for discovery only."""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from app.services.entities import extract_entities
from app.services.feeds import FeedParseError, RawItem, parse_gdelt, parse_rss
from app.services.fetcher import FetchError, Fetcher
from app.services.text import content_tokens

log = logging.getLogger(__name__)


def build_query(title: str, *, max_terms: int = 6) -> str:
    ents = [e["name"] for e in extract_entities(title) if e["type"] in ("company", "person")][:2]
    toks = [t for t in content_tokens(title) if t.lower() not in {e.lower() for e in ents}]
    terms = [f'"{e}"' if " " in e else e for e in ents] + toks[: max_terms - len(ents)]
    return " ".join(terms) or title


async def gdelt_search(fetcher: Fetcher, query: str, *, max_records: int = 20, timespan: str = "7d") -> list[RawItem]:
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?query="
        + quote_plus(f"{query} sourcelang:english")
        + f"&mode=artlist&format=json&maxrecords={max_records}&timespan={timespan}&sort=hybridrel"
    )
    try:
        res = await fetcher.get(url, respect_robots=False, use_cache=True)
        return parse_gdelt(res.text)
    except (FetchError, FeedParseError) as exc:
        log.info("gdelt search failed: %s", exc)
        return []


async def bing_news_search(fetcher: Fetcher, query: str) -> list[RawItem]:
    url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss"
    try:
        res = await fetcher.get(url, respect_robots=False, use_cache=True)
        return parse_rss(res.text)
    except (FetchError, FeedParseError) as exc:
        log.info("bing news search failed: %s", exc)
        return []


async def autosuggest(fetcher: Fetcher, query: str) -> list[str]:
    """Keyless search autosuggest (tier B: may be throttled; failures return [])."""
    import json

    url = f"https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q={quote_plus(query)}"
    try:
        res = await fetcher.get(url, respect_robots=False, use_cache=True, accept=("application/json", "text/javascript", "application/x-javascript", "text/plain"))
        data = json.loads(res.text)
        return [s for s in data[1] if isinstance(s, str)][:8] if isinstance(data, list) and len(data) > 1 else []
    except (FetchError, ValueError, IndexError, TypeError) as exc:
        log.info("autosuggest failed: %s", exc)
        return []


async def related_coverage(fetcher: Fetcher, title: str, *, limit: int = 12) -> list[RawItem]:
    query = build_query(title)
    items: list[RawItem] = []
    for fn in (gdelt_search, bing_news_search):
        items.extend(await fn(fetcher, query))
        if len(items) >= limit * 2:
            break
    out, seen = [], set()
    for it in items:
        key = it.canonical_url
        if key in seen or "news.google.com" in key:
            continue
        seen.add(key)
        out.append(it)
    return out[:limit]
