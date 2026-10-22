# Style calibration samples

The mentor's voice is the product (plan §6.3). Instead of fine-tuning, LayerFlow measures the voice from real examples and injects the measured targets into the writer prompt.

This folder is intentionally empty until real, mentor-approved articles are added. **Do not add invented or AI-written samples** — they would calibrate the writer to the wrong voice.

## What to add

| Folder | What goes in it | How many |
| --- | --- | --- |
| `good/` | Articles the mentor marks as "this is our voice" | 8–12 |
| `bad/` | Articles the mentor marks as "not our voice" (published or draft) | about 5 |

One article per Markdown file. Use H2 (`##`) for section headings so heading patterns can be measured. Front-matter:

```markdown
---
title: The full article headline
category: brief          # brief | thinking | room | playbook | decisions | deep_dive
url: https://theexecutivenarrative.com/brief/the-article-slug
---

Article body in Markdown…
```

Spread the `good/` samples across categories where possible — at least one each for Brief and Deep Dive, which are the demo-critical formats.

## Building the profile

```bash
python scripts/eval_agents.py --style-profile
```

This reads `good/` and `bad/` and writes `evals/style/style_profile.json` with:

- sentence-length distribution (mean, median, p90) per category,
- paragraph length in sentences,
- heading count and heading length patterns,
- the opening move (first-sentence shape: actor + action + number, question, scene) and closing move (decision, metric, test, summary),
- frequent preferred terms, and terms that appear in `bad/` but not in `good/`.

The writer prompt receives the measured targets from `style_profile.json` alongside the persona (`prompts/persona/ten.md`).

## Calibration loop

1. Mentor marks 5+ articles as good and 5 as not our voice.
2. Build the profile (above).
3. Re-run the golden set (`python scripts/eval_agents.py`) and compare rubric scores — especially `voice` — before and after.
4. Keep the profile only if scores improve; profile changes are versioned in git like prompts.
