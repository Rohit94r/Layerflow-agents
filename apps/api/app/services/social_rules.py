"""LinkedIn post rules (plan §15.2), enforced deterministically after generation."""

from __future__ import annotations

import re

MIN_CHARS, MAX_CHARS = 700, 1300
MAX_HASHTAGS = 3
BANNED_SOCIAL = re.compile(
    r"(excited to share|thrilled to (announce|share)|i'?m (so )?(excited|thrilled|humbled)|🚀|agree\??\s*$|"
    r"comment below|tag someone|like if you|link in (the )?comments|what do you think\?\s*$)",
    re.I,
)
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF️]", re.UNICODE
)
HASHTAG = re.compile(r"(?<!\w)#(\w+)")


def strip_emoji(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", EMOJI.sub("", text))


def normalize_hashtags(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        t = re.sub(r"[^\w]", "", t.strip().lstrip("#"))
        if t and t.lower() not in {o.lower() for o in out}:
            out.append(t[:40])
    return out[:MAX_HASHTAGS]


def check_post(text: str, hashtags: list[str], *, opening_paragraph: str | None = None) -> list[str]:
    issues = []
    n = len(text or "")
    if n < MIN_CHARS:
        issues.append(f"Post is {n} characters; aim for {MIN_CHARS}–{MAX_CHARS}")
    elif n > MAX_CHARS:
        issues.append(f"Post is {n} characters; LinkedIn reach drops past {MAX_CHARS}")
    inline_tags = HASHTAG.findall(text or "")
    if len(hashtags or []) > MAX_HASHTAGS or len(inline_tags) > MAX_HASHTAGS:
        issues.append(f"Use at most {MAX_HASHTAGS} hashtags")
    if BANNED_SOCIAL.search(text or ""):
        issues.append("Contains engagement bait or 'excited to share' phrasing")
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if lines and len(lines[0]) > 210:
        issues.append("Hook is too long; the first two lines are all that show before 'see more'")
    if opening_paragraph and opening_paragraph[:120].strip() and opening_paragraph[:120].strip() in (text or ""):
        issues.append("Reuses the article's opening paragraph verbatim")
    if not re.search(r"https?://", text or ""):
        issues.append("No link to the article")
    return issues


def assemble(hook: str, body: str, leaders_line: str, cta: str, link: str | None, hashtags: list[str], *, emoji: bool) -> str:
    parts = [hook.strip(), body.strip()]
    if leaders_line.strip():
        parts.append(leaders_line.strip())
    tail = cta.strip()
    if link:
        tail = f"{tail}\n{link}" if tail else link
    if tail:
        parts.append(tail)
    if hashtags:
        parts.append(" ".join(f"#{h}" for h in hashtags))
    text = "\n\n".join(p for p in parts if p)
    if not emoji:
        text = strip_emoji(text)
    return text.strip()


def fit_length(hook: str, body: str, leaders_line: str, cta: str, link: str | None, hashtags: list[str], *, emoji: bool) -> str:
    """Trim the body at sentence boundaries until the post fits the 1,300-character ceiling."""
    text = assemble(hook, body, leaders_line, cta, link, hashtags, emoji=emoji)
    if len(text) <= MAX_CHARS:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", body.strip())
    while sentences and len(text) > MAX_CHARS:
        sentences.pop()
        text = assemble(hook, " ".join(sentences), leaders_line, cta, link, hashtags, emoji=emoji)
    return text
