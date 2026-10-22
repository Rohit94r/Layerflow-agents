# ADR-002: Ollama as the default model provider, behind a provider interface

- **Status:** Accepted
- **Date:** 2026-10-20
- **Deciders:** Rohit Jadhav

## Context

The brief's hard constraint is **no paid AI API keys**. Generation, editing, classification and critique must run on open-weight models. The target is a CPU-only VPS (8 GB recommended), with the option of running the model on a different machine that has more RAM or a GPU. Model quality and speed will need to change over time — a 7B model today, a 14B/32B or GPU-hosted model later, perhaps a free-tier API as an optional fallback.

## Decision

1. Serve models with **Ollama** by default (`MODEL_PROVIDER=ollama`, `OLLAMA_BASE_URL`).
2. Agents never call Ollama directly. They receive an object implementing a `ModelProvider` interface:
   - `generate(model, system, prompt, schema, temperature, max_tokens, timeout_s) → ModelResult`
   - `embed(model, texts) → vectors`
   - `health() → ProviderHealth`
3. Ship three implementations:
   - `OllamaProvider` — default, keyless, local or over Tailscale.
   - `OpenAICompatProvider` — optional; any OpenAI-compatible endpoint (self-hosted vLLM/llama.cpp server, or a free-tier API). Never required.
   - `MockProvider` — deterministic, for tests and UI work without a model. Clearly labelled in the dashboard whenever it is active.
4. Model per agent, temperature and context length are tenant settings, editable from Settings → Models.
5. One model loaded at a time on CPU hosts (`OLLAMA_MAX_LOADED_MODELS=1`, `MODEL_CONCURRENCY=1`).

## Consequences

**Positive**

- Zero marginal cost per article; no external dependency for the demo.
- Swapping model size or host is a configuration change, not a code change.
- Split hosting (app on VPS, model on a bigger box) changes only a base URL.
- Tests run without a model.

**Negative**

- CPU inference is slow (10–25 minutes per long article on 8 GB); the UI must be asynchronous and stream progress.
- Small local models drift on JSON; we need schema prompting, `format: json`, validation and a repair loop.
- Quality depends on model choice, which must be benchmarked on the real hardware (`scripts/bench_model.py`).

## Alternatives considered

| Option | Why not |
| --- | --- |
| Hosted paid APIs | Violates the no-paid-key constraint. |
| vLLM | Needs a GPU; heavier to operate on a CPU VPS. |
| llama.cpp server directly | Workable (and reachable through `OpenAICompatProvider`), but more manual model management than Ollama. |
| Hard-coding Ollama calls in agents | Makes every future model change a rewrite. |
