"""Deterministic formatting duties of the editor (plan §5 A4). Rules run before and after the model pass,
so formatting is guaranteed even when the model is weak."""

from __future__ import annotations

import re
from typing import Any

from app.services import banned as banned_mod
from app.services.playbooks import get_playbook
from app.services.text import normalize_space, sentences, word_count

US_UK = {
    "organization": "organisation", "organizations": "organisations", "organize": "organise", "organized": "organised",
    "analyze": "analyse", "analyzed": "analysed", "analyzing": "analysing", "behavior": "behaviour",
    "behaviors": "behaviours", "center": "centre", "centers": "centres", "color": "colour", "favor": "favour",
    "favorable": "favourable", "labor": "labour", "optimize": "optimise", "optimized": "optimised",
    "optimization": "optimisation", "prioritize": "prioritise", "prioritized": "prioritised", "realize": "realise",
    "realized": "realised", "recognize": "recognise", "recognized": "recognised", "modeling": "modelling",
    "traveling": "travelling", "defense": "defence", "catalog": "catalogue", "fulfill": "fulfil",
    "capitalize": "capitalise", "capitalized": "capitalised", "monetize": "monetise", "monetization": "monetisation",
    "standardize": "standardise", "minimize": "minimise", "maximize": "maximise", "emphasize": "emphasise",
    "criticize": "criticise", "utilize": "utilise", "programs": "programmes", "license": "licence",
    "canceled": "cancelled", "neighbor": "neighbour", "honor": "honour", "rumor": "rumour", "endeavor": "endeavour",
    "jewelry": "jewellery", "aluminum": "aluminium", "skeptical": "sceptical", "skepticism": "scepticism",
}
UK_US = {v: k for k, v in US_UK.items()}


def _match_case(src: str, dst: str) -> str:
    if src.isupper():
        return dst.upper()
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


def apply_spelling(text: str, spelling: str) -> tuple[str, int]:
    table = US_UK if spelling == "en-GB" else UK_US
    n = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal n
        word = m.group(0)
        repl = table.get(word.lower())
        if repl is None:
            return word
        n += 1
        return _match_case(word, repl)

    pattern = re.compile(r"\b(" + "|".join(map(re.escape, sorted(table, key=len, reverse=True))) + r")\b", re.IGNORECASE)
    return pattern.sub(sub, text), n


def smart_quotes(text: str) -> str:
    text = re.sub(r'(^|[\s(\[{—–-])"', "\\1“", text)
    text = text.replace('"', "”")
    text = re.sub(r"(^|[\s(\[{—–-])'", "\\1‘", text)
    text = text.replace("'", "’")
    return text


def normalize_dashes(text: str, spelling: str = "en-US") -> str:
    text = re.sub(r"(?<=\d)\s?-\s?(?=\d)", "–", text)  # numeric ranges: 10–20
    if spelling == "en-GB":
        text = re.sub(r"\s+(--|—|-)\s+", " – ", text)
    else:
        text = re.sub(r"\s*--\s*|\s+-\s+|\s+—\s+", "—", text)
    return text


