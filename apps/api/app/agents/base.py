"""Shared agent plumbing: the job context and the structured-output loop (plan §11.5):
schema-constrained prompt -> format constraint -> validate + repair (max 2) -> deterministic fallbacks by callers.
Every model call is recorded in model_runs."""

from __future__ import annotations

import copy
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.db import session_factory
from app.models import ModelRun, Tenant
from app.providers.base import ModelRequestError, ModelUnavailable
from app.providers.registry import GuardedProvider
from app.queue.jobs import PermanentError, RetryableError, heartbeat, log_event
from app.services.fetcher import Fetcher
from app.services.tenant_settings import agent_model, effective
from app.services.text import sha256

T = TypeVar("T", bound=BaseModel)


class AgentOutputError(RetryableError):
    """Model output still invalid after the repair loop."""


class InsufficientEvidence(PermanentError):
    """Research found too few usable sources; the article moves to needs_sources (not an error)."""


@dataclass
class TenantSnapshot:
    id: uuid.UUID
    slug: str
    name: str
    timezone: str
    settings: dict[str, Any]

    @classmethod
    def of(cls, t: Tenant) -> TenantSnapshot:
        return cls(id=t.id, slug=t.slug, name=t.name, timezone=t.timezone, settings=effective(t.settings))


@dataclass
class AgentContext:
    tenant: TenantSnapshot
    provider: GuardedProvider
    fetcher: Fetcher
    job_id: uuid.UUID | None = None
    article_id: uuid.UUID | None = None
    worker_id: str | None = None
    settings: Settings = field(default_factory=get_settings)
    _last_beat: float = field(default=0.0)

    async def log(self, message: str, level: str = "info", **data: Any) -> None:
        await log_event(self.tenant.id, message, job_id=self.job_id, article_id=self.article_id, level=level, data=data or None)

    async def beat(self) -> None:
        if self.job_id and self.worker_id and time.monotonic() - self._last_beat > self.settings.worker_heartbeat_s:
            self._last_beat = time.monotonic()
            await heartbeat(self.job_id, self.worker_id)

    def model_config(self, agent: str) -> dict[str, Any]:
        return agent_model(self.tenant.settings, agent)


def parse_json(text: str) -> Any:
    """Tolerant JSON parse: strips code fences / chatter around the first JSON object."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise json.JSONDecodeError("No JSON object found", t, 0)
    depth, in_str, esc = 0, False, False
    opener = t[start]
    closer = "}" if opener == "{" else "]"
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return json.loads(t[start : i + 1])
    raise json.JSONDecodeError("Unterminated JSON object", t, start)


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve $ref/$defs so small-model grammar constraints get a flat schema."""
    defs = schema.get("$defs", {})

    def resolve(node: Any, depth: int = 0) -> Any:
        if depth > 12:
            return {}
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return resolve(copy.deepcopy(defs.get(name, {})), depth + 1)
            # Drop `title` annotations (strings) but keep properties that happen to be called "title" (dicts).
            return {
                k: resolve(v, depth + 1)
                for k, v in node.items()
                if k != "$defs" and not (k == "title" and isinstance(v, str))
            }
        if isinstance(node, list):
            return [resolve(x, depth + 1) for x in node]
        return node

    return resolve(schema)


def compact_schema(schema: dict[str, Any]) -> str:
    return json.dumps(schema, separators=(",", ":"))


async def record_run(
    ctx: AgentContext,
    *,
    agent: str,
    model: str,
    params: dict[str, Any],
    input_hash: str,
    output: Any,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int,
    repairs: int,
    error: str | None,
    prompt_version: str | None,
) -> uuid.UUID:
    run_id = uuid.uuid4()
    out = output if isinstance(output, dict) else {"value": output}
    async with session_factory()() as db:
        db.add(
            ModelRun(
                id=run_id,
                tenant_id=ctx.tenant.id,
                agent=agent,
                job_id=ctx.job_id,
                article_id=ctx.article_id,
                prompt_version=prompt_version,
                model=model,
                provider=ctx.provider.name,
                params=params,
                input_hash=input_hash,
                output_hash=sha256(json.dumps(out, sort_keys=True, default=str)) if out else None,
                output=out,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                repairs=repairs,
                error=error,
            )
        )
        await db.commit()
    return run_id


