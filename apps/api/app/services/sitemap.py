"""Sitemap repair and incremental update (plan §14.3 step 5). Drops localhost/foreign entries — the defect on
the live TEN sitemap — keeps valid entries, and writes ISO lastmod values."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from app.services.htmlmeta import parse_sitemap

BAD_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def valid_for_site(url: str, site_url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    site_host = (urlsplit(site_url).hostname or "").lower()
    if not host or host in BAD_HOSTS or host.endswith(".local"):
        return False
    return host == site_host or host == f"www.{site_host}" or site_host == f"www.{host}"


def merge(
    existing_xml: str | None,
    site_url: str,
    entries: dict[str, datetime | None],
    *,
    remove: set[str] | None = None,
) -> tuple[str, dict[str, int]]:
    """Return (xml, stats). `entries` maps URL -> lastmod; they override existing entries for the same URL."""
    remove = remove or set()
    urls: dict[str, datetime | None] = {}
    dropped = 0
    if existing_xml:
        found, _children = parse_sitemap(existing_xml)
        for u in found:
            if valid_for_site(u, site_url):
                urls[u.rstrip("/") or u] = None
            else:
                dropped += 1
    for u, lastmod in entries.items():
        if valid_for_site(u, site_url):
            urls[u.rstrip("/") or u] = lastmod
    for u in remove:
        urls.pop(u.rstrip("/"), None)
    home = site_url.rstrip("/") + "/"
    urls.setdefault(home.rstrip("/"), None)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in sorted(urls):
        loc = u if urlsplit(u).path else u + "/"
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(loc)}</loc>")
        lm = urls[u]
        if lm:
            lines.append(f"    <lastmod>{lm.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%S+00:00')}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n", {"urls": len(urls), "dropped_invalid": dropped}


def entry(url: str, lastmod: datetime | None) -> str:
    lm = f"\n    <lastmod>{lastmod.astimezone(UTC).isoformat()}</lastmod>" if lastmod else ""
    return f"  <url>\n    <loc>{escape(url)}</loc>{lm}\n  </url>\n"


def now() -> datetime:
    return datetime.now(UTC)
