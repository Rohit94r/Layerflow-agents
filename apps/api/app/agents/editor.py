"""A4 Editor & Formatting — deterministic transforms, a per-section model pass for clarity and rhythm, then
deterministic transforms again. The model pass is rejected for any section where it introduces a number that
was not already there (plan: 'diff shows no new numbers')."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentOutputError, structured
from app.core.db import session_factory
from app.models import Article
from app.queue.jobs import PermanentError
from app.services import banned as banned_mod
from app.services.article_doc import compute_stats, section_text
from app.services.formatter import format_article, format_report
from app.services.playbooks import get_playbook
from app.services.prompts import banned_list, compose_system, versions_tag
from app.services.text import numbers_in, word_count
from app.services.versions import add_version, current_payload


class EditedSection(BaseModel):
    paragraphs: list[str] = Field(min_length=1, max_length=8)
    bullets: list[str] = Field(default_factory=list, max_length=8)
    pull_quote: str | None = Field(default=None, max_length=300)
    changes: list[str] = Field(default_factory=list, max_length=6, description="short notes on what you changed")


async def run_editor(ctx: AgentContext, article_id: uuid.UUID, *, instruction: str | None = None) -> dict[str, Any]:
    async with session_factory()() as db:
        article = await db.get(Article, article_id)
        if article is None:
            raise PermanentError("Article missing")
        payload = await current_payload(db, article)
        if not payload.get("article"):
            raise PermanentError("Nothing to edit yet; run Write first")
        system, used = await compose_system(db, ctx.tenant.id, agent="editor", category=article.category)
        banned = await banned_list(db, ctx.tenant.id)

    spelling = ctx.tenant.settings.get("spelling", "en-US")
    art, change_log, report, stats = await edit(
        ctx, system=system, used=used, original=payload["article"], banned=banned, spelling=spelling, instruction=instruction
    )

    new_payload = {**payload, "article": art, "editor": {"change_log": change_log, "format_report": report}, "stats": stats, "qa": None}
    async with session_factory()() as db:
        article = await db.get(Article, article_id)
        await add_version(db, article, stage="edited", payload=new_payload, prompt_version=versions_tag(used),
                          note=f"Editor: {len(change_log)} change(s)" + (f"; instruction: {instruction[:120]}" if instruction else ""))
        article.prompt_versions = {**(article.prompt_versions or {}), "editor": versions_tag(used)}
        await db.commit()
    await ctx.log(f"Edit complete: {stats['word_count']} words, {len(report['violations'])} structural violation(s)")
    return {"changes": len(change_log), "violations": len(report["violations"]), "word_count": stats["word_count"]}


async def edit(
    ctx: AgentContext,
    *,
    system: str,
    used: dict[str, str],
    original: dict[str, Any],
    banned: list[str] | None,
    spelling: str = "en-US",
    instruction: str | None = None,
) -> tuple[dict[str, Any], list[str], dict[str, Any], dict[str, Any]]:
    """Pure editing step (no DB): returns (article, change_log, format_report, stats)."""
    original = copy.deepcopy(original)
    pb = get_playbook(original["category"])
    art, change_log = format_article(copy.deepcopy(original), spelling=spelling)
    wc = word_count(" ".join(section_text(s) for s in art["sections"]))
    _lo, hi = pb.length_band()
    tighten = hi / wc if wc > hi else 1.0
    if tighten < 1.0:
        change_log.append(f"Article is {wc} words, above the {pb.label} band; tightening sections by ~{int((1 - tighten) * 100)}%")

    rejected = 0
    for idx, section in enumerate(art["sections"]):
        await ctx.beat()
        before = section_text(section)
        before_numbers = numbers_in(before, significant_only=False)
        before_words = word_count(before)
        goal = int(before_words * tighten)
        hits = banned_mod.scan(before, banned)

        def validate(out: EditedSection, before_numbers: set[str] = before_numbers, goal: int = goal, key: str = section.get("key", "")) -> list[str]:
            text = " ".join(out.paragraphs + out.bullets + ([out.pull_quote] if out.pull_quote else []))
            problems = []
            new_nums = numbers_in(text, significant_only=False) - before_numbers
            if new_nums:
                problems.append(f"you added numbers that were not in the section: {', '.join(sorted(new_nums))}. Do not add facts.")
            w = word_count(text)
            if goal and (w < goal * 0.6 or w > goal * 1.3):
                problems.append(f"section is {w} words; keep it near {goal}")
            leftover = banned_mod.scan(text, banned)
            if leftover:
                problems.append("remove banned phrases: " + ", ".join(h["phrase"] for h in leftover))
            if key == "lede" and len(out.paragraphs) > 1:
                problems.append("the lede is a single paragraph")
            return problems

        prompt = (
            f"Edit this section of a {pb.label} article for clarity, flow and rhythm. Do not add facts, numbers, names or quotes. "
            f"Keep every number exactly as written. Spelling: {spelling}. Target about {goal} words.\n"
            f"Section heading: {section.get('heading')}\n"
            + (f"Banned phrases present that you must remove: {', '.join(h['phrase'] for h in hits)}\n" if hits else "")
            + (f"Editor's instruction: {instruction}\n" if instruction else "")
            + "\nSECTION TEXT:\n"
            + "\n\n".join(section.get("paragraphs") or [])
            + ("\n\nBULLETS:\n" + "\n".join(f"- {b}" for b in section.get("bullets") or []) if section.get("bullets") else "")
            + (f"\n\nPULL QUOTE: {section['pull_quote']}" if section.get("pull_quote") else "")
        )
        try:
            out, _ = await structured(
                ctx, agent="editor", task="section", system=system, prompt=prompt, schema=EditedSection, validate=validate,
                context={"section": section, "goal": goal, "instruction": instruction}, prompt_version=versions_tag(used), max_repairs=1,
            )
        except AgentOutputError as exc:
            rejected += 1
            change_log.append(f"[{section.get('key')}] Kept the deterministic edit; model edit rejected ({str(exc)[:120]})")
            continue
        section["paragraphs"] = out.paragraphs if section.get("key") != "lede" else out.paragraphs[:1]
        section["bullets"] = out.bullets
        section["pull_quote"] = out.pull_quote or section.get("pull_quote")
        change_log.extend(f"[{section.get('key')}] {c}" for c in out.changes[:4])
        await ctx.log(f"Edited section {idx + 1}/{len(art['sections'])}: {section.get('heading')}")

    art, change_log2 = format_article(art, spelling=spelling)
    change_log.extend(change_log2)
    art["sources_used"] = original.get("sources_used", [])
    for s_new, s_old in zip(art["sections"], original["sections"], strict=False):
        s_new["facts_used"] = s_old.get("facts_used", [])
    added = numbers_in(" ".join(section_text(s) for s in art["sections"]), significant_only=False) - numbers_in(
        " ".join(section_text(s) for s in original["sections"]), significant_only=False
    )
    report = format_report(art)
    report["new_numbers"] = sorted(added)
    report["model_sections_rejected"] = rejected
    stats = compute_stats(art, banned_phrases=banned)
    if not stats["in_band"] and stats["word_count"] < stats["band_min"]:
        report["warnings"].append({"code": "short", "message": "Below the length band; the editor cannot add facts — revise in Write"})
    return art, change_log, report, stats