async def structured(
    ctx: AgentContext,
    *,
    agent: str,
    task: str,
    system: str,
    prompt: str,
    schema: type[T],
    context: dict[str, Any] | None = None,
    prompt_version: str | None = None,
    validate: Callable[[T], list[str]] | None = None,
    max_repairs: int = 2,
    overrides: dict[str, Any] | None = None,
) -> tuple[T, uuid.UUID]:
    cfg = {**ctx.model_config(agent), **(overrides or {})}
    json_schema = inline_refs(schema.model_json_schema())
    schema_block = (
        "\n\nOUTPUT FORMAT\nReturn ONLY one JSON object (no prose, no code fences) that validates against this JSON Schema:\n"
        + compact_schema(json_schema)
    )
    base_prompt = prompt + schema_block
    current = base_prompt
    params = {k: cfg.get(k) for k in ("temperature", "max_tokens", "num_ctx")}
    input_hash = sha256(system + "\n" + prompt)
    total_latency, last_err, last_text = 0, "", ""
    prompt_tokens = completion_tokens = None
    for attempt in range(max_repairs + 1):
        await ctx.beat()
        try:
            result = await ctx.provider.generate(
                model=cfg["model"],
                system=system,
                prompt=current,
                schema=json_schema,
                temperature=float(cfg.get("temperature", 0.4)),
                max_tokens=int(cfg.get("max_tokens", 1200)),
                timeout_s=ctx.settings.model_timeout_s,
                num_ctx=cfg.get("num_ctx"),
                task=task,
                context=context,
            )
        except ModelUnavailable as exc:
            await record_run(
                ctx, agent=f"{agent}.{task}", model=cfg["model"], params=params, input_hash=input_hash, output=None,
                prompt_tokens=None, completion_tokens=None, latency_ms=total_latency, repairs=attempt, error=str(exc),
                prompt_version=prompt_version,
            )
            raise RetryableError(f"Model unavailable: {exc}") from exc
        except ModelRequestError as exc:
            await record_run(
                ctx, agent=f"{agent}.{task}", model=cfg["model"], params=params, input_hash=input_hash, output=None,
                prompt_tokens=None, completion_tokens=None, latency_ms=total_latency, repairs=attempt, error=str(exc),
                prompt_version=prompt_version,
            )
            raise PermanentError(str(exc)) from exc
        total_latency += result.latency_ms
        prompt_tokens = (prompt_tokens or 0) + (result.prompt_tokens or 0)
        completion_tokens = (completion_tokens or 0) + (result.completion_tokens or 0)
        last_text = result.text
        try:
            data = parse_json(result.text)
            obj = schema.model_validate(data)
            problems = validate(obj) if validate else []
            if problems:
                raise ValueError("; ".join(problems))
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
            last_err = _short_error(exc)
            current = (
                base_prompt
                + "\n\nYOUR PREVIOUS OUTPUT FAILED VALIDATION:\n"
                + last_err
                + "\nFix exactly these problems and return ONLY the corrected JSON object."
            )
            continue
        run_id = await record_run(
            ctx, agent=f"{agent}.{task}", model=cfg["model"], params=params, input_hash=input_hash,
            output=obj.model_dump(), prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            latency_ms=total_latency, repairs=attempt, error=None, prompt_version=prompt_version,
        )
        return obj, run_id
    await record_run(
        ctx, agent=f"{agent}.{task}", model=cfg["model"], params=params, input_hash=input_hash,
        output={"raw": last_text[:4000]}, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        latency_ms=total_latency, repairs=max_repairs, error=last_err, prompt_version=prompt_version,
    )
    raise AgentOutputError(f"{agent}.{task}: output invalid after {max_repairs} repairs: {last_err[:300]}", retry_after_s=5)


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for e in exc.errors()[:8]:
            loc = ".".join(str(x) for x in e.get("loc", []))
            parts.append(f"- {loc or 'root'}: {e.get('msg')}")
        return "\n".join(parts)
    return str(exc)[:800]
