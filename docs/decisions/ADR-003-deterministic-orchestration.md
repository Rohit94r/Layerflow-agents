# ADR-003: Deterministic orchestration; LLM only where judgment is needed

- **Status:** Accepted
- **Date:** 2026-10-20
- **Deciders:** Rohit Jadhav

## Context

Agent demos often let an LLM decide what to do next: which tool to call, when to stop, whether to retry. That makes behaviour hard to predict, hard to explain to a non-technical owner and hard to test. This engine publishes under a real brand to senior executives; predictability matters more than flexibility. It also runs on slow CPU inference, so every unnecessary model call costs minutes.

## Decision

1. The orchestrator (A0) is plain Python with **no LLM**. It enforces an explicit article state machine (`queued → researching → drafting → editing → seo → qa → in_review → approved → scheduled → publishing → published`, with `needs_sources`, `failed` and `archived` branches). Illegal transitions raise and are covered by tests.
2. Budgets are hard-coded and configurable: max 3 attempts per job, max 2 critic-driven revision loops, a timeout per stage, a circuit breaker when the model endpoint is down.
3. **Rules before models.** Anything a rule can do is done by a rule: category routing (with the LLM only overriding at high confidence, reason logged), URL canonicalisation, dedupe, scoring, slug generation, word counts, heading checks, banned-phrase scans, number grounding, link validation, length limits.
4. Models are used for judgment and prose: classification at the margin, research synthesis, writing, editing, SEO phrasing, critique, social copy.
5. Agents cannot call tools beyond what they are explicitly given; model output never triggers actions directly.
6. Every model call is logged in `model_runs` (prompt version, model, parameters, latency, repairs, output hash).

## Consequences

**Positive**

- Behaviour is explainable: the mentor can see exactly why an article is in a state.
- Deterministic checks are fast, testable and cannot hallucinate.
- Failures are localised to a stage and retried surgically.
- Fewer model calls on slow hardware.

**Negative**

- Less "autonomous" in appearance; new behaviours require code, not a prompt tweak.
- Rules need maintenance (for example, new business-signal keywords).

## Alternatives considered

| Option | Why not |
| --- | --- |
| LLM planner/agent loop (ReAct-style) | Unpredictable paths, runaway loops, hard to test and to explain; slow on CPU. |
| Single mega-prompt per article | No stage visibility, no surgical retries, poor quality on small models. |
| Workflow engine (Temporal, Airflow) | Heavy for the scale; another service to run. The table queue plus a small state machine covers the need. |
