"""Optional OpenAI-compatible provider (free-tier or self-hosted endpoint). Never required (plan §2.1 tier C)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.providers.base import ModelRequestError, ModelResult, ModelUnavailable, ProviderHealth


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str = "", *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

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
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            body["response_format"] = {"type": "json_object"}
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_s, transport=self._transport) as client:
                resp = await client.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"Endpoint unreachable: {exc.__class__.__name__}") from exc
        if resp.status_code in (429, 500, 502, 503, 504):
            raise ModelUnavailable(f"Endpoint busy ({resp.status_code})")
        if resp.status_code >= 400:
            raise ModelRequestError(f"Endpoint rejected request ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        usage = data.get("usage") or {}
        return ModelResult(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=120, transport=self._transport) as client:
                resp = await client.post(f"{self.base_url}/embeddings", json={"model": model, "input": texts}, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ModelUnavailable(str(exc)) from exc
        if resp.status_code >= 400:
            raise ModelRequestError(f"Embeddings rejected ({resp.status_code})")
        return [d["embedding"] for d in resp.json().get("data", [])]

    async def health(self) -> ProviderHealth:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5, transport=self._transport) as client:
                resp = await client.get(f"{self.base_url}/models", headers=self._headers())
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderHealth(ok=False, provider=self.name, base_url=self.base_url, detail=str(exc)[:200])
        models = [m.get("id", "") for m in resp.json().get("data", [])]
        return ProviderHealth(ok=True, provider=self.name, base_url=self.base_url, models=models, latency_ms=int((time.perf_counter() - started) * 1000))
