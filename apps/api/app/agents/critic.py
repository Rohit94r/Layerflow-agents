"""A6 QA / Critic — deterministic gates (cannot be overridden by a model) + adversarial rubric scored against
the sources. Pass rule: every score >= 3, factuality >= 4, no critical issue, every blocking gate passed."""

from __future__ import annotations

import uuid
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import AgentContext, AgentOutputError, structured
from app.agents.research import latest_pack
from app.core.db import session_factory, utcnow
from app.models import Article, ArticleVersion, Topic
from app.queue.jobs import PermanentError
from app.services.article_doc import body_text, compute_stats, to_markdown
from app.services.grounding import run_gates
from app.services.prompts import banned_list, compose_system, versions_tag
from app.services.text import truncate_words

SCORE_KEYS = ("factuality", "structure", "executive_value", "originality", "voice", "readability")
EXEC_QUESTIONS = {
    "decision": "What decision does this change for a senior leader?",
    "misconception": "What would most people get wrong about this?",
    "second_order": "What is the second-order effect?",
    "key_number": "What is the number that actually matters?",
    "opposite_case": "What would have to be true for the opposite conclusion to hold?",
}
WRITE_CODES = {"ungrounded_number", "ungrounded_quote", "missing_section", "empty_section", "schema", "duplication", "no_sources", "length_short", "exec_value"}
EDIT_CODES = {"banned_phrase", "long_paragraph", "double_space", "markdown_leak", "readability", "length_long", "duplicate_heading", "voice"}


class RubricIssue(BaseModel):
    severity: Literal["critical", "major", "minor"]
    message: str = Field(min_length=5, max_length=300)
    location: str = Field(default="body", max_length=60)


class RubricOut(BaseModel):
    factuality: int = Field(ge=1, le=5)
    structure: int = Field(ge=1, le=5)
    executive_value: int = Field(ge=1, le=5)
    originality: int = Field(ge=1, le=5)
    voice: int = Field(ge=1, le=5)
    readability: int = Field(ge=1, le=5)
    exec_questions_answered: list[Literal["decision", "misconception", "second_order", "key_number", "opposite_case"]] = Field(default_factory=list)
    issues: list[RubricIssue] = Field(default_factory=list, max_length=10)
    summary: str = Field(min_length=10, max_length=600)


def _deterministic_scores(gates: dict[str, bool]) -> dict[str, int]:
    return {
        "factuality": 5 if gates.get("grounding") else 1,
        "structure": 5 if gates.get("structure") else 2,
        "executive_value": 3,
        "originality": 4 if gates.get("duplication") else 1,
        "voice": 4 if gates.get("banned_phrases") else 2,
        "readability": 4 if gates.get("readability") else 3,
    }


async def run_critic(ctx: AgentContext, article_id: uuid.UUID) -> dict[str, Any]:
    async with session_factory()() as db:
        article = await db.get(Article, article_id)
        if article is None:
            raise PermanentError("Article missing")
        version = await db.get(ArticleVersion, article.current_version_id) if article.current_version_id else None
        payload = dict(version.payload) if version else {}
        if not payload.get("article"):
            raise PermanentError("Nothing to review yet; run Write first")
        pack_row = await latest_pack(db, article_id)
        pack = pack_row.payload if pack_row else {}
        topic = await db.get(Topic, article.topic_id) if article.topic_id else None
        published = list(
            (
                await db.execute(
                    select(ArticleVersion.payload)
                    .join(Article, Article.current_version_id == ArticleVersion.id)
                    .where(Article.tenant_id == ctx.tenant.id, Article.state == "published", Article.id != article_id)
                )
            ).scalars()
        )
        banned = await banned_list(db, ctx.tenant.id)
        system, used = await compose_system(db, ctx.tenant.id, agent="critic", category=article.category)

    qa = await evaluate(
        ctx, system=system, used=used, payload=payload, pack=pack,
        published_texts=[body_text((p or {}).get("article") or {}) for p in published], banned=banned,
        quality=ctx.tenant.settings.get("quality", {}), extra_evidence=[topic.title] if topic else None,
    )
    verdict, revise_stage, summary = qa["verdict"], qa["revise_stage"], qa["summary"]
    ranked = sorted(qa["issues"], key=lambda i: {"critical": 0, "major": 1, "minor": 2}[i["severity"]])
    block_reason = qa["block_reason"]
    new_payload = {**payload, "qa": qa}
    async with session_factory()() as db:
        article = await db.get(Article, article_id)
        from app.services.versions import add_version

        await add_version(db, article, stage="qa", payload=new_payload, prompt_version=versions_tag(used),
                          note=f"QA {verdict} ({qa['overall']})")
        article.prompt_versions = {**(article.prompt_versions or {}), "critic": versions_tag(used)}
        await db.commit()
    await ctx.log(f"QA verdict: {verdict.upper()} — overall {qa['overall']}/100" + (f"; revise via {revise_stage}" if verdict == "revise" else ""))
    return {
        "verdict": verdict,
        "block_reason": block_reason,
        "overall": qa["overall"],
        "revise_stage": qa["revise_stage"],
        "revision_instruction": qa["revision_instruction"],
        "summary": summary if verdict == "pass" else "; ".join(i["message"] for i in ranked[:3]),
    }