def fix_spacing(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", text)
    text = re.sub(r"\.{4,}", "…", text)
    return text.strip()


def split_paragraph(p: str, max_sentences: int = 4) -> list[str]:
    sents = sentences(p)
    if len(sents) <= max_sentences:
        return [p]
    chunks = []
    size = 3 if len(sents) > 6 else max(2, (len(sents) + 1) // 2)
    for i in range(0, len(sents), size):
        chunks.append(" ".join(sents[i : i + size]))
    return chunks


def clean_inline(text: str, spelling: str) -> str:
    text = normalize_space(text)
    text = text.lstrip("#*-•> ").strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # stray markdown bold from models
    text = fix_spacing(text)
    text = normalize_dashes(text, spelling)
    text = smart_quotes(text)
    return text


def format_article(article: dict[str, Any], *, spelling: str = "en-US") -> tuple[dict[str, Any], list[str]]:
    log: list[str] = []
    seen_sentences: set[str] = set()
    spell_changes = 0
    for field in ("title", "dek", "takeaway"):
        if article.get(field):
            new = clean_inline(article[field], spelling).strip("“”")
            new, n = apply_spelling(new, spelling)
            spell_changes += n
            article[field] = new
    for section in article.get("sections") or []:
        new_paras: list[str] = []
        for p in section.get("paragraphs") or []:
            p = clean_inline(p, spelling)
            p, n = apply_spelling(p, spelling)
            spell_changes += n
            p, changes = banned_mod.apply_replacements(p)
            log.extend(f"[{section.get('key')}] {c}" for c in changes)
            kept = []
            for s in sentences(p):
                key = re.sub(r"\W+", " ", s.lower()).strip()
                if len(key) > 25 and key in seen_sentences:
                    log.append(f"[{section.get('key')}] Removed duplicate sentence: “{s[:60]}…”")
                    continue
                seen_sentences.add(key)
                kept.append(s)
            p = " ".join(kept)
            if not p:
                continue
            parts = split_paragraph(p)
            if len(parts) > 1:
                log.append(f"[{section.get('key')}] Split a {len(sentences(p))}-sentence paragraph")
            new_paras.extend(parts)
        section["paragraphs"] = new_paras
        section["bullets"] = [clean_inline(b, spelling).rstrip(".;") for b in section.get("bullets") or [] if normalize_space(b)]
        if section.get("pull_quote"):
            section["pull_quote"] = clean_inline(section["pull_quote"], spelling).strip("“”\"")
        if section.get("heading"):
            section["heading"] = clean_inline(section["heading"], spelling).rstrip(".:")
    if spell_changes:
        log.append(f"Normalised {spell_changes} spelling(s) to {spelling}")
    article["word_count"] = sum(
        word_count(" ".join((s.get("paragraphs") or []) + (s.get("bullets") or []) + ([s["pull_quote"]] if s.get("pull_quote") else [])))
        for s in article.get("sections") or []
    ) + word_count(article.get("takeaway") or "")
    return article, log


def format_report(article: dict[str, Any]) -> dict[str, Any]:
    pb = get_playbook(article.get("category") or "brief")
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    title = article.get("title") or ""
    if not title:
        violations.append({"code": "missing_h1", "message": "Article has no title (H1)"})
    elif len(title) > 90:
        violations.append({"code": "h1_too_long", "message": f"Title is {len(title)} chars; keep under 90"})
    headings = [s.get("heading", "") for s in article.get("sections") or []]
    if len({h.lower() for h in headings}) != len(headings):
        violations.append({"code": "duplicate_heading", "message": "Two sections share a heading"})
    present = [s.get("key") for s in article.get("sections") or []]
    missing = [k for k in pb.section_keys if k not in present]
    for k in missing:
        violations.append({"code": "missing_section", "message": f"Required section '{pb.section(k).heading}' is missing"})
    long_paras = short_paras = empty_sections = 0
    for s in article.get("sections") or []:
        paras = s.get("paragraphs") or []
        if not paras and not s.get("bullets"):
            empty_sections += 1
        for p in paras:
            n = len(sentences(p))
            if n > 4:
                long_paras += 1
            if word_count(p) < 8:
                short_paras += 1
        for b in s.get("bullets") or []:
            if word_count(b) > 45:
                warnings.append({"code": "long_bullet", "message": f"Bullet in '{s.get('heading')}' exceeds 45 words"})
    if empty_sections:
        violations.append({"code": "empty_section", "message": f"{empty_sections} section(s) have no content"})
    if long_paras:
        violations.append({"code": "long_paragraph", "message": f"{long_paras} paragraph(s) exceed 4 sentences"})
    if short_paras:
        warnings.append({"code": "fragment", "message": f"{short_paras} paragraph(s) under 8 words"})
    body = " ".join(" ".join(s.get("paragraphs") or []) for s in article.get("sections") or [])
    if "  " in body:
        violations.append({"code": "double_space", "message": "Double spaces in body"})
    if re.search(r"(?m)^#{1,6}\s|\*\*", body):
        violations.append({"code": "markdown_leak", "message": "Markdown syntax leaked into paragraphs"})
    return {
        "violations": violations,
        "warnings": warnings,
        "h1_count": 1 if title else 0,
        "sections": len(present),
        "required_sections": len(pb.section_keys),
        "missing_sections": missing,
        "structural_ok": not violations,
    }
