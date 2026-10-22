"""On-page SEO parsing for the site inventory and competitor crawls (plan §13.1)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from lxml import etree
from lxml import html as lxml_html

from app.services.text import normalize_space, word_count

PLACEHOLDER_MARKERS = (
    "lorem ipsum",
    "masterpiece painting",
    "classical art in a digital age",
    "breaking down the elements of a masterpiece",
    "dolor sit amet",
    "your title here",
    "sample post",
)


@dataclass
class PageMeta:
    url: str
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    og: dict[str, str] = field(default_factory=dict)
    twitter: dict[str, str] = field(default_factory=dict)
    has_jsonld: bool = False
    jsonld_types: list[str] = field(default_factory=list)
    h1: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    headline: str | None = None
    first_paragraph: str | None = None
    word_count: int = 0
    internal_links: list[str] = field(default_factory=list)
    placeholder_hits: list[str] = field(default_factory=list)
    stack_signals: list[str] = field(default_factory=list)


def parse_page(html: str, url: str) -> PageMeta:
    meta = PageMeta(url=url)
    try:
        tree = lxml_html.fromstring(html or "<html></html>")
    except (etree.ParserError, ValueError):
        return meta

    def first(xpath: str) -> str | None:
        vals = tree.xpath(xpath)
        if not vals:
            return None
        v = vals[0]
        v = v if isinstance(v, str) else v.text_content()
        v = normalize_space(v)
        return v or None

    meta.title = first("//title")
    meta.meta_description = first("//meta[translate(@name,'DESCRIPTION','description')='description']/@content")
    meta.canonical = first("//link[translate(@rel,'CANONICAL','canonical')='canonical']/@href")
    for el in tree.xpath("//meta[starts-with(@property,'og:')]"):
        meta.og[el.get("property")] = el.get("content") or ""
    for el in tree.xpath("//meta[starts-with(@name,'twitter:')]"):
        meta.twitter[el.get("name")] = el.get("content") or ""
    for script in tree.xpath("//script[@type='application/ld+json']"):
        meta.has_jsonld = True
        try:
            data = json.loads(script.text_content() or "{}")
            items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
            for it in items:
                if isinstance(it, dict) and it.get("@type"):
                    t = it["@type"]
                    meta.jsonld_types.extend(t if isinstance(t, list) else [t])
        except (ValueError, AttributeError):
            pass
    meta.h1 = [normalize_space(e.text_content()) for e in tree.xpath("//h1") if normalize_space(e.text_content())]
    meta.headings = [
        f"{e.tag}: {normalize_space(e.text_content())}" for e in tree.xpath("//h1|//h2|//h3") if normalize_space(e.text_content())
    ][:40]
    # The live TEN site renders article headlines as <h3>; take the most prominent heading as the headline.
    meta.headline = meta.h1[0] if meta.h1 else first("//article//h1|//article//h2|//article//h3|//main//h3|//h2|//h3")

    for bad in tree.xpath("//script|//style|//noscript|//nav|//footer|//header"):
        bad.drop_tree()
    paras = [normalize_space(p.text_content()) for p in tree.xpath("//p")]
    paras = [p for p in paras if word_count(p) >= 12]
    meta.first_paragraph = paras[0] if paras else None
    body_text = " ".join(paras)
    meta.word_count = word_count(body_text)

    lower = (html or "").lower()
    meta.placeholder_hits = [m for m in PLACEHOLDER_MARKERS if m in lower]
    if "jquery" in lower:
        meta.stack_signals.append("jquery")
    if "assets/imgs/template" in lower:
        meta.stack_signals.append("template-assets")
    if "wp-content" in lower or "wp-json" in lower:
        meta.stack_signals.append("wordpress")
    if "__next" in lower:
        meta.stack_signals.append("nextjs")

    host = urlsplit(url).hostname
    links = set()
    for href in tree.xpath("//a/@href"):
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(url, href).split("#")[0]
        if urlsplit(absolute).hostname == host:
            links.add(absolute)
    meta.internal_links = sorted(links)
    return meta


def parse_sitemap(xml: str) -> tuple[list[str], list[str]]:
    """Return (page_urls, child_sitemaps). Tolerates namespaces and malformed whitespace."""
    urls: list[str] = []
    children: list[str] = []
    try:
        root = etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml, parser=etree.XMLParser(recover=True))
    except (etree.XMLSyntaxError, ValueError):
        found = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml or "")
        return found, []
    if root is None:
        return [], []
    tag = etree.QName(root).localname if isinstance(root.tag, str) else ""
    locs = [normalize_space(e.text or "") for e in root.iter() if isinstance(e.tag, str) and etree.QName(e).localname == "loc"]
    if tag == "sitemapindex":
        children = [loc for loc in locs if loc]
    else:
        urls = [loc for loc in locs if loc]
    return urls, children