async def evaluate(
    ctx: AgentContext,
    *,
    system: str,
    used: dict[str, str],
    payload: dict[str, Any],
    pack: dict[str, Any],
    published_texts: list[str] | None = None,
    banned: list[str] | None = None,
    quality: dict[str, Any] | None = None,
    extra_evidence: list[str] | None = None,
    skip_gates: tuple[str, ...] = (),
    use_model: bool = True,
) -> dict[str, Any]:
    """Pure QA step (no DB): gates + rubric -> QA report. Used by the job and the eval harness."""
    art = payload["article"]
    quality = quality or {}
    gates, issues = run_gates(
        payload, pack, published_texts=published_texts, banned_phrases=banned, quality=quality, extra_evidence=extra_evidence,
    )
    if skip_gates:
        gates = [g for g in gates if g["gate"] not in skip_gates]
        issues = [i for i in issues if not ("seo_completeness" in skip_gates and i["code"] == "seo_incomplete")]
    gate_ok = {g["gate"]: g["passed"] for g in gates}
    stats = compute_stats(art, banned_phrases=banned)
    for i in issues:
        if i["code"] == "length":
            i["code"] = "length_short" if stats["word_count"] < stats["band_min"] else "length_long"
    await ctx.log(
        "Gates: " + ", ".join(f"{g['gate']} {'✓' if g['passed'] else '✗'}" for g in gates)
    )

    facts = "\n".join(f"[{f['id']}] {f['claim']} ({f.get('source_name')})" for f in pack.get("key_facts", [])[:14])
    excerpts = "\n\n".join(
        f'<source index="{s["index"]}" publisher="{s.get("publisher") or ""}">{truncate_words(s.get("excerpt") or "", 1200)}</source>'
        for s in pack.get("sources", [])[:5]
    )
    det_summary = "\n".join(f"- [{i['severity']}] {i['message']}" for i in issues[:12]) or "- none"
    prompt = (
        "Review this article adversarially against its sources. Score each rubric dimension 1–5. A number, name or quote "
        "that does not appear in the sources is a critical factuality issue. List which executive-value questions the article "
        "genuinely answers (decision, misconception, second_order, key_number, opposite_case).\n\n"
        f"DETERMINISTIC FINDINGS (already verified by code):\n{det_summary}\n\n"
        f"ARTICLE:\n{to_markdown(art)}\n\nRESEARCH FACTS:\n{facts}\n\n<research>\n{excerpts}\n</research>"
    )
    rubric_source = "model"
    try:
        if not use_model:
            raise AgentOutputError("model rubric disabled for this run")
        rubric, _ = await structured(
            ctx, agent="critic", task="rubric", system=system, prompt=prompt, schema=RubricOut,
            context={"article": art, "pack": pack, "gates": gate_ok, "issues": issues},
            prompt_version=versions_tag(used), max_repairs=1,
        )
        scores = {k: getattr(rubric, k) for k in SCORE_KEYS}
        answered = list(dict.fromkeys(rubric.exec_questions_answered))
        model_issues = [{"severity": i.severity, "code": "critic", "message": i.message, "location": i.location} for i in rubric.issues]
        summary = rubric.summary
    except AgentOutputError as exc:
        rubric_source = "deterministic"
        scores = _deterministic_scores(gate_ok)
        answered = ["decision"] if art.get("takeaway") else []
        model_issues = [{"severity": "minor", "code": "critic_unavailable", "message": f"Model rubric unavailable: {str(exc)[:120]}", "location": "qa"}]
        summary = "Scored by deterministic gates only (critic model output was invalid)."

    # Code-verified failures cap the model's scores: the model cannot talk its way past a failed gate.
    if not gate_ok.get("grounding", True):
        scores["factuality"] = min(scores["factuality"], 2)
    if not gate_ok.get("structure", True):
        scores["structure"] = min(scores["structure"], 2)
    if not gate_ok.get("duplication", True):
        scores["originality"] = min(scores["originality"], 1)
    if not gate_ok.get("banned_phrases", True):
        scores["voice"] = min(scores["voice"], 2)
    if not answered:
        issues.append({"severity": "major", "code": "exec_value", "message": "Answers none of the executive-value questions", "location": "body"})
        scores["executive_value"] = min(scores["executive_value"], 2)

    all_issues = issues + model_issues
    blocking_failed = [g for g in gates if g["blocking"] and not g["passed"]]
    critical = [i for i in all_issues if i["severity"] == "critical"]
    passes = all(v >= 3 for v in scores.values()) and scores["factuality"] >= 4 and not critical and not blocking_failed and bool(answered)

    pack_thin = not pack or pack.get("status") != "ok" or len(pack.get("key_facts", [])) < 3
    if passes:
        verdict, block_reason = "pass", None
    elif pack_thin:
        verdict, block_reason = "block", "grounding"
    else:
        verdict, block_reason = "revise", None

    codes = {i["code"] for i in all_issues}
    if codes & WRITE_CODES or (scores["executive_value"] < 3) or (scores["factuality"] < 4):
        revise_stage = "write"
    elif codes & EDIT_CODES or scores["voice"] < 3 or scores["readability"] < 3:
        revise_stage = "edit"
    elif not gate_ok.get("seo_completeness", True):
        revise_stage = "seo"
    else:
        revise_stage = "write"
    ranked = sorted(all_issues, key=lambda i: {"critical": 0, "major": 1, "minor": 2}[i["severity"]])
    instruction = "Fix these QA issues without adding facts that are not in the research pack:\n" + "\n".join(
        f"- {i['message']} ({i['location']})" for i in ranked[:8]
    )
    if "exec_value" in codes:
        instruction += "\n- Make the takeaway name a concrete decision or trade-off for a senior leader."

    qa = {
        "verdict": verdict,
        "block_reason": block_reason,
        "scores": scores,
        "overall": round(mean(scores.values()) / 5 * 100),
        "gates": gates,
        "issues": all_issues,
        "exec_questions_answered": answered,
        "exec_questions": EXEC_QUESTIONS,
        "summary": summary,
        "revise_stage": revise_stage if verdict == "revise" else None,
        "revision_instruction": instruction if verdict != "pass" else None,
        "rubric_source": rubric_source,
        "created_at": utcnow().isoformat(),
    }
    return qa
