"""Contract tests (plan §18.1): agent outputs validate against packages/contracts JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from app.agents.evals import case_sources, load_cases, pack_from
from app.core.config import get_settings
from app.services.extractive import extractive_article, research_pack
from tests.conftest import login

SCHEMAS = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "schemas"


def schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def test_every_category_article_matches_contract():
    cases = [c for c in load_cases(get_settings().evals_dir) if c.get("label") == "good"]
    seen = set()
    for case in cases:
        if case["category"] in seen:
            continue
        seen.add(case["category"])
        sources = [{"index": s["index"], "text": s["excerpt"]} for s in case_sources(case)]
        pack = pack_from(case, research_pack(sources, title=case["input"]["topic"]["title"]))
        art = extractive_article(case["category"], case["input"]["topic"]["title"] + " — what leaders should know", pack)
        art["word_count"] = 400
        jsonschema.validate(art, schema("article.schema.json"))
    assert seen == {"brief", "thinking", "room", "playbook", "decisions", "deep_dive"}


async def test_feed_and_pack_contracts(client, worker):
    authed = await login(client)
    await authed.post("/api/v1/feed/refresh", json={})
    await worker.drain()
    items = (await authed.get("/api/v1/feed")).json()["items"]
    assert items
    for it in items:
        jsonschema.validate(it, schema("feed-item.schema.json"))
    head = next(i for i in items if "Northwind" in i["title"])
    r = await authed.post(f"/api/v1/feed/{head['id']}/promote", json={"auto": False})
    await worker.drain(max_jobs=1)
    art = (await authed.get(f"/api/v1/articles/{r.json()['article']['id']}")).json()
    jsonschema.validate(art["research_pack"]["payload"], schema("research-pack.schema.json"))
