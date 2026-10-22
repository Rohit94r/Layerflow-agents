"""Deterministic quality gates (plan §6.4). These run before the critic model and cannot be talked around:
an ungrounded number or quote is a critical issue regardless of what any model says."""

from __future__ import annotations

from typing import Any

from app.services import banned as banned_mod
from app.services.article_doc import body_text, compute_stats
from app.services.formatter import format_report
from app.services.playbooks import get_playbook
from app.services.seo_rules import completeness, validate_json_ld
from app.services.text import containment, match_key, numbers_in, quotes_in, shingles


def evidence_corpus(research: dict[str, Any], *, extra: list[str] | None = None) -> str:
    parts: list[str] = [research.get("summary") or "", research.get("context") or ""]
    for f in research.get("key_facts") or []:
        parts.append(f.get("claim") or "")
    for n in research.get("numbers") or []:
        parts.append(f"{n.get('value', '')} {n.get('unit', '')} {n.get('context', '')}")
    for s in research.get("sources") or []:
        parts += [s.get("title") or "", s.get("excerpt") or ""]
    parts += extra or []
    return "\n".join(parts)


def ungrounded_numbers(article: dict[str, Any], research: dict[str, Any], *, extra: list[str] | None = None) -> list[str]:
    allowed = numbers_in(evidence_corpus(research, extra=extra))
    found = numbers_in(body_text(article, include_title=True))
    return sorted(found - allowed, key=lambda x: (len(x), x))


def ungrounded_quotes(article: dict[str, Any], research: dict[str, Any]) -> list[str]:
    corpus = match_key(evidence_corpus(research))
    out = []
    for q in quotes_in(body_text(article, include_title=False)):
        if match_key(q) not in corpus:
            out.append(q)
    return out


def duplication(article: dict[str, Any], published_texts: list[str]) -> float:
    mine = shingles(body_text(article))
    best = 0.0
    for other in published_texts:
        best = max(best, containment(mine, shingles(other)))
    return round(best, 4)


def run_gates(
    payload: dict[str, Any],
    research: dict[str, Any],
    *,
    published_texts: list[str] | None = None,
    banned_phrases: list[str] | None = None,
    quality: dict[str, Any] | None = None,
    extra_evidence: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (gates, issues). Gate = {gate, passed, blocking, detail}. Issue = {severity, code, message, location}."""
    quality = quality or {}
    article = payload.get("article") or {}
    seo = payload.get("seo") or {}
    gates: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    def gate(name: str, passed: bool, blocking: bool, detail: str) -> None:
        gates.append({"gate": name, "passed": passed, "blocking": blocking, "detail": detail})

    # Schema
    required = ("title", "dek", "category", "sections", "takeaway", "sources_used")
    missing = [k for k in required if not article.get(k)]
    gate("schema", not missing, True, "All required fields present" if not missing else f"Missing: {', '.join(missing)}")
    for k in missing:
        issues.append({"severity": "critical", "code": "schema", "message": f"Missing field '{k}'", "location": k})

    # Grounding
    bad_numbers = ungrounded_numbers(article, research, extra=extra_evidence)
    bad_quotes = ungrounded_quotes(article, research)
    grounded = not bad_numbers and not bad_quotes
    detail = "Every number and quote maps to the research pack"
    if not grounded:
        detail = "; ".join(
            x
            for x in (
                f"Numbers not in sources: {', '.join(bad_numbers[:8])}" if bad_numbers else "",
                f"{len(bad_quotes)} quote(s) not found in sources" if bad_quotes else "",
            )
            if x
        )
    gate("grounding", grounded, True, detail)
    for n in bad_numbers:
        issues.append({"severity": "critical", "code": "ungrounded_number", "message": f"'{n}' does not appear in any source", "location": _locate(article, n)})
    for q in bad_quotes:
        issues.append({"severity": "critical", "code": "ungrounded_quote", "message": f"Quote not found in sources: “{q[:80]}”", "location": _locate(article, q[:30])})
    if not article.get("sources_used"):
        issues.append({"severity": "critical", "code": "no_sources", "message": "Article cites no sources", "location": "sources"})

    # Structure
    report = format_report(article)
    gate("structure", report["structural_ok"], True, "Category sections present; one H1" if report["structural_ok"] else "; ".join(v["message"] for v in report["violations"][:4]))
    for v in report["violations"]:
        issues.append({"severity": "major", "code": v["code"], "message": v["message"], "location": "structure"})

    # Length
    stats = compute_stats(article, banned_phrases=banned_phrases)
    pb = get_playbook(article.get("category") or "brief")
    gate("length", stats["in_band"], True, f"{stats['word_count']} words (band {stats['band_min']}–{stats['band_max']})")
    if not stats["in_band"]:
        issues.append({"severity": "major", "code": "length", "message": f"{stats['word_count']} words; {pb.label} needs {pb.min_words}–{pb.max_words} (±15%)", "location": "body"})

    # Banned phrases
    hits = banned_mod.scan(body_text(article, include_title=True), banned_phrases)
    gate("banned_phrases", not hits, True, "0 hits" if not hits else ", ".join(h["phrase"] for h in hits))
    for h in hits:
        issues.append({"severity": "major", "code": "banned_phrase", "message": f"Banned phrase '{h['phrase']}' ×{h['count']}", "location": _locate(article, h["phrase"])})

    # Duplication
    dup = duplication(article, published_texts or [])
    limit = float(quality.get("duplication_max", 0.08))
    gate("duplication", dup < limit, True, f"Max overlap with published articles {dup:.1%} (limit {limit:.0%})")
    if dup >= limit:
        issues.append({"severity": "critical", "code": "duplication", "message": f"{dup:.0%} overlap with a published article", "location": "body"})

    # SEO completeness
    if seo:
        done, missing_fields = completeness(seo)
        ld_issues = validate_json_ld(seo.get("json_ld") or [])
        ok = done == 8 and not ld_issues
        gate("seo_completeness", ok, True, f"{done}/8 fields valid" + (f"; {ld_issues[0]}" if ld_issues else ""))
        if not ok:
            issues.append({"severity": "major", "code": "seo_incomplete", "message": f"SEO {done}/8; missing {', '.join(missing_fields) or 'valid JSON-LD'}", "location": "seo"})
    else:
        gate("seo_completeness", False, True, "SEO stage has not run")

    # Readability (warn only)
    rd = stats["readability"]
    fmin, fmax = quality.get("flesch_min", 45), quality.get("flesch_max", 65)
    avg_max = quality.get("avg_sentence_max", 24)
    long_form = pb.min_words >= 900
    rd_ok = (not long_form or fmin - 10 <= rd["flesch"] <= fmax + 15) and rd["avg_sentence_len"] <= avg_max
    gate("readability", rd_ok, False, f"Flesch {rd['flesch']}, avg sentence {rd['avg_sentence_len']} words")
    if not rd_ok:
        issues.append({"severity": "minor", "code": "readability", "message": f"Flesch {rd['flesch']} / avg sentence {rd['avg_sentence_len']} words", "location": "body"})
    return gates, issues


def _locate(article: dict[str, Any], needle: str) -> str:
    low = needle.lower()
    if low in (article.get("title") or "").lower():
        return "title"
    if low in (article.get("dek") or "").lower():
        return "dek"
    for s in article.get("sections") or []:
        text = " ".join((s.get("paragraphs") or []) + (s.get("bullets") or []) + [s.get("pull_quote") or ""]).lower()
        if low in text or low.replace(",", "") in text.replace(",", ""):
            return f"section:{s.get('key')}"
    if low in (article.get("takeaway") or "").lower():
        return "takeaway"
    return "body"
