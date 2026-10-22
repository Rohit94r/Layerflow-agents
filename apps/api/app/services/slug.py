"""Slug generation and validation (plan §13.3): lowercase a-z0-9 + hyphen, 3–8 words, <=60 chars, no dates,
no stopword-only tail, unique. Fixes the live-site defect of titles concatenated into slugs."""

from __future__ import annotations

import re

from app.services.text import ascii_fold

SLUG_STOPWORDS = frozenset(
    "a an and the of in on at to for from by with as is are was were be or but into over under about its it this "
    "that these those vs via how why what who when where which will can could should would".split()
)
MONTHS = frozenset(
    "january february march april may june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec".split()
)
MAX_LEN = 60
MAX_WORDS = 8
MIN_WORDS = 3
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _tokens(text: str) -> list[str]:
    t = ascii_fold(text).lower().replace("&", " and ").replace("%", " percent ")
    t = re.sub(r"['’`]", "", t)
    return [tok for tok in re.split(r"[^a-z0-9]+", t) if tok]


def _is_date_token(tok: str) -> bool:
    return tok in MONTHS or bool(re.fullmatch(r"(19|20)\d{2}", tok))


def slugify(text: str, *, max_len: int = MAX_LEN, max_words: int = MAX_WORDS) -> str:
    toks = [t for t in _tokens(text) if not _is_date_token(t)]
    while toks and toks[0] in SLUG_STOPWORDS:
        toks.pop(0)
    # Prefer content words when the title is long: drop interior stopwords first.
    if len(toks) > max_words:
        toks = [t for i, t in enumerate(toks) if i == 0 or t not in SLUG_STOPWORDS]
    toks = toks[:max_words]
    out: list[str] = []
    for tok in toks:
        candidate = "-".join([*out, tok])
        if len(candidate) > max_len:
            break
        out.append(tok)
    while out and out[-1] in SLUG_STOPWORDS:
        out.pop()
    slug = "-".join(out)
    if not slug:
        slug = "article"
    return slug


def validate_slug(slug: str) -> list[str]:
    issues = []
    if not slug:
        return ["Slug is empty"]
    if len(slug) > MAX_LEN:
        issues.append(f"Slug is {len(slug)} chars; maximum is {MAX_LEN}")
    if not SLUG_RE.match(slug):
        issues.append("Slug must be lowercase ASCII letters, digits and single hyphens")
    parts = [p for p in slug.split("-") if p]
    if len(parts) < MIN_WORDS:
        issues.append(f"Slug has {len(parts)} words; use {MIN_WORDS}–{MAX_WORDS}")
    if len(parts) > MAX_WORDS:
        issues.append(f"Slug has {len(parts)} words; use {MIN_WORDS}–{MAX_WORDS}")
    if parts and parts[-1] in SLUG_STOPWORDS:
        issues.append("Slug ends with a stopword")
    if any(_is_date_token(p) for p in parts):
        issues.append("Slug contains a date; dates make URLs look stale")
    return issues


def unique_slug(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    for n in range(2, 100):
        suffix = f"-{n}"
        candidate = base[: MAX_LEN - len(suffix)].rstrip("-") + suffix
        if candidate not in taken:
            return candidate
    raise ValueError("Could not find a unique slug")


def is_malformed_live_slug(path_segment: str) -> bool:
    """Detect slugs like 'Open-AI-Models-Are-Changing-...' (title concatenated into the URL)."""
    seg = path_segment.strip("/").split("/")[-1]
    if not seg:
        return False
    return len(seg) > MAX_LEN or bool(re.search(r"[A-Z]", seg)) or seg.count("-") >= MAX_WORDS or " " in seg or "%20" in seg
