"""Structured-output plumbing: tolerant JSON parsing, schema flattening, repair loop."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from app.agents.base import AgentContext, AgentOutputError, TenantSnapshot, inline_refs, parse_json, structured
from app.agents.writer import OutlineOut
from app.providers.base import ModelResult


def test_parse_json_tolerates_fences_and_chatter():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! Here it is: {"a": {"b": "x}"}} hope that helps') == {"a": {"b": "x}"}}
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_inline_refs_keeps_title_property():
    flat = inline_refs(OutlineOut.model_json_schema())
    assert "title" in flat["properties"] and flat["properties"]["title"]["type"] == "string"
    assert "$defs" not in json.dumps(flat) and "$ref" not in json.dumps(flat)
    assert "key" in flat["properties"]["sections"]["items"]["properties"]


class Out(BaseModel):
    value: int


class FlakyProvider:
    name = "flaky"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    async def generate(self, **kw):
        self.prompts.append(kw["prompt"])
        return ModelResult(text=self.outputs.pop(0), model=kw["model"], provider=self.name, latency_ms=1)

    async def health(self):  # pragma: no cover
        raise NotImplementedError


async def test_repair_loop_then_success(tenant):
    from tests.conftest import make_fetcher

    prov = FlakyProvider(["not json", '{"value": "x"}', '{"value": 7}'])
    f = make_fetcher()
    try:
        ctx = AgentContext(tenant=TenantSnapshot.of(tenant), provider=prov, fetcher=f)
        out, run_id = await structured(ctx, agent="writer", task="t", system="s", prompt="p", schema=Out)
    finally:
        await f.close()
    assert out.value == 7 and run_id
    assert "FAILED VALIDATION" in prov.prompts[1] and "value" in prov.prompts[2]


async def test_repair_loop_gives_up(tenant):
    from tests.conftest import make_fetcher

    prov = FlakyProvider(["{}", "{}", "{}"])
    f = make_fetcher()
    try:
        ctx = AgentContext(tenant=TenantSnapshot.of(tenant), provider=prov, fetcher=f)
        with pytest.raises(AgentOutputError):
            await structured(ctx, agent="writer", task="t", system="s", prompt="p", schema=Out, max_repairs=2)
    finally:
        await f.close()
