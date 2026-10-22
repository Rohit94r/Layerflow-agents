"""Fetcher guards (SSRF, robots, size, redirects) and feed parsers (malformed input never crashes)."""

from __future__ import annotations

import json

import pytest

from app.services.extractor import extract
from app.services.feeds import FeedParseError, parse_gdelt, parse_hn, parse_reddit, parse_rss, parse_source
from app.services.fetcher import FetchError
from tests.conftest import ARTICLE_1, RSS, make_fetcher


@pytest.mark.parametrize(
    "url",
    ["http://localhost/admin", "http://127.0.0.1:8000/", "http://10.1.2.3/", "http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "http://internal.example.com/", "http://[::1]/"],
)
async def test_ssrf_blocked(url):
    f = make_fetcher()
    try:
        with pytest.raises(FetchError) as exc:
            await f.get(url, respect_robots=False, use_cache=False)
        assert exc.value.kind in ("ssrf", "network")
    finally:
        await f.close()


async def test_redirect_to_private_ip_blocked():
    f = make_fetcher()
    try:
        with pytest.raises(FetchError) as exc:
            await f.get("https://redirect.example.com/x", respect_robots=False, use_cache=False)
        assert exc.value.kind == "ssrf"
    finally:
        await f.close()


async def test_robots_and_size_cap_and_cache():
    f = make_fetcher()
    try:
        with pytest.raises(FetchError) as exc:
            await f.get("https://news.example.com/private/page")
        assert exc.value.kind == "robots"
        with pytest.raises(FetchError) as exc:
            await f.get("https://big.example.com/huge", respect_robots=False, use_cache=False)
        assert exc.value.kind == "too_large"
        r1 = await f.get("https://news.example.com/northwind-warehouses")
        r2 = await f.get("https://news.example.com/northwind-warehouses")
        assert r1.status == 200 and r2.from_cache
    finally:
        await f.close()


def test_extractor_strips_hidden_injection():
    ex = extract(ARTICLE_1, "https://news.example.com/northwind-warehouses")
    assert ex.word_count > 150
    assert "triple" not in ex.text.lower()
    assert ex.injection_flags  # recorded, not obeyed


def test_paywall_detected():
    ex = extract("<html><body><p>Subscribe to continue reading.</p></body></html>", "https://paywall.example.com/a")
    assert ex.paywalled


def test_parsers():
    items = parse_rss(RSS.replace("{now}", "Wed, 21 Oct 2026 10:00:00 GMT"))
    assert len(items) == 4 and items[0].published_at is not None
    assert "utm_source" not in items[0].canonical_url
    assert parse_gdelt(json.dumps({"articles": [{"url": "https://a.example/x", "title": "T", "seendate": "20261022T080000Z", "domain": "a.example", "language": "English"}]}))[0].lang == "en"
    assert parse_hn(json.dumps({"hits": [{"title": "Show HN", "url": "https://h.example", "created_at": "2026-10-22T08:00:00Z", "objectID": "1"}]}))[0].title == "Show HN"
    assert parse_reddit(json.dumps({"data": {"children": [{"data": {"title": "Q", "permalink": "/r/business/1", "is_self": True, "created_utc": 1761120000, "subreddit": "business"}}]}}))[0].url.startswith("https://www.reddit.com")


@pytest.mark.parametrize("bad", ["", "<rss><channel><item><title>oops", "not xml at all {", "<html><body>hi</body></html>"])
def test_malformed_feeds_do_not_crash(bad):
    try:
        out = parse_source("rss", bad)
        assert isinstance(out, list)
    except FeedParseError:
        pass
    with pytest.raises(FeedParseError):
        parse_gdelt("Invalid query: bad syntax")
