#!/usr/bin/env python
"""Golden-set evaluation (plan §18) and style calibration (plan §6.3).

    python scripts/eval_agents.py --suite deterministic      # gates only, no model, seconds
    python scripts/eval_agents.py --suite critic             # + critic model rubric
    python scripts/eval_agents.py --suite pipeline --case brief-good-001
    python scripts/eval_agents.py --style-profile            # evals/style/{good,bad}/*.md -> style_profile.json

Results are written to eval_runs (visible in Settings → Evaluations)."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
from pathlib import Path

import _bootstrap_path  # noqa: F401

from app.core.config import get_settings
from app.core.db import dispose_engine
from app.services.text import readability, sentences, word_count


def _strip_front_matter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    import yaml

    return yaml.safe_load(m.group(1)) or {}, text[m.end() :]


def profile_dir(path: Path) -> dict:
    docs = []
    for p in sorted(path.glob("*.md")):
        meta, body = _strip_front_matter(p.read_text(encoding="utf-8"))
        docs.append((meta, body))
    if not docs:
        return {}
    lens, paras, heads, openers, closers = [], [], [], [], []
    for _meta, body in docs:
        blocks = [b.strip() for b in body.split("\n\n") if b.strip()]
        text_blocks = [b for b in blocks if not b.startswith("#")]
        heads.append(sum(1 for b in blocks if b.startswith("#")))
        for b in text_blocks:
            ss = sentences(b)
            paras.append(len(ss))
            lens.extend(word_count(s) for s in ss)
        if text_blocks:
            first = sentences(text_blocks[0])[:1]
            last = sentences(text_blocks[-1])[-1:]
            openers.append(first[0][:160] if first else "")
            closers.append(last[0][:160] if last else "")
    rd = readability("\n\n".join(b for _m, b in docs))
    return {
        "articles": len(docs),
        "sentence_length": {
            "mean": round(statistics.mean(lens), 1) if lens else None,
            "median": statistics.median(lens) if lens else None,
            "p90": sorted(lens)[int(len(lens) * 0.9)] if lens else None,
        },
        "sentences_per_paragraph": round(statistics.mean(paras), 1) if paras else None,
        "headings_per_article": round(statistics.mean(heads), 1) if heads else None,
        "flesch": rd["flesch"],
        "opening_moves": openers[:6],
        "closing_moves": closers[:6],
    }


def style_profile() -> None:
    root = get_settings().evals_dir / "style"
    good = profile_dir(root / "good")
    bad = profile_dir(root / "bad")
    if not good:
        raise SystemExit(f"No mentor-approved samples in {root / 'good'} (see evals/style/README.md)")
    out = {"good": good, "not_our_voice": bad or None, "targets": {
        "avg_sentence_words": good["sentence_length"]["mean"],
        "sentences_per_paragraph": good["sentences_per_paragraph"],
        "headings_per_article": good["headings_per_article"],
        "flesch": good["flesch"],
    }}
    (root / "style_profile.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out["targets"], indent=2))
    print(f"wrote {root / 'style_profile.json'} — the writer prompt now includes these measured targets")


async def run_suite(suite: str, case_ids: list[str] | None) -> None:
    from app.agents.base import AgentContext, TenantSnapshot
    from app.agents.evals import run_eval
    from app.cli import ensure_tenant
    from app.providers.registry import get_provider
    from app.services.fetcher import Fetcher

    try:
        tenant = await ensure_tenant()
        async with Fetcher() as fetcher:
            ctx = AgentContext(tenant=TenantSnapshot.of(tenant), provider=get_provider(), fetcher=fetcher)
            result = await run_eval(ctx, suite=suite, case_ids=case_ids)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await dispose_engine()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", choices=["deterministic", "critic", "pipeline"], default="deterministic")
    ap.add_argument("--case", action="append", dest="cases", help="limit to one case id (repeatable)")
    ap.add_argument("--style-profile", action="store_true")
    args = ap.parse_args()
    if args.style_profile:
        style_profile()
        return
    asyncio.run(run_suite(args.suite, args.cases))


if __name__ == "__main__":
    main()
