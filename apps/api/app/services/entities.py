"""Entity extraction (dictionary + heuristics, no model needed) and region tagging (plan §10.3)."""

from __future__ import annotations

import re
from typing import Any

COMPANY_SUFFIXES = (
    "Inc", "Inc.", "Corp", "Corp.", "Corporation", "Ltd", "Ltd.", "Limited", "LLC", "PLC", "plc", "Group", "Holdings",
    "Bank", "Capital", "Partners", "Technologies", "Technology", "Motors", "Airlines", "Industries", "Systems",
    "Labs", "Pharma", "Pharmaceuticals", "Energy", "Ventures", "Financial", "Insurance", "Foods", "Semiconductor",
    "AG", "SA", "NV", "SE", "GmbH", "Co", "Co.",
)
COUNTRY_REGION: dict[str, str] = {
    "india": "india", "indian": "india", "mumbai": "india", "delhi": "india", "bengaluru": "india", "bangalore": "india",
    "hyderabad": "india", "chennai": "india", "pune": "india", "sebi": "india", "rbi": "india", "nse": "india",
    "bse": "india", "sensex": "india", "nifty": "india", "rupee": "india", "crore": "india", "lakh": "india",
    "united states": "us", "u.s.": "us", "us": "us", "america": "us", "american": "us", "wall street": "us",
    "washington": "us", "new york": "us", "silicon valley": "us", "california": "us", "federal reserve": "us",
    "the fed": "us", "sec": "us", "nasdaq": "us", "nyse": "us", "s&p 500": "us", "dow jones": "us",
    "united kingdom": "uk", "uk": "uk", "britain": "uk", "british": "uk", "london": "uk", "ftse": "uk",
    "bank of england": "uk", "england": "uk", "scotland": "uk",
    "european union": "eu", "eu": "eu", "europe": "eu", "european": "eu", "brussels": "eu", "ecb": "eu",
    "germany": "eu", "german": "eu", "france": "eu", "french": "eu", "italy": "eu", "spain": "eu",
    "netherlands": "eu", "dutch": "eu", "sweden": "eu", "ireland": "eu", "paris": "eu", "berlin": "eu",
    "frankfurt": "eu", "eurozone": "eu",
    "uae": "mena", "dubai": "mena", "abu dhabi": "mena", "saudi": "mena", "saudi arabia": "mena", "riyadh": "mena",
    "qatar": "mena", "doha": "mena", "egypt": "mena", "israel": "mena", "kuwait": "mena", "oman": "mena",
    "bahrain": "mena", "turkey": "mena", "iran": "mena",
    "china": "apac", "chinese": "apac", "beijing": "apac", "shanghai": "apac", "shenzhen": "apac", "hong kong": "apac",
    "japan": "apac", "japanese": "apac", "tokyo": "apac", "korea": "apac", "south korea": "apac", "seoul": "apac",
    "singapore": "apac", "australia": "apac", "sydney": "apac", "indonesia": "apac", "vietnam": "apac",
    "thailand": "apac", "malaysia": "apac", "philippines": "apac", "taiwan": "apac", "new zealand": "apac",
    "nigeria": "africa", "kenya": "africa", "south africa": "africa", "ghana": "africa", "ethiopia": "africa",
    "lagos": "africa", "nairobi": "africa", "johannesburg": "africa", "morocco": "africa", "rwanda": "africa",
    "brazil": "latam", "mexico": "latam", "argentina": "latam", "chile": "latam", "colombia": "latam",
    "peru": "latam", "sao paulo": "latam", "latin america": "latam",
}
CURRENCY_REGION = (
    (re.compile(r"₹|\bRs\.?\s?\d|\bINR\b"), "india"),
    (re.compile(r"£|\bGBP\b"), "uk"),
    (re.compile(r"€|\bEUR\b"), "eu"),
    (re.compile(r"\bAED\b|\bSAR\b|\briyal"), "mena"),
    (re.compile(r"¥|\bJPY\b|\bCNY\b|\byuan\b|\bRMB\b"), "apac"),
)
_CAP_SEQ = re.compile(r"\b([A-Z][a-zA-Z&\.\-]+(?:\s+(?:of\s+|&\s+)?[A-Z][a-zA-Z&\.\-]+){0,4})")
_SKIP_CAPS = frozenset(
    "The A An In On At For And But Or Why How What When Where Who Which This That These Those It Its We Our You "
    "Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August "
    "September October November December Breaking Exclusive Update Live Analysis Opinion Report Watch Video".split()
)


def _word_re(term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w])" + re.escape(term) + r"(?![\w])", re.IGNORECASE)


def extract_entities(title: str, summary: str = "", watchlist: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    watchlist = watchlist or {}
    text = f"{title}. {summary or ''}"
    found: dict[str, dict[str, Any]] = {}

    def add(name: str, etype: str, in_title: bool, watch: bool = False) -> None:
        key = name.lower()
        cur = found.get(key)
        prominence = 1.0 if in_title else 0.6
        if cur is None:
            found[key] = {"name": name, "type": etype, "prominence": prominence, "watchlist": watch}
        else:
            cur["prominence"] = max(cur["prominence"], prominence)
            cur["watchlist"] = cur["watchlist"] or watch

    for etype, key in (("company", "companies"), ("person", "people"), ("sector", "sectors")):
        for term in watchlist.get(key, []) or []:
            if not term:
                continue
            pat = _word_re(term)
            if pat.search(text):
                add(term, etype, bool(pat.search(title)), watch=True)

    for m in _CAP_SEQ.finditer(text):
        phrase = m.group(1).strip(" .-")
        toks = phrase.split()
        while toks and toks[0] in _SKIP_CAPS:
            toks.pop(0)
        if not toks:
            continue
        phrase = " ".join(toks)
        low = phrase.lower()
        if low in COUNTRY_REGION:
            add(phrase, "country", phrase in title)
            continue
        if toks[-1] in COMPANY_SUFFIXES or (len(toks) >= 2 and toks[-1].rstrip(".") in COMPANY_SUFFIXES):
            add(phrase, "company", phrase in title)

    for term in COUNTRY_REGION:
        if len(term) <= 3:
            # short tokens (US, UK, EU, SEC) must be uppercase in the source text to count
            if re.search(r"(?<![\w.])" + re.escape(term.upper()) + r"(?![\w])", text):
                add(term.upper(), "country", term.upper() in title)
        elif _word_re(term).search(text):
            add(term.title(), "country", bool(_word_re(term).search(title)))

    ents = sorted(found.values(), key=lambda e: (-e["prominence"], not e["watchlist"], e["name"]))
    return ents[:15]


def tag_region(title: str, summary: str = "", *, default: str | None = None, entities: list[dict] | None = None) -> str:
    text = f"{title} {summary or ''}"
    votes: dict[str, float] = {}
    for pat, region in CURRENCY_REGION:
        if pat.search(text):
            votes[region] = votes.get(region, 0) + 1.5
    for e in entities or []:
        if e.get("type") == "country":
            region = COUNTRY_REGION.get(e["name"].lower())
            if region:
                votes[region] = votes.get(region, 0) + (1.5 if e.get("prominence", 0) >= 1 else 1.0)
    if votes:
        best = max(votes.items(), key=lambda kv: kv[1])
        if best[1] >= 1.0:
            return best[0]
    return default or "global"
