"""QA acceptance (plan §5 A6, §18): seeded hallucinated statistics are caught 10/10; known-good articles are
not blocked. Runs the real golden set from evals/cases through the deterministic suite."""

from __future__ import annotations

import pytest

from app.agents.evals import case_sources, load_cases, pack_from, seed_hallucination
from app.core.config import get_settings
from app.services.extractive import extractive_article, research_pack
from app.services.grounding import run_gates, ungrounded_numbers, ungrounded_quotes

SEEDS = [
    "Revenue will grow 347% by the end of the decade.",
    "The deal is worth 97.53 billion dollars.",
    "About 61.7% of executives agree.",
    "It employs 123,457 people.",
    "Margins reached 44.47 percent.",
    "The fund closed at 8.253 billion.",
    "Costs fell 73.9% within months.",
    "Shares jumped 29.31 percent overnight.",
    "Analysts expect 1,239 new stores.",
    "The company spent 3.37 trillion won.",
]


def _good_case():
    cases = [c for c in load_cases(get_settings().evals_dir) if c.get("label") == "good"]
    assert cases, "golden set missing"
    return cases[0]


def _pack_and_article(case):
    sources = [{"index": s["index"], "text": s["excerpt"]} for s in case_sources(case)]
    pack = pack_from(case, research_pack(sources, title=case["input"]["topic"]["title"]))
    art = extractive_article(case["category"], case["input"]["topic"]["title"], pack)
    return pack, art


def test_known_good_article_is_grounded():
    pack, art = _pack_and_article(_good_case())
    assert ungrounded_numbers(art, pack, extra=[_good_case()["input"]["topic"]["title"]]) == []
    assert ungrounded_quotes(art, pack) == []


@pytest.mark.parametrize("seed", SEEDS)
def test_seeded_hallucination_is_caught(seed):
    case = _good_case()
    pack, art = _pack_and_article(case)
    art["sections"][1]["paragraphs"][0] += " " + seed
    gates, issues = run_gates({"article": art}, pack, extra_evidence=[case["input"]["topic"]["title"]])
    grounding = next(g for g in gates if g["gate"] == "grounding")
    assert not grounding["passed"], seed
    assert any(i["code"] == "ungrounded_number" and i["severity"] == "critical" for i in issues)


def test_fabricated_quote_is_caught():
    case = _good_case()
    pack, art = _pack_and_article(case)
    art["sections"][2]["paragraphs"][0] += ' The chairman said "we will double the dividend every single year forever".'
    assert ungrounded_quotes(art, pack)


def test_seed_helper_used_by_eval_suite():
    _pack, art = _pack_and_article(_good_case())
    seeded = seed_hallucination(art)
    assert "847.3" in " ".join(p for s in seeded["sections"] for p in s["paragraphs"])


async def test_deterministic_eval_suite_meets_targets(tenant):
    from app.agents.base import AgentContext, TenantSnapshot
    from app.agents.evals import run_eval
    from app.providers.registry import get_provider
    from tests.conftest import make_fetcher

    fetcher = make_fetcher()
    try:
        ctx = AgentContext(tenant=TenantSnapshot.of(tenant), provider=get_provider(), fetcher=fetcher)
        result = await run_eval(ctx, suite="deterministic")
    finally:
        await fetcher.close()
    scores = result["scores"]
    assert scores["seeded_total"] >= 10
    assert scores["seeded_caught"] == scores["seeded_total"]  # 10/10 (or more) seeded stats caught
    assert scores["good_not_blocked"] >= 0.8 * scores["good_total"]  # good articles not blocked
