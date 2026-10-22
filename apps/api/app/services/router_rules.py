"""Deterministic category router (plan §6.2). The LLM may override only with high confidence, and the
reason is logged."""

from __future__ import annotations

import re

from app.services.scoring import business_signal

_DECISION = re.compile(r"\b(should (we|you|companies|leaders|boards|ceos)|which option|trade-?offs?|or not\b|build or buy|make or buy|choose between|versus|vs\.?)\b", re.I)
_PLAYBOOK = re.compile(r"\b(how to|framework|playbook|step[- ]by[- ]step|steps to|checklist|system for|guide to|lessons on how)\b", re.I)
_TRANSCRIPT = re.compile(r"\b(transcript|interview|in conversation|q&a|fireside|podcast|roundtable)\b", re.I)
_PUBLIC_FIN = re.compile(r"\b(annual report|10-k|10-q|earnings call|investor day|quarterly results|full-year results|fy\d{2}|shareholder letter)\b", re.I)
DEAL_SIGNALS = {"m&a", "funding", "ipo", "earnings", "capex", "deal_value"}


def route_category(
    title: str,
    summary: str = "",
    *,
    source_kind: str | None = None,
    source_count: int | None = None,
    word_count: int | None = None,
    has_company: bool = False,
) -> tuple[str, str]:
    text = f"{title}. {summary or ''}"
    _, signals = business_signal(text)
    deal = DEAL_SIGNALS & set(signals)
    if _TRANSCRIPT.search(text) and source_kind in {"manual", None}:
        return "room", "Supplied as interview/transcript material"
    if deal and (word_count is None or word_count < 550) and not _PUBLIC_FIN.search(text):
        return "brief", f"Deal/financial signal ({', '.join(sorted(deal))}) in a news item"
    if _DECISION.search(text):
        return "decisions", "Frames a choice or trade-off"
    if has_company and _PUBLIC_FIN.search(text) and (source_count is None or source_count >= 3):
        return "deep_dive", "Company with public financials and enough sources"
    if deal:
        return "brief", f"Deal/financial signal ({', '.join(sorted(deal))})"
    if _PLAYBOOK.search(text):
        return "playbook", "How-to / framework language"
    return "thinking", "Default: strategy or leadership theme"
