"""Transparent candidate scoring (plan §5 A1). No model needed; weights are tenant-editable."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

SIGNALS: dict[str, tuple[float, tuple[str, ...]]] = {
    "m&a": (1.0, ("acquire", "acquires", "acquired", "acquisition", "merger", "merge", "takeover", "buyout", "m&a", "stake in", "deal to buy", "to buy")),
    "funding": (0.9, ("raises", "raised", "funding round", "series a", "series b", "series c", "series d", "seed round", "valuation", "invests", "investment of", "backed by")),
    "ipo": (0.9, ("ipo", "initial public offering", "listing", "goes public", "files to go public", "drhp", "s-1")),
    "earnings": (0.8, ("earnings", "quarterly results", "q1", "q2", "q3", "q4", "net profit", "revenue rose", "revenue fell", "guidance", "profit", "beats estimates", "misses estimates", "10-k", "10-q")),
    "capex": (0.8, ("capex", "capital expenditure", "new plant", "factory", "invest $", "investment plan", "data center", "data centre", "expansion")),
    "leadership": (0.7, ("ceo", "chief executive", "appoints", "appointed", "steps down", "resigns", "names new", "board", "chairman", "succession")),
    "regulation": (0.7, ("regulator", "regulation", "antitrust", "fine", "fined", "probe", "ruling", "ban", "tariff", "sanction", "policy", "compliance", "lawsuit")),
    "restructuring": (0.6, ("layoffs", "job cuts", "restructuring", "bankruptcy", "insolvency", "spin off", "spinoff", "divest", "divestiture")),
    "partnership": (0.5, ("partnership", "partners with", "joint venture", "alliance", "collaboration")),
    "strategy": (0.5, ("strategy", "pivot", "market share", "pricing", "expands into", "launches", "enters")),
}
_SIGNAL_PATTERNS = {
    name: (weight, [re.compile(r"(?<![\w])" + re.escape(t) + r"(?![\w])", re.IGNORECASE) for t in terms])
    for name, (weight, terms) in SIGNALS.items()
}
# A stated money amount ("$2.1 billion", "₹500 crore", "€3bn") is itself a business signal.
_SIGNAL_PATTERNS["deal_value"] = (
    0.75,
    [
        re.compile(r"[$€£₹¥]\s?\d[\d,.]*\s?(?:bn|mn|b|m|k|billion|million|trillion|crore|lakh)?\b", re.IGNORECASE),
        re.compile(r"\b\d[\d,.]*\s?(?:billion|million|trillion|crore|lakh|bn|mn)\b", re.IGNORECASE),
    ],
)


def recency(published_at: datetime | None, now: datetime, half_life_h: float = 12.0) -> float:
    if published_at is None:
        return 0.4
    age_h = max(0.0, (now - published_at).total_seconds() / 3600)
    return round(math.pow(0.5, age_h / half_life_h), 4)


def entity_relevance(entities: list[dict[str, Any]]) -> float:
    if not entities:
        return 0.0
    watch = [e for e in entities if e.get("watchlist")]
    base = sum(e.get("prominence", 0.6) for e in watch)
    other = sum(0.15 * e.get("prominence", 0.6) for e in entities if not e.get("watchlist") and e.get("type") == "company")
    return round(min(1.0, base * 0.6 + other), 4)


def business_signal(text: str) -> tuple[float, list[str]]:
    matched: list[tuple[str, float]] = []
    for name, (weight, pats) in _SIGNAL_PATTERNS.items():
        if any(p.search(text) for p in pats):
            matched.append((name, weight))
    if not matched:
        return 0.0, []
    top = max(w for _, w in matched)
    bonus = 0.05 * (len(matched) - 1)
    return round(min(1.0, top + bonus), 4), [n for n, _ in matched]


def source_quality(weight: float) -> float:
    return round(max(0.0, min(1.0, weight / 1.5)), 4)


def novelty(max_similarity: float) -> float:
    return round(max(0.0, 1.0 - max_similarity), 4)


def score(
    *,
    published_at: datetime | None,
    now: datetime,
    entities: list[dict[str, Any]],
    text: str,
    source_weight: float,
    max_similarity: float,
    weights: dict[str, float],
) -> tuple[float, dict[str, float], list[str]]:
    sig, signals = business_signal(text)
    breakdown = {
        "recency": recency(published_at, now),
        "entity": entity_relevance(entities),
        "signal": sig,
        "source": source_quality(source_weight),
        "novelty": novelty(max_similarity),
    }
    total = sum(weights.get(k, 0.0) * v for k, v in breakdown.items())
    return round(total, 4), breakdown, signals
