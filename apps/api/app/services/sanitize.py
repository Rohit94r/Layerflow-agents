"""Prompt-injection defence for fetched content (plan §12.3). Fetched text is data, never instructions."""

from __future__ import annotations

import html
import re

from app.services.text import ZERO_WIDTH_RE, normalize_space

INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts|messages|rules)",
        r"disregard (all |any |the )?(previous|prior|above) (instructions|rules)",
        r"you are now\b",
        r"^\s*system\s*:",
        r"\bsystem prompt\b",
        r"\bnew instructions\b",
        r"\bact as (an?|the)\b",
        r"\bdo not (tell|inform|mention to) the (user|editor|reader)\b",
        r"\boverride (your|the) (instructions|rules|guidelines)\b",
        r"</?(source|research|system|assistant|user)>",
        r"\bwrite that\b.{0,80}\b(stock|shares|price) will\b",
    )
]
_HIDDEN_ELEMENT = re.compile(
    r"<(\w+)[^>]*(?:display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|\bhidden\b|aria-hidden=\"true\")[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SCRIPT_STYLE = re.compile(r"<(script|style|noscript|template|svg)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
UNTRUSTED_CAP = 4000


def strip_hidden_html(raw_html: str) -> str:
    out = _COMMENT.sub(" ", raw_html or "")
    out = _SCRIPT_STYLE.sub(" ", out)
    prev = None
    while prev != out:
        prev = out
        out = _HIDDEN_ELEMENT.sub(" ", out)
    return out


def clean_text(text: str) -> str:
    text = ZERO_WIDTH_RE.sub("", text or "")
    text = html.unescape(text)
    text = re.sub(r"</?(source|research|system|assistant|user)[^>]*>", " ", text, flags=re.IGNORECASE)
    # paywall / subscription tails
    text = re.split(r"(?i)\b(subscribe to (continue|read)|to continue reading|already a subscriber\?|sign in to continue)", text)[0]
    return text.strip()


def injection_flags(text: str) -> list[str]:
    flags = []
    for pat in INJECTION_PATTERNS:
        m = pat.search(text or "")
        if m:
            flags.append(normalize_space(m.group(0))[:80])
    return flags


def wrap_source(index: int, url: str, publisher: str, text: str, cap: int = UNTRUSTED_CAP) -> str:
    body = normalize_space(clean_text(text))[:cap]
    url_attr = html.escape(url, quote=True)
    pub_attr = html.escape(publisher or "", quote=True)
    return f'<source index="{index}" url="{url_attr}" publisher="{pub_attr}">\n{body}\n</source>'
