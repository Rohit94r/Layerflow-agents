"""A3 Writer — category-routed, section-by-section generation grounded only in the research pack.
Outline call -> one call per required section -> takeaway call. Numbers are checked against the evidence
inside the repair loop, so an invented statistic is rejected while the model can still fix it."""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.agents.base import AgentContext, InsufficientEvidence, structured
from app.agents.research import latest_pack
from app.core.db import session_factory
from app.models import Article, Topic
from app.queue.jobs import PermanentError
from app.services.article_doc import compute_stats, normalise_sections
from app.services.grounding import evidence_corpus
from app.services.playbooks import Playbook, get_playbook
from app.services.prompts import banned_list, compose_system, get_prompt, versions_tag
from app.services.text import numbers_in, truncate_words, word_count
from app.services.versions import add_version, current_payload


class OutlineSection(BaseModel):
    key: str
    heading: str = Field(min_length=2, max_length=120)
    point: str = Field(min_length=5, max_length=400, description="the one point this section makes")
    facts: list[int] = Field(default_factory=list, description="key fact ids this section will use")


class OutlineOut(BaseModel):
    title: str = Field(min_length=20, max_length=90)
    dek: str = Field(min_length=40, max_length=220)
    angle: str = Field(default="", max_length=300)
    sections: list[OutlineSection] = Field(min_length=3, max_length=10)


class SectionOut(BaseModel):
    paragraphs: list[str] = Field(min_length=1, max_length=8)
    bullets: list[str] = Field(default_factory=list, max_length=8)
    pull_quote: str | None = Field(default=None, max_length=300)
    facts_used: list[int] = Field(default_factory=list)

    @field_validator("paragraphs", "bullets")
    @classmethod
    def _strip(cls, v: list[str]) -> list[str]:
        return [p.strip() for p in v if p and p.strip()]


class TakeawayOut(BaseModel):
    takeaway: str = Field(min_length=60, max_length=420)


def _facts_block(pack: dict[str, Any], limit: int = 12) -> str:
    lines = []
    for f in pack.get("key_facts", [])[:limit]:
        conf = "" if f.get("confidence") in ("high", "medium") else f" [{f.get('confidence')}]"
        lines.append(f"[{f['id']}] {f['claim']} — {f.get('source_name') or 'source'}{conf}")
    nums = [f"- {n['value']} {n.get('unit', '')}: {n['context']}" for n in pack.get("numbers", [])[:12] if n.get("verified", True)]
    out = "KEY FACTS (cite by id):\n" + "\n".join(lines)
    if nums:
        out += "\n\nVERIFIED NUMBERS:\n" + "\n".join(nums)
    if pack.get("counterpoints"):
        out += "\n\nCOUNTERPOINTS:\n" + "\n".join(f"- {c}" for c in pack["counterpoints"][:5])
    if pack.get("context"):
        out += f"\n\nCONTEXT: {truncate_words(pack['context'], 700)}"
    return out


async def _style_profile(ctx: AgentContext) -> str | None:
    path = ctx.settings.evals_dir / "style" / "style_profile.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return "## MEASURED STYLE TARGETS (from mentor-approved samples)\n" + json.dumps(data, indent=0)[:1500]


