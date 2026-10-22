# ADR-004: Human approval gate before publishing

- **Status:** Accepted
- **Date:** 2026-10-20
- **Deciders:** Rohit Jadhav, with the TEN editor (mentor)

## Context

The engine can technically publish without a person in the loop. But local models can still produce plausible errors, sources can be wrong or manipulated, and the content appears under a brand whose credibility with executives is the asset. Factual accuracy cannot be guaranteed by software (plan §24). The mentor explicitly asked for control.

## Decision

1. **Nothing publishes without an explicit human approval** recorded in `review_actions` with the user, time and optional reason.
2. Automated quality gates (schema, grounding, structure, length, banned phrases, duplication, SEO completeness, critic score) run before the review queue. They reduce what reaches a human; they do not replace the human.
3. Review actions are `approve`, `reject` (with a required reason; article archived) and `request_revision` (with an instruction; article returns to the pipeline).
4. An owner may send an article that failed automated gates to review with a written reason. This override is recorded in the audit log; it never bypasses human approval.
5. Approval is per version. Editing an approved or published article creates a new version that must be approved again before it is re-published.
6. The scheduler and publisher refuse any article whose current version is not approved; this is enforced in code and covered by tests, not just by the UI.
7. Roles: `owner` (everything), `editor` (content and review), `reviewer` (review and scheduling only).

## Consequences

**Positive**

- Brand risk sits with an accountable person, not a model.
- Every published piece has a named approver and a reasoned history.
- Rejection reasons become training data for prompts and the style profile.

**Negative**

- Throughput is capped by reviewer time.
- Demo flows include a manual step (by design — it is part of the pitch).

## Alternatives considered

| Option | Why not |
| --- | --- |
| Fully autonomous publishing | Possible technically, inadvisable; one fabricated quote would cost more than the automation saves. |
| Auto-publish when the critic passes | The critic is a model too; it reduces risk but cannot be the final authority. |
| Post-publication review | Errors would already be public and indexed. |
