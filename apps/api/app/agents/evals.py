"""Evaluation harness (plan §18). Suites:
- deterministic: gates only on extractive known-good articles + seeded hallucinations (no model, seconds).
- critic: same cases, with the critic model rubric on top (catches 10/10 seeded stats? blocks <=2/10 good?).
- pipeline: golden cases through research synthesis -> writer -> editor -> critic on the configured model.
Results are stored as eval_runs rows and shown in Settings → Evaluations."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.agents.base import AgentContext
from app.agents.critic import evaluate
from app.agents.editor import edit
from app.agents.research import synthesize
from app.agents.writer import compose
from app.core.db import session_factory
from app.models import EvalRun
from app.queue.jobs import JobError
from app.services.extractive import extractive_article
from app.services.prompts import banned_list, compose_system
from app.services.sanitize import injection_flags

SEEDED = "Analysts now estimate the market will reach 847.3 billion by 2031, a 412% jump."


def load_cases(evals_dir: Path, ids: list[str] | None = None) -> list[dict[str, Any]]:
    out = []
    for p in sorted((evals_dir / "cases").glob("*.json")):
        try:
            case = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if ids and case.get("id") not in ids:
            continue
        out.append(case)
    return out


def case_sources(case: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i, s in enumerate(case.get("input", {}).get("sources", []), start=1):
        text = s.get("text") or ""
        out.append(
            {
                "index": i,
                "url": s.get("url") or f"https://example.com/source-{i}",
                "title": s.get("title"),
                "publisher": s.get("publisher"),
                "published_at": s.get("published_at"),
                "excerpt": text,
                "word_count": len(text.split()),
                "injection_flags": injection_flags(text),
            }
        )
    return out


def pack_from(case: dict[str, Any], synth: dict[str, Any]) -> dict[str, Any]:
    sources = case_sources(case)
    by_index = {s["index"]: s for s in sources}
    facts = []
    for f in synth.get("key_facts", []):
        src = by_index.get(f["source_index"], sources[0] if sources else {})
        facts.append({"id": len(facts) + 1, "claim": f["claim"], "source_index": f["source_index"], "source_url": src.get("url"), "source_name": src.get("publisher"), "confidence": f.get("confidence", "high")})
    return {
        "summary": synth.get("summary", ""),
        "key_facts": facts,
        "numbers": [{**n, "source_url": by_index.get(n["source_index"], {}).get("url"), "verified": True} for n in synth.get("numbers", [])],
        "context": synth.get("context", ""),
        "counterpoints": synth.get("counterpoints", []),
        "open_questions": synth.get("open_questions", []),
        "sources": sources,
        "coverage": {"source_count": len(sources)},
        "status": "ok" if len(sources) >= int(case.get("expected", {}).get("min_sources", 2)) else "insufficient_evidence",
    }


def usable_distinct(sources: list[dict[str, Any]], *, min_words: int = 50) -> int:
    """Sources that would survive the research agent's filters: not a paywall stub, not trivially short, and not
    a syndicated copy of another source (near-duplicates count once)."""
    from app.services.dedupe import TfidfIndex
    from app.services.extractor import PAYWALL_MARKERS

    usable = [s for s in sources if s["word_count"] >= min_words and not any(m in s["excerpt"].lower() for m in PAYWALL_MARKERS)]
    if len(usable) < 2:
        return len(usable)
    idx = TfidfIndex([s["excerpt"] for s in usable])
    distinct: list[int] = []
    for i in range(len(usable)):
        if all(TfidfIndex.cosine(idx.vectors[i], idx.vectors[j]) < 0.8 for j in distinct):
            distinct.append(i)
    return len(distinct)


def seed_hallucination(article: dict[str, Any]) -> dict[str, Any]:
    art = copy.deepcopy(article)
    target = next((s for s in art["sections"] if s.get("key") not in ("lede",) and s.get("paragraphs")), art["sections"][0])
    target["paragraphs"][0] = target["paragraphs"][0] + " " + SEEDED
    return art


async def run_eval(ctx: AgentContext, *, suite: str, case_ids: list[str] | None = None) -> dict[str, Any]:
    from app.services.extractive import research_pack

    cases = load_cases(ctx.settings.evals_dir, case_ids)
    if not cases:
        raise JobError("No eval cases found in evals/cases/")
    async with session_factory()() as db:
        banned = await banned_list(db, ctx.tenant.id)
        systems = {
            a: await compose_system(db, ctx.tenant.id, agent=a, category=None, include_persona=a != "research", include_style=a != "research")
            for a in ("research", "critic")
        }
        cat_systems: dict[str, tuple[str, dict[str, str]]] = {}
        for c in {c["category"] for c in cases if c.get("category") in ("brief", "thinking", "room", "playbook", "decisions", "deep_dive")}:
            cat_systems[f"writer:{c}"] = await compose_system(db, ctx.tenant.id, agent="writer", category=c)
            cat_systems[f"editor:{c}"] = await compose_system(db, ctx.tenant.id, agent="editor", category=c)
            cat_systems[f"critic:{c}"] = await compose_system(db, ctx.tenant.id, agent="critic", category=c)
    quality = ctx.tenant.settings.get("quality", {})
    details: list[dict[str, Any]] = []
    model_name = ctx.model_config("critic" if suite != "pipeline" else "writer")["model"] if suite != "deterministic" else "deterministic"

    if suite in ("deterministic", "critic"):
        caught = good_ok = good_total = seeded_total = 0
        for case in cases:
            if case.get("label") not in ("good", "adversarial"):
                continue
            await ctx.beat()
            sources = [{"index": s["index"], "text": s["excerpt"]} for s in case_sources(case)]
            synth = research_pack(sources, title=case["input"]["topic"]["title"])
            pack = pack_from(case, synth)
            if pack["status"] != "ok":
                continue
            art = extractive_article(case["category"], case["input"]["topic"]["title"], pack)
            system, used = cat_systems.get(f"critic:{case['category']}", systems["critic"])
            use_model = suite == "critic"
            good = await evaluate(ctx, system=system, used=used, payload={"article": art}, pack=pack, banned=banned, quality=quality,
                                  skip_gates=("seo_completeness", "length", "readability"), use_model=use_model)
            good_gate = next((g for g in good["gates"] if g["gate"] == "grounding"), {"passed": False})
            good_total += 1
            not_blocked = good["verdict"] != "block" and good_gate["passed"]
            good_ok += int(not_blocked)
            bad = await evaluate(ctx, system=system, used=used, payload={"article": seed_hallucination(art)}, pack=pack, banned=banned,
                                 quality=quality, skip_gates=("seo_completeness", "length", "readability"), use_model=use_model)
            flagged = any(i["code"] == "ungrounded_number" and ("847.3" in i["message"] or "412" in i["message"]) for i in bad["issues"])
            seeded_total += 1
            caught += int(flagged and bad["verdict"] != "pass")
            details.append({"case": case["id"], "good_verdict": good["verdict"], "good_grounded": good_gate["passed"], "seeded_flagged": flagged, "seeded_verdict": bad["verdict"]})
            await ctx.log(f"{case['id']}: good={good['verdict']} seeded={'caught' if flagged else 'MISSED'}")
        scores = {
            "seeded_caught": caught,
            "seeded_total": seeded_total,
            "good_not_blocked": good_ok,
            "good_total": good_total,
            "seeded_catch_rate": round(caught / seeded_total, 3) if seeded_total else None,
            "good_pass_rate": round(good_ok / good_total, 3) if good_total else None,
        }
        passed, total = caught + good_ok, seeded_total + good_total
    elif suite == "pipeline":
        passed = 0
        valid_json = sections_ok = grounded = 0
        for case in cases:
            await ctx.beat()
            exp = case.get("expected", {})
            topic = case["input"]["topic"]
            sources = case_sources(case)
            row: dict[str, Any] = {"case": case["id"], "expected": exp.get("verdict")}
            if usable_distinct(sources) < int(exp.get("min_sources", 2)):
                verdict = "insufficient_evidence"
                row.update({"verdict": verdict, "ok": exp.get("verdict") == verdict})
                passed += int(row["ok"])
                details.append(row)
                continue
            try:
                rsys, rused = systems["research"]
                pack = await synthesize(ctx, system=rsys, used=rused, title=topic["title"], category=case["category"], angle=topic.get("angle"),
                                        region=topic.get("region"), sources=sources)
                wsys, wused = cat_systems[f"writer:{case['category']}"]
                art, _stats = await compose(ctx, system=wsys, used=wused, pack=pack, title=topic["title"], angle=topic.get("angle"),
                                            category=case["category"], banned=banned)
                esys, eused = cat_systems[f"editor:{case['category']}"]
                art, _log, _report, _stats = await edit(ctx, system=esys, used=eused, original=art, banned=banned)
                csys, cused = cat_systems[f"critic:{case['category']}"]
                qa = await evaluate(ctx, system=csys, used=cused, payload={"article": art}, pack=pack, banned=banned, quality=quality,
                                    skip_gates=("seo_completeness",))
                valid_json += 1
            except JobError as exc:
                row.update({"verdict": "error", "error": str(exc)[:300], "ok": False})
                details.append(row)
                await ctx.log(f"{case['id']}: error {str(exc)[:120]}", level="warn")
                continue
            text = body_text_of(art).lower()
            must_not = [m for m in exp.get("must_not_contain", []) if m.lower() in text]
            sec_ok = all(k in {s["key"] for s in art["sections"]} for k in exp.get("required_sections", []))
            g_ok = next((g["passed"] for g in qa["gates"] if g["gate"] == "grounding"), False)
            sections_ok += int(sec_ok)
            grounded += int(g_ok)
            ok = sec_ok and not must_not and (qa["verdict"] == exp.get("verdict") or (exp.get("verdict") == "pass" and qa["verdict"] == "revise" and g_ok))
            passed += int(ok)
            row.update({"verdict": qa["verdict"], "overall": qa["overall"], "sections_ok": sec_ok, "grounded": g_ok, "must_not_hits": must_not, "ok": ok})
            details.append(row)
            await ctx.log(f"{case['id']}: {qa['verdict']} ({qa['overall']}) {'✓' if ok else '✗'}")
        total = len(cases)
        scores = {
            "valid_output": valid_json,
            "structure_ok": sections_ok,
            "grounded": grounded,
            "matched_expectation": passed,
            "cases": total,
        }
    else:
        raise JobError(f"Unknown eval suite '{suite}'")

    async with session_factory()() as db:
        run = EvalRun(tenant_id=ctx.tenant.id, agent=suite, model=model_name, scores=scores, details=details, passed=passed, total=total)
        db.add(run)
        await db.commit()
        rid = run.id
    await ctx.log(f"Eval '{suite}' finished: {passed}/{total}")
    return {"eval_run_id": str(rid), "passed": passed, "total": total, "scores": scores}


def body_text_of(art: dict[str, Any]) -> str:
    from app.services.article_doc import body_text

    return body_text(art, include_title=True)
