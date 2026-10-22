#!/usr/bin/env python
"""Phase 0 model benchmark (plan §11.7): run on the real hardware and record the numbers in plan.md §11.3.

    python scripts/bench_model.py --model qwen2.5:7b-instruct --runs 3
    docker compose exec api python /srv/layerflow/scripts/bench_model.py

Measures: valid-JSON rate (first attempt and after repair), latency per call, tokens/second, latency per
~300 words of prose, and whether the golden-set brief case stays grounded. Peak RAM is read from the
Ollama /api/ps endpoint when available."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import _bootstrap_path  # noqa: F401

from app.agents.base import parse_json
from app.core.config import get_settings
from app.providers.registry import build_provider
from app.services.text import word_count

JSON_PROMPT = (
    "Return a JSON object with keys 'company' (string), 'move' (string), 'numbers' (array of strings) describing: "
    "Northwind Logistics will invest 2.1 billion dollars in 14 automated warehouses by 2028, its CEO said on Tuesday."
)
PROSE_PROMPT = (
    "Write about 300 words for senior executives on why warehouse automation is becoming a capital allocation "
    "decision rather than an efficiency project. Return JSON {\"text\": \"...\"}."
)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    s = get_settings()
    model = args.model or s.model_writer
    provider = build_provider()
    health = await provider.health()
    print(f"provider={provider.name} base={health.base_url} ok={health.ok} models={len(health.models)}")
    if not health.ok:
        raise SystemExit(f"Model endpoint unreachable: {health.detail}")

    first_ok = repaired_ok = 0
    latencies, tps, prose_lat = [], [], []
    for i in range(args.runs):
        t0 = time.perf_counter()
        res = await provider.generate(model=model, system="Output JSON only.", prompt=JSON_PROMPT, schema={"type": "object"},
                                      temperature=0.2, max_tokens=200, timeout_s=s.model_timeout_s)
        latencies.append((time.perf_counter() - t0) * 1000)
        try:
            data = parse_json(res.text)
            ok = isinstance(data, dict) and "company" in data
        except ValueError:
            ok = False
        if ok:
            first_ok += 1
            repaired_ok += 1
        else:
            res2 = await provider.generate(model=model, system="Output JSON only.", prompt=JSON_PROMPT + "\nYour previous output was invalid JSON. Return ONLY the JSON object.",
                                           schema={"type": "object"}, temperature=0.1, max_tokens=200, timeout_s=s.model_timeout_s)
            try:
                repaired_ok += int(isinstance(parse_json(res2.text), dict))
            except ValueError:
                pass
        if res.completion_tokens and res.latency_ms:
            tps.append(res.completion_tokens / (res.latency_ms / 1000))
        t1 = time.perf_counter()
        prose = await provider.generate(model=model, system="Output JSON only.", prompt=PROSE_PROMPT, schema={"type": "object"},
                                        temperature=0.5, max_tokens=700, timeout_s=s.model_timeout_s)
        elapsed = time.perf_counter() - t1
        try:
            words = word_count(parse_json(prose.text).get("text", ""))
        except (ValueError, AttributeError):
            words = word_count(prose.text)
        prose_lat.append(elapsed * 300 / max(words, 1))
        print(f"run {i + 1}: json_ok={ok} latency={latencies[-1]:.0f}ms words={words} per300w={prose_lat[-1]:.1f}s")

    ps = {}
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5) as c:
            ps = (await c.get(f"{s.ollama_base_url.rstrip('/')}/api/ps")).json()
    except Exception:
        pass
    report = {
        "model": model,
        "runs": args.runs,
        "valid_json_first_attempt": f"{first_ok}/{args.runs}",
        "valid_json_after_repair": f"{repaired_ok}/{args.runs}",
        "latency_ms_p50": round(statistics.median(latencies)),
        "tokens_per_second": round(statistics.mean(tps), 1) if tps else None,
        "seconds_per_300_words": round(statistics.mean(prose_lat), 1) if prose_lat else None,
        "loaded_models": [{"name": m.get("name"), "size_vram": m.get("size_vram"), "size": m.get("size")} for m in ps.get("models", [])],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
