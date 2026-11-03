"""Fetcher guards (SSRF, robots, size, redirects) and feed parsers (malformed input never crashes)."""

from __future__ import annotations

import json

import pytest

from app.services.extractor import extract
from app.services.feeds import FeedParseError, parse_gdelt, parse_hn, parse_reddit, parse_rss, parse_source
from app.services.fetcher import FetchError, _is_public_ip
from app.services.images import ImageCandidate, candidates_from_html, pick_image
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


def test_nat64_decisions_follow_the_embedded_ipv4():
    # 64:ff9b::/96 is the well-known NAT64 prefix used by IPv6-only networks.
    assert _is_public_ip("64:ff9b::9765:d136")  # 151.101.209.54
    assert not _is_public_ip("64:ff9b::a00:1")  # 10.0.0.1
    assert not _is_public_ip("64:ff9b::7f00:1")  # 127.0.0.1


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
    assert items[0].image_url == "https://cdn.example.com/northwind-hero.jpg"
    assert items[0].image_width == 1200 and items[0].image_height == 675
    assert items[1].image_url is None
    assert parse_gdelt(json.dumps({"articles": [{"url": "https://a.example/x", "title": "T", "seendate": "20261022T080000Z", "domain": "a.example", "language": "English"}]}))[0].lang == "en"
    assert parse_hn(json.dumps({"hits": [{"title": "Show HN", "url": "https://h.example", "created_at": "2026-10-22T08:00:00Z", "objectID": "1"}]}))[0].title == "Show HN"
    assert parse_reddit(json.dumps({"data": {"children": [{"data": {"title": "Q", "permalink": "/r/business/1", "is_self": True, "created_utc": 1761120000, "subreddit": "business"}}]}}))[0].url.startswith("https://www.reddit.com")


def test_image_policy_accepts_landscape_photography_only():
    best = pick_image(
        [
            ImageCandidate("https://cdn.example.com/site-logo.png", 1200, 675),
            ImageCandidate("https://cdn.example.com/hero.svg", 1200, 675),
            ImageCandidate("https://cdn.example.com/thumb.jpg", 200, 120),
            ImageCandidate("https://cdn.example.com/pixel.gif", 1, 1),
            ImageCandidate("https://cdn.example.com/hero.jpg", 1600, 900),
            ImageCandidate("https://other.example.com/hero.webp", 1200, 675),
        ]
    )
    assert best is not None
    assert best.url == "https://cdn.example.com/hero.jpg"


def test_html_image_collection_prefers_og_and_jsonld():
    page = """<html><head>
      <meta property="og:image" content="/media/logo.png">
      <meta property="og:image:secure_url" content="https://cdn.example.com/lead.jpg">
      <meta property="og:image:width" content="1200"><meta property="og:image:height" content="675">
      <script type="application/ld+json">{"@type":"NewsArticle","image":{"url":"https://cdn.example.com/jsonld.jpg"}}</script>
    </head><body><article><img src="/media/inline.jpg" width="900" height="500"></article></body></html>"""
    best = pick_image(candidates_from_html(page, "https://news.example.com/a"))
    assert best is not None
    assert best.url == "https://cdn.example.com/lead.jpg"
    assert pick_image([ImageCandidate("data:image/png;base64,xxxx")]) is None


@pytest.mark.parametrize("bad", ["", "<rss><channel><item><title>oops", "not xml at all {", "<html><body>hi</body></html>"])
def test_malformed_feeds_do_not_crash(bad):
    try:
        out = parse_source("rss", bad)
        assert isinstance(out, list)
    except FeedParseError:
        pass
    with pytest.raises(FeedParseError):
        parse_gdelt("Invalid query: bad syntax")
