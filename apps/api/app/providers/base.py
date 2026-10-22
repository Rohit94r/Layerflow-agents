"""Model provider interface (plan §11.1). Agents receive a provider; they never import one directly."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ModelResult:
    text: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderHealth:
    ok: bool
    provider: str
    base_url: str | None = None
    models: list[str] = field(default_factory=list)
    detail: str | None = None
    latency_ms: int | None = None


class ModelUnavailable(Exception):
    """Endpoint down, timed out or overloaded: the job should retry with backoff."""


class ModelRequestError(Exception):
    """The request itself is wrong (unknown model, bad params): retrying will not help."""


class ModelProvider(Protocol):
    name: str

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
    ) -> ModelResult: ...

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]: ...

    async def health(self) -> ProviderHealth: ...
