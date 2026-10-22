"""Mock provider (MODEL_PROVIDER=mock): deterministic, extractive, schema-valid outputs for every agent task.
For tests and for UI work on machines without a model. The dashboard labels it 'Mock provider' so nobody
mistakes its output for model writing."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from app.providers.base import ModelResult, ProviderHealth
from app.services.extractive import CONNECTIVES, _pick, research_pack, section_paragraphs
from app.services.seo_rules import fit_meta, fit_title
from app.services.text import truncate_words, word_count


class MockProvider:
    name = "mock"
    base_url = "mock://local"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: dict[str, Any] | None,
        temperature: float,
        max_tokens: int,
        timeout_s: int,
        num_ctx: int | None = None,
        task: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> ModelResult:
        ctx = context or {}
        self.calls.append({"task": task, "model": model})
        out = self._dispatch(task or "", ctx, prompt)
        text = json.dumps(out)
        return ModelResult(text=text, model=model, provider=self.name, prompt_tokens=len(prompt) // 4, completion_tokens=len(text) // 4, latency_ms=5)

    # ---- tasks ----
    def _dispatch(self, task: str, c: dict[str, Any], prompt: str) -> dict[str, Any]:
        if task == "classify":
            return {
                "category": c.get("rules_category") or "thinking",
                "confidence": 0.6,
                "why_it_matters": truncate_words(c.get("summary") or c.get("title") or "Signals a shift in competitive position for operators.", 135)
                if word_count(c.get("summary") or c.get("title") or "") >= 3
                else "Signals a shift in competitive position for operators.",
                "entities": [],
            }
        if task == "synthesize":
            sources = [{"index": s["index"], "text": s.get("text", "")} for s in c.get("sources", [])]
            return research_pack(sources, title=c.get("topic", ""))
        if task == "outline":
            pack = c.get("pack") or {}
            facts = pack.get("key_facts") or []
            keys = c.get("playbook") or []
            title = fit_title(c.get("topic") or "Untitled analysis")
            if len(title) < 20:
                title = (title + ": what it means for leaders")[:88]
            dek = truncate_words(pack.get("summary") or c.get("topic") or "", 210)
            if len(dek) < 40:
                dek = (dek + " What the evidence shows, and the decision it creates for senior leaders.")[:215]
            from app.services.playbooks import get_playbook

            pb = get_playbook(c.get("category") or "brief")
            sections = []
            for i, k in enumerate(keys):
                spec = pb.section(k)
                ids = [f["id"] for j, f in enumerate(facts) if j % max(1, len(keys)) == i] or ([facts[i % len(facts)]["id"]] if facts else [])
                sections.append({"key": k, "heading": spec.heading if spec else k, "point": f"Make the {spec.heading if spec else k} point from the evidence.", "facts": ids[:3]})
            return {"title": title, "dek": dek, "angle": "", "sections": sections}
        if task == "section" and "pack" in c:
            from app.services.playbooks import get_playbook

            pack = c.get("pack") or {}
            facts = pack.get("key_facts") or []
            keys = get_playbook(c.get("category") or "brief").section_keys
            index = keys.index(c["key"]) if c.get("key") in keys else 0
            wanted = set(c.get("facts") or [])
            mine = [f for f in facts if f["id"] in wanted] or (facts[index % len(facts) : index % len(facts) + 1] if facts else [])
            words = int(c.get("words") or 120)
            paras, used = section_paragraphs(c.get("key", ""), mine[: max(1, math.ceil(words / 40))], words, seed=str(c.get("heading")), index=index)
            return {"paragraphs": paras, "bullets": [], "pull_quote": None, "facts_used": used}
        if task == "takeaway":
            return {"takeaway": "The decision for leaders is whether to commit capital to this shift now or wait for clearer evidence, knowing that waiting also has a cost."}
        if task == "section" and "section" in c:
            sec = c.get("section") or {}
            return {"paragraphs": sec.get("paragraphs") or ["No change."], "bullets": sec.get("bullets") or [], "pull_quote": sec.get("pull_quote"), "changes": ["Kept wording (mock editor)"]}
        if task == "meta":
            title = c.get("title") or ""
            kw = (c.get("keywords") or ["analysis"])[0]
            tt = [fit_title(f"{kw.title()}: {title}"), fit_title(f"{title} — Analysis")]
            dek = c.get("dek") or title
            meta = fit_meta(f"{dek} {c.get('takeaway', '')}")
            return {"title_tags": tt, "meta_descriptions": [meta], "primary_keyword": kw, "secondary_keywords": (c.get("keywords") or [])[1:5]}
        if task == "rubric":
            gates = c.get("gates") or {}
            return {
                "factuality": 5 if gates.get("grounding", True) else 2,
                "structure": 4 if gates.get("structure", True) else 2,
                "executive_value": 4,
                "originality": 4,
                "voice": 4 if gates.get("banned_phrases", True) else 2,
                "readability": 4,
                "exec_questions_answered": ["decision", "second_order"],
                "issues": [],
                "summary": "Mock critic: scores mirror the deterministic gates.",
            }
        if task == "post":
            art = c.get("article") or {}
            title = art.get("title") or "A new analysis"
            body_bits = CONNECTIVES["default"][-8:]
            body = " ".join([art.get("takeaway") or "", *body_bits])
            return {
                "hook": truncate_words(f"{title}.", 200),
                "body": truncate_words(body, 980),
                "leaders_line": "What this means for leaders: the timing of the decision matters as much as the decision itself.",
                "cta": "The full analysis is on The Executive Narrative.",
                "hashtags": ["Leadership", "Strategy"],
            }
        if task == "smoke":
            return {"ok": True, "reply": "pong"}
        return {}

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * 64
            for tok in re.findall(r"[a-z0-9]+", t.lower()):
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                vec[h % 64] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out

    async def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True, provider=self.name, base_url=self.base_url, models=["mock-writer", "mock-fast", "mock-embed"], detail="Mock provider — deterministic extractive output, not a language model", latency_ms=0)