async def run_writer(ctx: AgentContext, article_id: uuid.UUID, *, instruction: str | None = None, revision: int = 0) -> dict[str, Any]:
    async with session_factory()() as db:
        article = await db.get(Article, article_id)
        topic = await db.get(Topic, article.topic_id) if article and article.topic_id else None
        pack_row = await latest_pack(db, article_id)
        if article is None or topic is None:
            raise PermanentError("Article or topic missing")
        if pack_row is None or pack_row.status != "ok":
            raise InsufficientEvidence("No usable research pack; run Research first")
        pack = pack_row.payload
        style = await _style_profile(ctx)
        system, used = await compose_system(db, ctx.tenant.id, agent="writer", category=article.category, extra=style)
        previous = await current_payload(db, article) if instruction else {}
        persona_ref = await get_prompt(db, ctx.tenant.id, "persona/ten")
        banned = await banned_list(db, ctx.tenant.id)

    if article.category == "room" and not any(s.get("origin") == "editor notes" for s in pack.get("sources", [])):
        raise InsufficientEvidence("Room articles are written only from supplied transcript/interview material (add it to the topic notes)")

    art, stats = await compose(
        ctx, system=system, used=used, pack=pack, title=topic.title, angle=topic.angle, category=article.category,
        banned=banned, instruction=instruction, previous_article=(previous or {}).get("article"),
    )
    payload = {
        "article": art,
        "seo": None,
        "qa": None,
        "editor": None,
        "stats": stats,
        "sources_meta": [{"url": s["url"], "title": s.get("title"), "publisher": s.get("publisher")} for s in pack.get("sources", [])],
        "research_pack_id": str(pack_row.id),
    }
    async with session_factory()() as db:
        article = await db.get(Article, article_id)
        await add_version(
            db, article, stage="revised" if (instruction or revision) else "draft", payload=payload,
            note=(f"Revision: {instruction[:200]}" if instruction else None), prompt_version=versions_tag(used),
        )
        article.prompt_versions = {**(article.prompt_versions or {}), "writer": versions_tag(used), "persona": persona_ref.version}
        await db.commit()
    await ctx.log(f"Draft complete: {stats['word_count']} words ({'in' if stats['in_band'] else 'outside'} band)")
    return {"word_count": stats["word_count"], "in_band": stats["in_band"], "sections": len(art["sections"])}


