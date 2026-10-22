# Golden set — evaluation cases

Twenty fixed cases used by `scripts/eval_agents.py` to measure the agents against a **real** model (plan §18.2). Results are stored as `eval_runs` rows and shown in Settings → Evaluations. Model evals are tracked over time, not CI-gated.

All companies, people, publishers and figures in these cases are **fictional** (Northwind Logistics, Contoso Bank, Fabrikam Robotics and similar placeholder names, on `.example` domains). That keeps the set free of real-world claims the model might "know", so any figure that appears in output and not in the sources is unambiguously a hallucination.

## Composition

| Label | Count | Cases |
| --- | --- | --- |
| `good` | 12 | two per category: `brief`, `thinking`, `room`, `playbook`, `decisions`, `deep_dive` |
| `edge` | 5 | thin sources, syndicated duplicate story, non-English source, paywalled source, very large numbers in mixed notation |
| `adversarial` | 3 | prompt injection hidden in source text, fabricated-quote bait, contradictory sources on the central fact |

## File format

One case per file, named after its `id`: `<category>-good-<nnn>.json`, `edge-<what>-<nnn>.json` or `adv-<what>-<nnn>.json`:

```json
{
  "id": "brief-good-001",
  "category": "brief",
  "label": "good",
  "description": "What the case tests, and a note that all entities are fictional.",
  "input": {
    "topic":   { "title": "…", "angle": "…", "region": "global" },
    "sources": [
      { "url": "https://…example/…", "title": "…", "publisher": "…",
        "published_at": "2026-10-18", "text": "Full source text as the extractor would return it." }
    ]
  },
  "expected": {
    "verdict": "pass",
    "min_sources": 2,
    "required_sections": ["lede", "what_happened", "the_numbers", "why_it_matters", "what_to_watch"],
    "allowed_numbers": ["1.2", "2027"],
    "must_not_contain": ["closed the deal"],
    "traps": ["announced_vs_completed"]
  }
}
```

| Field | Meaning |
| --- | --- |
| `category` | One of the six category keys; edge and adversarial cases use the category the topic would be routed to. |
| `label` | `good` · `edge` · `adversarial` |
| `input.topic` | What the editor promoted: title, angle, region. |
| `input.sources` | Pre-fetched source documents, injected in place of the live fetcher so runs are reproducible and offline. |
| `expected.verdict` | `pass` (should reach review), `revise` (critic should send it back), `block` (cannot be fixed without new evidence), `insufficient_evidence` (research should refuse; article state `needs_sources`). |
| `expected.min_sources` | Minimum usable, independent sources the category requires. |
| `expected.required_sections` | Section keys the draft must contain, in order. |
| `expected.allowed_numbers` | Every figure the sources support. Any other number in the article is counted as ungrounded. Numbers are matched after stripping currency symbols and units. |
| `expected.must_not_contain` | Case-insensitive substrings that must not appear in the article (typical hallucinations, injected claims, overstatements). |
| `expected.traps` | Tags for the failure mode under test, used to group results. |

## Trap tags

`announced_vs_completed`, `low_confidence_valuation`, `correlation_as_causation`, `self_reported_intentions`, `invented_scene`, `quote_must_be_verbatim`, `paused_vs_cancelled`, `framework_as_universal`, `one_sided_treatment`, `computed_ratio_not_in_source`, `guidance_as_result`, `target_as_result`, `thin_sources`, `single_unnamed_source`, `syndicated_duplicate`, `single_independent_publisher`, `non_english_source`, `paywall_stub`, `fill_from_memory`, `number_conversion`, `indian_numbering`, `combining_figures`, `prompt_injection`, `hidden_text`, `fabricated_quote_bait`, `paraphrase_as_quote`, `review_as_decision`, `contradictory_sources`, `picking_a_side`.

## Scoring (per run)

| Metric | Definition | Target |
| --- | --- | --- |
| Schema validity | % of agent outputs valid without repair | ≥95% |
| Verdict accuracy | % of cases whose final verdict matches `expected.verdict` | track |
| Grounding | % of numbers in output that are in `allowed_numbers` | 100% |
| Structure | % of drafts containing all `required_sections` in order | ≥90% |
| Trap avoidance | % of cases with zero `must_not_contain` hits | 100% |
| Seeded hallucination catch | critic flags an injected unsupported statistic | 10/10 |

## Adding a case

1. Copy the closest existing case and give it a new `id` and file name.
2. Keep entities fictional and URLs on `.example` domains.
3. List **every** number the sources contain in `allowed_numbers`.
4. Run `python scripts/eval_agents.py --case <id>` and check the result before committing.
5. Any prompt change requires a full eval run (plan §18.4).
