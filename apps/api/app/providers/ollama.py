"""Ollama provider: local open-weight models, no API key (ADR-002)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.providers.base import ModelRequestError, ModelResult, ModelUnavailable, ProviderHealth


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(timeout, connect=10.0), transport=self._transport)

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
            "stream": False,
            "keep_alive": "15m",
            "options": {"temperature": temperature, "num_predict": max_tokens, "repeat_penalty": 1.1},
        }
        if num_ctx:
            body["options"]["num_ctx"] = num_ctx
        if schema is not None:
            body["format"] = schema or "json"
        started = time.perf_counter()
        try:
            async with self._client(timeout_s) as client:
                resp = await client.post("/api/chat", json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.PoolTimeout) as exc:
            raise ModelUnavailable(f"Ollama unreachable at {self.base_url}: {exc.__class__.__name__}") from exc
        latency = int((time.perf_counter() - started) * 1000)
        if resp.status_code == 404:
            raise ModelRequestError(f"Model '{model}' is not available in Ollama. Run: ollama pull {model}")
        if resp.status_code >= 500:
            raise ModelUnavailable(f"Ollama error {resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 400:
            raise ModelRequestError(f"Ollama rejected the request ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        text = (data.get("message") or {}).get("content", "")
        return ModelResult(
            text=text,
            model=model,
            provider=self.name,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            latency_ms=latency,
            raw={k: data.get(k) for k in ("total_duration", "load_duration", "eval_duration", "done_reason")},
        )

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        try:
            async with self._client(120) as client:
                resp = await client.post("/api/embed", json={"model": model, "input": texts})
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"Ollama embed failed: {exc.__class__.__name__}") from exc
        if resp.status_code == 404:
            raise ModelRequestError(f"Embedding model '{model}' not pulled. Run: ollama pull {model}")
        if resp.status_code >= 400:
            raise ModelUnavailable(f"Ollama embed error {resp.status_code}")
        return resp.json().get("embeddings", [])

    async def health(self) -> ProviderHealth:
        started = time.perf_counter()
        try:
            async with self._client(5) as client:
                resp = await client.get("/api/tags")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderHealth(ok=False, provider=self.name, base_url=self.base_url, detail=f"Unreachable: {exc.__class__.__name__}")
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        return ProviderHealth(
            ok=True,
            provider=self.name,
            base_url=self.base_url,
            models=models,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