async def compose(
    ctx: AgentContext,
    *,
    system: str,
    used: dict[str, str],
    pack: dict[str, Any],
    title: str,
    angle: str | None,
    category: str,
    banned: list[str] | None,
    instruction: str | None = None,
    previous_article: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pure writing step: evidence pack -> structured article. Used by the job and the eval harness."""
    pb = get_playbook(category)
    target = pb.target_words
    facts = _facts_block(pack)
    allowed_numbers = numbers_in(evidence_corpus(pack, extra=[title]))
    section_list = "\n".join(
        f"- {s.key}: default heading “{s.heading}”, about {pb.words_for(s.key, target)} words" for s in pb.sections
    )
    revise_note = f"\n\nREVISION REQUEST (address this directly): {instruction}" if instruction else ""
    prev_article = previous_article or {}

    # 1) Outline
    def validate_outline(o: OutlineOut) -> list[str]:
        keys = [s.key for s in o.sections]
        problems = [f"missing required section key '{k}'" for k in pb.section_keys if k not in keys]
        problems += [f"unknown section key '{k}'" for k in keys if k not in pb.section_keys]
        if len(set(keys)) != len(keys):
            problems.append("each section key must appear exactly once")
        bad = numbers_in(o.title + " " + o.dek) - allowed_numbers
        if bad:
            problems.append(f"title/dek use numbers not in the research pack: {', '.join(sorted(bad))}")
        return problems

    outline_prompt = (
        f"Plan a {pb.label} article (~{target} words, band {pb.min_words}–{pb.max_words}) on:\n{title}\n"
        f"Angle: {angle or 'the decision this changes for a senior leader'}\n\n"
        f"REQUIRED SECTIONS, in this order (use these exact keys):\n{section_list}\n\n{facts}"
        + (f"\n\nPREVIOUS TITLE: {prev_article.get('title')}" if prev_article else "")
        + revise_note
    )
    outline, _ = await structured(
        ctx, agent="writer", task="outline", system=system, prompt=outline_prompt, schema=OutlineOut, validate=validate_outline,
        context={"pack": pack, "topic": title, "category": category, "playbook": pb.section_keys, "instruction": instruction},
        prompt_version=versions_tag(used),
    )
    await ctx.log(f"Outline ready: “{outline.title}”")
    plan = {s.key: s for s in outline.sections}

    # Which sections to (re)write
    targets = list(pb.section_keys)
    prev_sections = {s.get("key"): s for s in prev_article.get("sections") or []}

    sections: list[dict[str, Any]] = []
    written_summaries: list[str] = []
    for i, key in enumerate(pb.section_keys, start=1):
        spec = pb.section(key)
        assert spec is not None
        words = pb.words_for(key, target)
        osec = plan[key]
        if key not in targets and key in prev_sections:
            sections.append(prev_sections[key])
            continue

        def validate_section(s: SectionOut, words: int = words, spec_key: str = key) -> list[str]:
            problems = []
            wc = word_count(" ".join(s.paragraphs + s.bullets))
            if wc < words * 0.5:
                problems.append(f"section is {wc} words; write about {words}")
            if wc > words * 2.2:
                problems.append(f"section is {wc} words; cut to about {words}")
            bad = numbers_in(" ".join(s.paragraphs + s.bullets + ([s.pull_quote] if s.pull_quote else []))) - allowed_numbers
            if bad:
                problems.append(
                    f"numbers {', '.join(sorted(bad))} are not in the research pack — remove them or use only pack numbers"
                )
            if spec_key == "lede" and word_count(" ".join(s.paragraphs)) > 60:
                problems.append("the lede must be one paragraph of at most 40 words")
            return problems

        prev_text = ""
        if key in prev_sections:
            prev_text = "\n\nPREVIOUS VERSION OF THIS SECTION (improve it, keep what works):\n" + "\n".join(prev_sections[key].get("paragraphs") or [])
        section_prompt = (
            f"Article: “{outline.title}” — {outline.dek}\n"
            f"Category: {pb.label}. Write section {i}/{len(pb.sections)}: key '{key}', heading “{osec.heading}”.\n"
            f"This section's point: {osec.point}\nTarget length: about {words} words"
            + (" (a single lede paragraph of at most 40 words, no heading)" if key == "lede" else "")
            + f".\nUse primarily facts {osec.facts or 'relevant to the point'}; list the fact ids you used in facts_used.\n"
            + ("Sections already written:\n" + "\n".join(written_summaries) + "\n" if written_summaries else "")
            + f"\n{facts}{prev_text}{revise_note}\n\n"
            "Rules: 2–4 sentences per paragraph; bullets only for 3+ parallel items; no numbers, names or quotes that are "
            "not in the facts above; no throat-clearing; do not repeat earlier sections."
        )
        out, _ = await structured(
            ctx, agent="writer", task="section", system=system, prompt=section_prompt, schema=SectionOut, validate=validate_section,
            context={"pack": pack, "key": key, "heading": osec.heading, "words": words, "facts": osec.facts, "category": category, "instruction": instruction},
            prompt_version=versions_tag(used),
        )
        sections.append(
            {
                "key": key,
                "heading": osec.heading if spec.show_heading else spec.heading,
                "paragraphs": out.paragraphs if key != "lede" else out.paragraphs[:1],
                "bullets": out.bullets,
                "pull_quote": out.pull_quote,
                "facts_used": [f for f in out.facts_used if isinstance(f, int)],
            }
        )
        written_summaries.append(f"- {osec.heading}: {truncate_words(out.paragraphs[0], 160)}")
        await ctx.log(f"Wrote section {i}/{len(pb.sections)}: {osec.heading}")

    # 3) Takeaway
    def validate_takeaway(t: TakeawayOut) -> list[str]:
        bad = numbers_in(t.takeaway) - allowed_numbers
        return [f"numbers {', '.join(sorted(bad))} not in the research pack"] if bad else []

    take, _ = await structured(
        ctx, agent="writer", task="takeaway", system=system,
        prompt=(
            f"Article: “{outline.title}”.\nSections:\n" + "\n".join(written_summaries)
            + "\n\nWrite the takeaway: 1–3 sentences (60–400 characters) naming the decision or trade-off this creates for a "
            "senior leader. No new facts."
        ),
        schema=TakeawayOut, validate=validate_takeaway,
        context={"pack": pack, "title": outline.title, "category": category},
        prompt_version=versions_tag(used),
    )

    fact_urls = {f["id"]: f["source_url"] for f in pack.get("key_facts", [])}
    used_ids: list[int] = []
    for s in sections:
        for fid in s.get("facts_used") or []:
            if fid in fact_urls and fid not in used_ids:
                used_ids.append(fid)
    sources_used: list[str] = []
    for fid in used_ids:
        if fact_urls[fid] not in sources_used:
            sources_used.append(fact_urls[fid])
    if not sources_used:
        sources_used = [s["url"] for s in pack.get("sources", [])]

    art = {
        "title": outline.title.strip().rstrip("."),
        "dek": outline.dek.strip(),
        "category": category,
        "sections": sections,
        "takeaway": take.takeaway.strip(),
        "sources_used": sources_used,
    }
    art = normalise_sections(art)
    stats = compute_stats(art, banned_phrases=banned)
    return art, stats


__all__ = ["run_writer", "compose", "Playbook"]
