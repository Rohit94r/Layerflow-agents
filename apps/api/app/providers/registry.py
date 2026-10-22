"""Provider selection + circuit breaker. A dead endpoint fails fast for a cool-down instead of hanging every job."""

from __future__ import annotations

import time
from typing import Any

from app.core.config import get_settings
from app.providers.base import ModelProvider, ModelResult, ModelUnavailable, ProviderHealth


class CircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown_s: float = 60.0) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.failures = 0
        self.opened_at: float | None = None

    def check(self) -> None:
        if self.opened_at is not None:
            if time.monotonic() - self.opened_at < self.cooldown_s:
                raise ModelUnavailable("Model endpoint circuit is open after repeated failures; retrying later")
            self.opened_at = None
            self.failures = self.threshold - 1  # half-open: one more failure re-opens

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


class GuardedProvider:
    """Wraps a provider with the circuit breaker; same interface."""

    def __init__(self, inner: ModelProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.breaker = CircuitBreaker()

    @property
    def base_url(self) -> str | None:
        return getattr(self.inner, "base_url", None)

    async def generate(self, **kwargs: Any) -> ModelResult:
        self.breaker.check()
        try:
            result = await self.inner.generate(**kwargs)
        except ModelUnavailable:
            self.breaker.failure()
            raise
        self.breaker.success()
        return result

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        self.breaker.check()
        try:
            out = await self.inner.embed(model=model, texts=texts)
        except ModelUnavailable:
            self.breaker.failure()
            raise
        self.breaker.success()
        return out

    async def health(self) -> ProviderHealth:
        return await self.inner.health()


_provider: GuardedProvider | None = None


def build_provider(name: str | None = None) -> GuardedProvider:
    s = get_settings()
    name = (name or s.model_provider).lower()
    if name == "mock":
        from app.providers.mock import MockProvider

        inner: ModelProvider = MockProvider()
    elif name == "openai_compat":
        from app.providers.openai_compat import OpenAICompatProvider

        if not s.openai_compat_base_url:
            raise RuntimeError("MODEL_PROVIDER=openai_compat requires OPENAI_COMPAT_BASE_URL")
        inner = OpenAICompatProvider(s.openai_compat_base_url, s.openai_compat_api_key)
    else:
        from app.providers.ollama import OllamaProvider

        inner = OllamaProvider(s.ollama_base_url)
    return GuardedProvider(inner)


def get_provider() -> GuardedProvider:
    global _provider
    if _provider is None:
        _provider = build_provider()
    return _provider


def set_provider(provider: Any) -> None:
    """Used by tests and the CLI to inject a provider."""
    global _provider
    _provider = provider if isinstance(provider, GuardedProvider) or provider is None else GuardedProvider(provider)
