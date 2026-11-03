"""Lead-image collection and editorial policy (plan §10.1, extended).

The dashboard only shows real publisher photography. A candidate image is accepted when it is:

- an absolute http(s) URL on a public host,
- a photographic raster format (jpg/jpeg/png/webp/avif) — never svg, gif, ico or data: URIs,
- not an obvious logo, icon, sprite, favicon, avatar, placeholder, spacer, pixel or tracking asset,
- landscape when dimensions are known (1.1–3.0), and at least ``MIN_WIDTH`` px wide.

Images are discovered in this order (first good candidate wins by score):

1. the feed itself — ``media:content``, ``media:thumbnail``, ``enclosure``/``link``, ``itunes:image``,
   ``<img>`` inside ``content:encoded``/``summary``, Reddit ``preview`` and GDELT ``socialimage``;
2. the article page — ``og:image`` / ``og:image:secure_url``, ``twitter:image``, ``link rel=image_src``
   and JSON-LD ``image`` (fetched only by the bounded discovery backfill, respecting robots.txt).

Remote URLs are stored; the browser loads them directly. Publisher CDNs are not mirrored, which keeps the
VPS disk small and avoids re-hosting copyrighted photography.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

MIN_WIDTH = 320
MIN_HEIGHT = 180
MIN_RATIO = 1.1
MAX_RATIO = 3.0
MAX_URL_LENGTH = 2048

ALLOWED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".avif"})
BLOCKED_EXTENSIONS = frozenset({".svg", ".svgz", ".gif", ".ico", ".bmp", ".tif", ".tiff"})

# `/logo.svg`, `site-logo-dark.png`, `icons/share.png`, `1x1.gif`, `spacer.png`, `tracking-pixel.png`…
_BLOCKED_MARKERS = re.compile(
    r"(?:^|[/_.=-])("
    r"logos?|icons?|favicon|sprite|sprites|avatar|avatars|placeholder|spacer|pixel|tracking|"
    r"badge|button|blank|transparent|1x1|share[-_]?(?:icon|image)|social[-_]?icon|default[-_]?(?:image|thumb)"
    r")(?:[/_.=-]|$)",
    re.I,
)
_TRACKING_QUERY = frozenset({"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "_ga", "_gl"})
_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_ATTR = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_JSONLD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)


@dataclass(frozen=True)
class ImageCandidate:
    url: str
    width: int | None = None
    height: int | None = None
    source: str = "feed"

    @property
    def ratio(self) -> float | None:
        if self.width and self.height:
            return self.width / self.height
        return None


def _to_int(value: Any) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _allowed(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    path = parts.path.lower()
    ext = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    if ext in BLOCKED_EXTENSIONS:
        return False
    if len(url) > MAX_URL_LENGTH:
        return False
    if _BLOCKED_MARKERS.search(f"{parts.path}?{parts.query}"):
        return False
    return True


def normalize_image_url(raw: Any, base_url: str | None = None) -> str | None:
    """Return a clean absolute image URL (or None when it is not a usable photograph)."""
    if raw is None:
        return None
    value = html_lib.unescape(str(raw)).strip().strip("\"'")
    if not value or value.startswith(("data:", "javascript:", "blob:")):
        return None
    if value.startswith("//"):
        value = "https:" + value
    elif not urlsplit(value).scheme:
        if not base_url:
            return None
        value = urljoin(base_url, value)
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _TRACKING_QUERY]
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    return clean if _allowed(clean) else None


def score_candidate(candidate: ImageCandidate) -> float:
    """Higher is better. Known large landscape photography beats an unknown thumbnail."""
    source_bonus = {"feed_media": 1.0, "feed_img": 0.7, "og": 0.9, "jsonld": 0.85, "social": 0.8, "reddit": 0.8}.get(
        candidate.source, 0.5
    )
    score = source_bonus
    if candidate.url.startswith("https://"):
        score += 0.2
    ext = "." + candidate.url.split("?", 1)[0].rsplit(".", 1)[-1].lower()
    if ext in (".jpg", ".jpeg", ".webp", ".avif"):
        score += 0.15
    if candidate.width and candidate.height:
        area = candidate.width * candidate.height
        score += min(area / 1_000_000, 2.0)
        ratio = candidate.width / candidate.height
        score += max(0.0, 1.0 - abs(ratio - 1.78) / 1.78)
        if candidate.width < 600:
            score -= 0.15
        if candidate.height < 315:
            score -= 0.15
    elif candidate.width:
        score += min(candidate.width / 1000, 1.5)
    return score


def pick_image(candidates: Iterable[ImageCandidate], *, min_width: int = MIN_WIDTH) -> ImageCandidate | None:
    """Apply the editorial policy and return the best surviving candidate."""
    best: ImageCandidate | None = None
    best_score = float("-inf")
    seen: set[str] = set()
    for raw in candidates:
        url = normalize_image_url(raw.url)
        if not url or url in seen:
            continue
        seen.add(url)
        width = raw.width or None
        height = raw.height or None
        if width and width < min_width:
            continue
        if height and height < MIN_HEIGHT:
            continue
        ratio = width / height if width and height else None
        if ratio and not (MIN_RATIO <= ratio <= MAX_RATIO):
            continue
        cand = ImageCandidate(url=url, width=width, height=height, source=raw.source)
        score = score_candidate(cand)
        if score > best_score:
            best, best_score = cand, score
    return best


# --------------------------------------------------------------------------- feeds
def _from_attrs(attrs: dict[str, str], base_url: str, source: str) -> ImageCandidate | None:
    url = attrs.get("url") or attrs.get("href") or attrs.get("src")
    if not url:
        return None
    return ImageCandidate(
        url=url,
        width=_to_int(attrs.get("width")),
        height=_to_int(attrs.get("height")),
        source=source,
    )


def _html_img_candidates(markup: str | None, base_url: str = "") -> list[ImageCandidate]:
    if not markup:
        return []
    out: list[ImageCandidate] = []
    for tag in _IMG_TAG.findall(markup):
        attrs = {m.group(1).lower(): html_lib.unescape(m.group(2) or m.group(3) or "") for m in _ATTR.finditer(tag)}
        src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-lazy-src")
        if not src:
            continue
        out.append(
            ImageCandidate(
                url=urljoin(base_url, src) if base_url else src,
                width=_to_int(attrs.get("width")),
                height=_to_int(attrs.get("height")),
                source="feed_img",
            )
        )
    return out


def candidates_from_feed_entry(entry: Any) -> list[ImageCandidate]:
    """Collect image candidates from a ``feedparser`` entry (RSS 2.0, Atom, Media RSS, iTunes)."""
    out: list[ImageCandidate] = []

    for key in ("media_content", "media_thumbnail"):
        for item in entry.get(key) or []:
            if not isinstance(item, dict):
                continue
            medium = (item.get("medium") or "").lower()
            mtype = (item.get("type") or "").lower()
            if medium and medium != "image":
                continue
            if mtype and not mtype.startswith("image") and not _looks_like_image_url(item.get("url", "")):
                continue
            cand = _from_attrs({**{k: str(v) for k, v in item.items() if k in ("url", "width", "height")}}, "", "feed_media")
            if cand:
                out.append(cand)

    for item in entry.get("enclosures") or []:
        if isinstance(item, dict) and (
            (item.get("type") or "").lower().startswith("image") or _looks_like_image_url(item.get("href") or item.get("url") or "")
        ):
            cand = _from_attrs({**{k: str(v) for k, v in item.items() if k in ("href", "url", "width", "height")}}, "", "feed_media")
            if cand:
                out.append(cand)

    for item in entry.get("links") or []:
        if not isinstance(item, dict):
            continue
        if (item.get("type") or "").lower().startswith("image") or item.get("rel") == "enclosure":
            cand = _from_attrs({**{k: str(v) for k, v in item.items() if k in ("href", "url", "width", "height")}}, "", "feed_media")
            if cand:
                out.append(cand)

    image = entry.get("image")
    if isinstance(image, dict):
        cand = _from_attrs({**{k: str(v) for k, v in image.items() if k in ("href", "url", "width", "height")}}, "", "feed_media")
        if cand:
            out.append(cand)
    elif isinstance(image, str) and _looks_like_image_url(image):
        out.append(ImageCandidate(url=image, source="feed_media"))

    for key in ("itunes_image", "media_image"):
        item = entry.get(key)
        if isinstance(item, dict):
            cand = _from_attrs({k: str(v) for k, v in item.items() if k in ("href", "url", "width", "height")}, "", "feed_media")
            if cand:
                out.append(cand)

    # Some feeds embed the lead image in the HTML summary/description/content:encoded.
    for key in ("content", "summary", "description"):
        value = entry.get(key)
        blocks = value if isinstance(value, list) else [value]
        for block in blocks:
            markup = block.get("value") if isinstance(block, dict) else block
            out.extend(_html_img_candidates(markup))

    return out


def _looks_like_image_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return any(path.endswith(ext) for ext in ALLOWED_EXTENSIONS)


# --------------------------------------------------------------------------- pages
def _jsonld_images(data: Any) -> list[str]:
    found: list[str] = []

    def visit(node: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, dict):
            image = node.get("image")
            if isinstance(image, str):
                found.append(image)
            elif isinstance(image, list):
                found.extend(i for i in image if isinstance(i, str))
                for i in image:
                    if isinstance(i, dict) and isinstance(i.get("url"), str):
                        found.append(i["url"])
            elif isinstance(image, dict) and isinstance(image.get("url"), str):
                found.append(image["url"])
            for value in node.values():
                if isinstance(value, (dict, list)):
                    visit(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                visit(value, depth + 1)

    visit(data)
    return found


def _meta_content(tree: Any, *, prop: str | None = None, name: str | None = None) -> str | None:
    if prop:
        values = tree.xpath(f"//meta[translate(@property,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='{prop.lower()}']/@content")
    else:
        values = tree.xpath(f"//meta[translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='{(name or '').lower()}']/@content")
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return None


def candidates_from_html(markup: str, base_url: str) -> list[ImageCandidate]:
    """Collect the publisher's declared social/lead image from an article page."""
    if not markup:
        return []
    try:
        tree = lxml_html.fromstring(markup)
    except (etree.ParserError, ValueError):
        return []
    out: list[ImageCandidate] = []

    width = _to_int(_meta_content(tree, prop="og:image:width"))
    height = _to_int(_meta_content(tree, prop="og:image:height"))
    for prop in ("og:image:secure_url", "og:image:url", "og:image"):
        value = _meta_content(tree, prop=prop)
        if value:
            out.append(ImageCandidate(url=urljoin(base_url, value), width=width, height=height, source="og"))
            break
    twitter = _meta_content(tree, name="twitter:image") or _meta_content(tree, name="twitter:image:src")
    if twitter:
        out.append(ImageCandidate(url=urljoin(base_url, twitter), source="og"))
    for href in tree.xpath("//link[translate(@rel,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='image_src']/@href"):
        if href:
            out.append(ImageCandidate(url=urljoin(base_url, str(href)), source="og"))

    for script in _JSONLD.findall(markup):
        try:
            import json

            data = json.loads(script.strip())
        except (ValueError, TypeError):
            continue
        for value in _jsonld_images(data):
            out.append(ImageCandidate(url=urljoin(base_url, value), source="jsonld"))

    # Last resort: a genuinely large inline image inside the article body (log kits are excluded by policy).
    for img in tree.xpath("//article//img|//main//img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        cand = ImageCandidate(
            url=urljoin(base_url, src),
            width=_to_int(img.get("width")),
            height=_to_int(img.get("height")),
            source="feed_img",
        )
        if (cand.width or 0) >= 600 or (cand.height or 0) >= 340:
            out.append(cand)
    return out
