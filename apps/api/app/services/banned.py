"""Banned-phrase scanner (prompts/style/banned.txt) and the deterministic replacements the editor may apply."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

FALLBACK = (
    "in today's fast-paced world",
    "game-changer",
    "game changer",
    "revolutionize",
    "revolutionise",
    "unlock the power",
    "delve",
    "tapestry",
    "it's important to note",
    "it is important to note",
)

# Safe one-for-one swaps; anything not listed is left for the model/human to rewrite.
REPLACEMENTS = {
    "game-changer": "significant shift",
    "game changer": "significant shift",
    "revolutionize": "reshape",
    "revolutionise": "reshape",
    "revolutionizing": "reshaping",
    "revolutionising": "reshaping",
    "delve into": "examine",
    "delves into": "examines",
    "delving into": "examining",
    "it's important to note that ": "",
    "it is important to note that ": "",
    "in today's fast-paced world, ": "",
    "unlock the power of": "use",
    "cutting-edge": "advanced",
    "seamless": "smooth",
    "seamlessly": "smoothly",
    "leverage synergies": "combine strengths",
    "move the needle": "make a measurable difference",
    "at the end of the day, ": "",
    "in conclusion, ": "",
}


@lru_cache
def _load(path: str) -> tuple[str, ...]:
    p = Path(path)
    if not p.exists():
        return FALLBACK
    phrases = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            phrases.append(line.replace("’", "'"))
    return tuple(dict.fromkeys(phrases)) or FALLBACK


def banned_phrases(extra: list[str] | None = None) -> list[str]:
    base = list(_load(str(get_settings().prompts_dir / "style" / "banned.txt")))
    for e in extra or []:
        e = e.strip().lower()
        if e and e not in base:
            base.append(e)
    return base


def reload() -> None:
    _load.cache_clear()


def _pattern(phrase: str) -> re.Pattern[str]:
    esc = re.escape(phrase).replace("'", "['’]")
    return re.compile(r"(?<![\w])" + esc + r"(?![\w])", re.IGNORECASE)


def scan(text: str, phrases: list[str] | None = None) -> list[dict]:
    hits = []
    for phrase in phrases or banned_phrases():
        n = len(_pattern(phrase).findall(text or ""))
        if n:
            hits.append({"phrase": phrase, "count": n})
    return hits


def apply_replacements(text: str) -> tuple[str, list[str]]:
    changes = []
    removed = False
    for src, dst in REPLACEMENTS.items():
        pat = _pattern(src.strip()) if dst else re.compile(re.escape(src).replace("'", "['’]"), re.IGNORECASE)
        if pat.search(text):

            def _sub(m: re.Match[str], dst: str = dst) -> str:
                if not dst:
                    return ""
                return dst[0].upper() + dst[1:] if m.group(0)[:1].isupper() else dst

            text = pat.sub(_sub, text)
            removed = removed or not dst
            changes.append(f"Replaced '{src.strip()}'" + (f" with '{dst}'" if dst else ""))
    if removed:
        # Re-capitalise a sentence start exposed by a removal (leave camelCase like 'iPhone' alone).
        text = re.sub(r"(^|[.!?]\s+)([a-z])(?![A-Z])", lambda m: m.group(1) + m.group(2).upper(), text)
    return text, changes
