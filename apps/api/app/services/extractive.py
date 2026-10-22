"""Deterministic, extractive composition from source text. Grounded by construction (every factual sentence
is lifted from a source). Used by the mock provider (tests / model-free UI work, clearly labelled) and by the
eval harness to build known-good articles for the critic's seeded-hallucination test."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.services.playbooks import get_playbook
from app.services.text import numbers_in, sentences, truncate_words, word_count

CONTRAST = re.compile(r"\b(however|but|although|critics|risk|risks|concern|warned|uncertain|despite|challenge)\b", re.I)

# Number-free connective prose. Each section takes a disjoint slice (by its index in the playbook), so the
# editor's duplicate-sentence removal never strips them.
CONNECTIVES: dict[str, list[str]] = {
    "default": [
        "The more useful question for a senior leader is what this changes about the next allocation decision.",
        "Read together, the details point to a shift in where operating discipline will matter most.",
        "The signal is less the headline than the operating choices that sit behind it.",
        "Boards will want to see how the plan holds up once execution meets real constraints.",
        "That sequencing matters, because it decides who captures the value and who absorbs the cost.",
        "Competitors will read the same facts and draw different conclusions about timing.",
        "The trade-off is between moving early with incomplete information and waiting while options narrow.",
        "Execution risk sits in the handoffs between strategy, finance and operations rather than in the plan itself.",
        "None of this is guaranteed, and the evidence so far supports a cautious reading.",
        "For operators, the practical test is whether the economics still work at a smaller scale.",
        "Leaders who treat this as a one-off event are likely to misjudge what follows from it.",
        "The knock-on effect falls on suppliers, partners and talent markets that adjust more slowly.",
        "What looks like a single announcement is really a sequence of commitments that can still change.",
        "The cost of being wrong is asymmetric, which is why the timing deserves more attention than the headline.",
        "Most of the value will be decided by execution in the next few quarters, not by the plan on paper.",
        "Investors will judge the move on cash discipline as much as on ambition.",
        "A cautious reader should separate what has been committed from what has only been signalled.",
        "The obvious reading is not wrong, but it leaves out who has to change their plans in response.",
        "There is a governance question here as well, about who owns the outcome if targets slip.",
        "Customers rarely notice these decisions directly, but they feel the consequences in service and price.",
        "The organisations that benefit are the ones that prepare before the outcome is obvious.",
        "Watching the next disclosure will show whether the plan is accelerating or quietly being trimmed.",
        "The decision also narrows future options, which is a cost that rarely appears in the announcement.",
        "Regulators and lenders will read the same signal through their own priorities.",
        "The people closest to the work will usually spot execution problems before the board does.",
        "Capital committed early buys position, but it also buys exposure if conditions turn.",
        "A sensible response is to define in advance what evidence would change the decision.",
        "The competitive response matters as much as the original move.",
        "Scale helps, but it does not remove the need for clear accountability at each step.",
        "For a leadership team, the practical move is to stress-test its own plans against this signal.",
        "The interesting part is not the size of the commitment but what it assumes about demand.",
        "Second-guessing the headline is easy; deciding what to do on Monday morning is harder.",
        "Talent, not technology, is often the constraint that sets the real pace of change.",
        "Partners will want clarity on terms before they commit their own capital alongside.",
        "The story will look different once the first results are reported against the plan.",
        "It is worth asking which assumptions would have to hold for the optimistic case to play out.",
        "Smaller rivals may find room to move while larger players are absorbed in execution.",
        "Clear milestones make it easier to tell progress from activity.",
        "The real test is whether the organisation can learn quickly from the first phase.",
        "Leaders should resist the urge to copy the move without understanding the conditions behind it.",
    ],
}
SLICE = 6


def _pick(pool: list[str], seed: str, n: int) -> list[str]:
    h = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
    start = h % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(min(n, len(pool)))]


def fact_sentences(sources: list[dict[str, Any]], limit: int = 16) -> list[tuple[str, int]]:
    """Sentences worth citing, numbers first; each tagged with its 1-based source index."""
    scored: list[tuple[float, str, int]] = []
    seen: set[str] = set()
    for s in sources:
        idx = int(s.get("index", 1))
        for sent in sentences(s.get("text") or s.get("excerpt") or "")[:40]:
            wc = word_count(sent)
            if wc < 8 or wc > 45:
                continue
            key = sent.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            score = 2.0 if numbers_in(sent) else 0.0
            score += 0.5 if re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+", sent) else 0.0
            score += 0.3 if '"' in sent or "“" in sent else 0.0
            score -= 0.01 * len(scored)
            scored.append((score, sent.strip(), idx))
    scored.sort(key=lambda x: -x[0])
    return [(s, i) for _, s, i in scored[:limit]]


def research_pack(sources: list[dict[str, Any]], *, title: str) -> dict[str, Any]:
    facts = fact_sentences(sources, limit=12)
    numbers = []
    for sent, idx in facts:
        for n in sorted(numbers_in(sent))[:2]:
            numbers.append({"value": n, "unit": "", "context": truncate_words(sent, 190), "source_index": idx})
    first = sources[0] if sources else {}
    summary = " ".join(sentences(first.get("text") or first.get("excerpt") or "")[:2]) or title
    counter = [s for s, _ in fact_sentences(sources, limit=40) if CONTRAST.search(s)][:3]
    return {
        "summary": truncate_words(summary, 600) if word_count(summary) >= 8 else f"{title}. Coverage from {len(sources)} sources.",
        "key_facts": [{"claim": truncate_words(s, 390), "source_index": i, "confidence": "high"} for s, i in facts] or [
            {"claim": truncate_words(title, 390), "source_index": 1, "confidence": "low"}
        ],
        "numbers": numbers[:12],
        "context": truncate_words(" ".join(s for s, _ in facts[3:6]), 900),
        "counterpoints": [truncate_words(c, 300) for c in counter],
        "open_questions": ["What would change the timeline?", "Who bears the execution risk?"],
    }


def section_paragraphs(key: str, facts: list[dict[str, Any]], words: int, seed: str, index: int | None = None) -> tuple[list[str], list[int]]:
    """Build paragraphs of ~`words` words: fact claims (verbatim) interleaved with number-free connectives."""
    pool = CONNECTIVES["default"]
    if index is not None:
        start = (index * SLICE) % len(pool)
        connect = [pool[(start + i) % len(pool)] for i in range(SLICE)]
    else:
        connect = _pick(pool, seed + key, SLICE)
    paras: list[str] = []
    used: list[int] = []
    cur: list[str] = []
    total = 0
    ci = 0
    for f in facts:
        claim = f["claim"].rstrip(".") + "."
        cur.append(claim)
        used.append(f["id"])
        total += word_count(claim)
        if ci < len(connect):
            cur.append(connect[ci])
            total += word_count(connect[ci])
            ci += 1
        if len(cur) >= 3:
            paras.append(" ".join(cur))
            cur = []
        if total >= words:
            break
    while total < words * 0.8 and ci < len(connect):
        cur.append(connect[ci])
        total += word_count(connect[ci])
        ci += 1
        if len(cur) >= 3:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    if key == "lede":
        lede = truncate_words(facts[0]["claim"].rstrip(".") + "." if facts else connect[0], 230)
        for extra in connect:
            if word_count(lede) >= max(30, int(words * 0.6)):
                break
            if word_count(lede) + word_count(extra) <= 58:
                lede = f"{lede} {extra}"
        return [lede], used[:1]
    return paras or [connect[0]], used


def extractive_article(category: str, title: str, pack: dict[str, Any], *, dek: str | None = None) -> dict[str, Any]:
    pb = get_playbook(category)
    facts = pack.get("key_facts") or []
    n = len(pb.sections)
    sections = []
    for i, spec in enumerate(pb.sections):
        mine = [f for j, f in enumerate(facts) if j % max(1, n) == i] or (facts[i % len(facts) : i % len(facts) + 1] if facts else [])
        paras, used = section_paragraphs(spec.key, mine[:3], pb.words_for(spec.key), seed=title, index=i)
        sections.append({"key": spec.key, "heading": spec.heading, "paragraphs": paras, "bullets": [], "pull_quote": None, "facts_used": used})
    sources_used: list[str] = []
    for f in facts:
        if f.get("source_url") and f["source_url"] not in sources_used:
            sources_used.append(f["source_url"])
    return {
        "title": truncate_words(title, 88),
        "dek": dek or truncate_words(pack.get("summary") or title, 210),
        "category": category,
        "sections": sections,
        "takeaway": "The decision for leaders is whether to act on this signal now or wait for clearer evidence, accepting the cost of either choice.",
        "sources_used": sources_used,
    }
