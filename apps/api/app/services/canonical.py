"""URL canonicalisation (plan §10.2): lowercase host, strip tracking params, normalise slashes, resolve AMP
variants, unwrap Bing/Google redirect wrappers to the publisher URL where possible."""

from __future__ import annotations

import base64
import binascii
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

TRACKING_EXACT = frozenset(
    {
        "fbclid", "gclid", "dclid", "msclkid", "ref", "ref_src", "ref_url", "referrer", "mc_cid", "mc_eid", "cmpid",
        "ocid", "_ga", "_gl", "igshid", "smid", "sr_share", "spm", "guccounter", "guce_referrer", "guce_referrer_sig",
        "taid", "ito", "cid", "trk", "trkcampaign", "src", "source", "partner", "via", "share", "amp", "outputtype",
        "rss", "feed", "s_cid", "icid", "yptr", "xtor", "ns_mchannel", "ns_source", "ns_campaign", "ns_linkname",
    }
)
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_", "oly_", "vero_")
_HOST_PREFIXES = ("www.", "m.", "amp.", "mobile.")
_URL_IN_BYTES = re.compile(rb"https?://[\x21-\x7e]+")
TWO_LEVEL_TLDS = frozenset({"co.uk", "co.in", "com.au", "co.jp", "com.br", "co.nz", "com.sg", "co.za", "com.mx", "org.uk", "ac.uk", "gov.uk", "net.in", "org.in"})


def _unwrap_google_news(url: str) -> str | None:
    parts = urlsplit(url)
    m = re.search(r"/(?:rss/)?articles/([A-Za-z0-9_\-]+)", parts.path)
    if not m:
        return None
    token = m.group(1)
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, binascii.Error):
        return None
    hit = _URL_IN_BYTES.search(raw)
    if not hit:
        return None
    candidate = hit.group(0).decode("ascii", "ignore")
    # protobuf length prefix bytes can trail the URL
    candidate = re.split(r"[\x00-\x1f\"<>\\^`{|}]", candidate)[0]
    return candidate if candidate.startswith("http") and "news.google.com" not in candidate else None


def unwrap(url: str) -> str:
    """Return the publisher URL behind a known redirect wrapper (or the input unchanged)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    host = (parts.hostname or "").lower()
    qs = dict(parse_qsl(parts.query, keep_blank_values=True))
    if host.endswith("bing.com") and "apiclick" in parts.path.lower() and qs.get("url"):
        return unquote(qs["url"])
    if host.endswith("google.com") and parts.path == "/url" and (qs.get("q") or qs.get("url")):
        return unquote(qs.get("q") or qs.get("url") or url)
    if host == "news.google.com":
        decoded = _unwrap_google_news(url)
        if decoded:
            return decoded
    if host.endswith("feedproxy.google.com") or host.endswith("feeds.feedburner.com"):
        return url
    return url


def canonicalize(url: str) -> str:
    url = unwrap(url)
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    scheme = (parts.scheme or "https").lower()
    if scheme not in ("http", "https"):
        return url.strip()
    host = (parts.hostname or "").lower().rstrip(".")
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix) and host.count(".") >= 2:
            host = host[len(prefix) :]
            break
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    path = re.sub(r"/amp/?$", "", path)
    path = re.sub(r"\.amp(\.html?)$", r"\1", path)
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() not in TRACKING_EXACT and not k.lower().startswith(TRACKING_PREFIXES)
    ]
    query.sort()
    return urlunsplit(("https" if scheme in ("http", "https") else scheme, netloc, path or "/", urlencode(query), ""))


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in TWO_LEVEL_TLDS:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def publisher_from_url(url: str) -> str:
    d = domain_of(url)
    name = d.split(".")[0]
    return name.replace("-", " ").title() if name else d
