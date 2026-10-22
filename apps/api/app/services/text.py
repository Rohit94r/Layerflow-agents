"""Deterministic text utilities shared by agents and gates: counting, readability, number/quote extraction
for grounding checks, and shingle overlap for duplication checks."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable

WORD_RE = re.compile(r"[A-Za-z0-9À-ɏ][A-Za-z0-9À-ɏ'’\-]*")
_ABBREV = (
    "Mr", "Mrs", "Ms", "Dr", "Prof", "Inc", "Ltd", "Co", "Corp", "St", "Jr", "Sr", "vs", "etc", "Mt", "No",
    "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec", "approx", "est", "Rs",
)
_ABBREV_RE = re.compile(r"\b(" + "|".join(_ABBREV) + r")\.", re.IGNORECASE)
_INITIALS_RE = re.compile(r"\b((?:[A-Z]\.){2,})")
_SENT_BOUNDARY = re.compile(r"(?<=[.!?])[\"”’)\]]*\s+(?=[\"“‘(\[]?[A-Z0-9])")
NUMBER_RE = re.compile(r"(?<![\w.\-/])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:\s?%)?")
QUOTE_RE = re.compile(r"[“\"]([^”\"]{12,600})[”\"]")
ZERO_WIDTH_RE = re.compile("[​‌‍⁠﻿­]")
STOPWORDS = frozenset(
    """a an and are as at be been being but by can could did do does for from had has have he her his how i if in
    into is it its may might more most must not of on or our over she should so than that the their them then there
    these they this those through to under up us was we were what when where which while who why will with would you
    your about after against all also any because before between both during each few further here just like many
    much new now only other out own same says said such too very via vs""".split()
)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", ZERO_WIDTH_RE.sub("", text or "")).strip()


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def words(text: str) -> list[str]:
    return WORD_RE.findall(text or "")


def word_count(text: str) -> int:
    return len(words(text))


def sentences(text: str) -> list[str]:
    text = normalize_space(text)
    if not text:
        return []
    protected = _ABBREV_RE.sub(lambda m: m.group(1) + "\u0000", text)
    protected = _INITIALS_RE.sub(lambda m: m.group(1).replace(".", "\u0000"), protected)
    parts = _SENT_BOUNDARY.split(protected)
    return [p.replace("\u0000", ".").strip() for p in parts if p.strip()]


def _syllables(word: str) -> int:
    w = word.lower().strip("'’-")
    if not w:
        return 0
    if w.isdigit():
        return max(1, len(w) // 2)
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    groups = re.findall(r"[aeiouy]{1,2}", w)
    return max(1, len(groups))


def readability(text: str) -> dict[str, float]:
    sents = sentences(text)
    ws = words(text)
    n_s, n_w = max(1, len(sents)), max(1, len(ws))
    syl = sum(_syllables(w) for w in ws)
    flesch = 206.835 - 1.015 * (n_w / n_s) - 84.6 * (syl / n_w)
    grade = 0.39 * (n_w / n_s) + 11.8 * (syl / n_w) - 15.59
    lens = [word_count(s) for s in sents] or [0]
    return {
        "flesch": round(flesch, 1),
        "grade": round(grade, 1),
        "avg_sentence_len": round(n_w / n_s, 1),
        "max_sentence_len": max(lens),
        "sentences": len(sents),
        "words": len(ws),
    }


def normalize_number(raw: str) -> str:
    s = raw.replace(",", "").replace("%", "").strip()
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.lstrip("0") or "0" if "." not in s else s


def numbers_in(text: str, *, significant_only: bool = True) -> set[str]:
    """Normalised numeric tokens. Small bare integers (0–10) are structural ('Step 2', 'two options')
    and excluded from grounding unless they carry a percent sign or decimals."""
    out: set[str] = set()
    for m in NUMBER_RE.finditer(text or ""):
        raw = m.group(0)
        norm = normalize_number(raw)
        if significant_only and "%" not in raw and "." not in raw.replace(",", ""):
            try:
                if int(norm) <= 10:
                    continue
            except ValueError:
                pass
        out.add(norm)
    return out


def quotes_in(text: str, min_words: int = 4) -> list[str]:
    found = []
    for m in QUOTE_RE.finditer(text or ""):
        q = normalize_space(m.group(1))
        if word_count(q) >= min_words:
            found.append(q)
    return found


def match_key(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    t = re.sub(r"[^a-z0-9%$.,' -]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def shingles(text: str, n: int = 5) -> set[str]:
    toks = [w.lower() for w in words(text)]
    if len(toks) < n:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)}


def containment(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def content_tokens(text: str) -> list[str]:
    return [w.lower() for w in words(text) if w.lower() not in STOPWORDS and len(w) > 2 and not w.isdigit()]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def truncate_words(text: str, max_chars: int, *, ellipsis: bool = False) -> str:
    text = normalize_space(text)
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars + 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    cut = cut.rstrip(" ,;:-–—")
    return (cut + "…") if ellipsis else cut


def join_text(parts: Iterable[str]) -> str:
    return "\n\n".join(p for p in parts if p)


def looks_english(text: str) -> bool:
    toks = [w.lower() for w in words(text)][:200]
    if not toks:
        return True
    non_ascii = sum(1 for ch in text[:2000] if ord(ch) > 0x2FF)
    if non_ascii > len(text[:2000]) * 0.2:
        return False
    hits = sum(1 for t in toks if t in STOPWORDS)
    return len(toks) < 8 or hits / len(toks) >= 0.12
