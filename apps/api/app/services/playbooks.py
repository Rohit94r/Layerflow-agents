"""Category playbooks: routes, required sections and word bands (plan §6.1). Prose guidance lives in
prompts/categories/*.md; this module is the machine-checked part."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SectionSpec:
    key: str
    heading: str
    weight: float = 1.0  # share of the article's word budget
    show_heading: bool = True


@dataclass(frozen=True)
class Playbook:
    key: str
    label: str
    route: str
    purpose: str
    min_words: int
    max_words: int
    sections: tuple[SectionSpec, ...]
    primary_sources: str
    search_intent: str
    color: str = "#1f3a5f"
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def target_words(self) -> int:
        return (self.min_words + self.max_words) // 2

    @property
    def section_keys(self) -> list[str]:
        return [s.key for s in self.sections]

    def section(self, key: str) -> SectionSpec | None:
        return next((s for s in self.sections if s.key == key), None)

    def words_for(self, key: str, target_words: int | None = None) -> int:
        total = target_words or self.target_words
        weights = sum(s.weight for s in self.sections)
        spec = self.section(key)
        if spec is None:
            return 120
        return max(40, int(total * spec.weight / weights))

    def length_band(self, tolerance: float = 0.15) -> tuple[int, int]:
        return int(self.min_words * (1 - tolerance)), int(self.max_words * (1 + tolerance))


PLAYBOOKS: dict[str, Playbook] = {
    "brief": Playbook(
        key="brief",
        label="Brief",
        route="/brief",
        purpose="Short factual deal/investment/M&A news with executive relevance",
        min_words=350,
        max_words=550,
        sections=(
            SectionSpec("lede", "Lede", 0.6, show_heading=False),
            SectionSpec("what_happened", "What happened", 1.2),
            SectionSpec("the_numbers", "The numbers", 1.0),
            SectionSpec("why_it_matters", "Why it matters", 1.2),
            SectionSpec("what_to_watch", "What to watch", 0.8),
        ),
        primary_sources="News + filings",
        search_intent="informational",
        color="#9a3412",
    ),
    "thinking": Playbook(
        key="thinking",
        label="Thinking",
        route="/thinking",
        purpose="Leadership/strategy essay, mental models, trade-offs",
        min_words=900,
        max_words=1300,
        sections=(
            SectionSpec("provocation", "The provocation", 0.8),
            SectionSpec("the_tension", "The tension", 1.0),
            SectionSpec("competing_views", "Two competing views", 1.3),
            SectionSpec("what_leaders_miss", "What most leaders miss", 1.1),
            SectionSpec("practical_implication", "The practical implication", 1.0),
        ),
        primary_sources="Research + judgment",
        search_intent="informational",
        color="#3f6212",
    ),
    "room": Playbook(
        key="room",
        label="Room",
        route="/room",
        purpose="Scenario / decision-room narrative from supplied material",
        min_words=1000,
        max_words=1500,
        sections=(
            SectionSpec("setting", "The setting", 0.9),
            SectionSpec("the_decision", "The decision", 1.0),
            SectionSpec("the_debate", "The debate", 1.4),
            SectionSpec("turning_point", "The turning point", 1.0),
            SectionSpec("what_it_reveals", "What it reveals", 1.0),
        ),
        primary_sources="Transcript/interview input only",
        search_intent="informational",
        color="#6b21a8",
    ),
    "playbook": Playbook(
        key="playbook",
        label="Playbook",
        route="/playbook",
        purpose="Repeatable framework with execution steps",
        min_words=1000,
        max_words=1400,
        sections=(
            SectionSpec("problem", "The problem", 0.8),
            SectionSpec("framework", "The framework", 1.1),
            SectionSpec("steps", "The steps", 1.4),
            SectionSpec("worked_example", "A worked example", 1.1),
            SectionSpec("failure_modes", "Failure modes", 0.8),
            SectionSpec("when_not_to_use", "When not to use it", 0.6),
        ),
        primary_sources="Practitioner sources",
        search_intent="informational",
        color="#0f766e",
    ),
    "decisions": Playbook(
        key="decisions",
        label="Decisions",
        route="/descisions",  # misspelling kept for SEO compatibility with the live site
        purpose="Decision question with options and trade-offs",
        min_words=900,
        max_words=1300,
        sections=(
            SectionSpec("the_question", "The question", 0.8),
            SectionSpec("option_a", "Option A", 1.1),
            SectionSpec("option_b", "Option B", 1.1),
            SectionSpec("decision_criteria", "Decision criteria", 1.0),
            SectionSpec("risks", "The risks", 0.8),
            SectionSpec("who_fits", "Which option fits whom", 0.9),
        ),
        primary_sources="Case evidence",
        search_intent="decision",
        color="#1d4ed8",
    ),
    "deep_dive": Playbook(
        key="deep_dive",
        label="Deep Dive",
        route="/deep_dive",
        purpose="Company analysis: model, moat, numbers, risks",
        min_words=1400,
        max_words=2000,
        sections=(
            SectionSpec("snapshot", "Snapshot", 0.7),
            SectionSpec("business_model", "The business model", 1.0),
            SectionSpec("how_it_makes_money", "How it makes money", 1.0),
            SectionSpec("strategic_moves", "Strategic moves", 1.1),
            SectionSpec("the_numbers", "The numbers", 1.0),
            SectionSpec("moat", "The moat", 0.9),
            SectionSpec("risks", "The risks", 0.9),
            SectionSpec("lessons", "Lessons for leaders", 0.8),
        ),
        primary_sources="Filings, IR, earnings calls",
        search_intent="informational",
        color="#b45309",
    ),
}

CATEGORY_KEYS: tuple[str, ...] = tuple(PLAYBOOKS)
REGIONS: tuple[str, ...] = ("global", "us", "eu", "uk", "india", "mena", "apac", "africa", "latam")


def get_playbook(category: str) -> Playbook:
    try:
        return PLAYBOOKS[category]
    except KeyError as exc:
        raise ValueError(f"Unknown category '{category}'") from exc


def category_from_route(route: str) -> str | None:
    route = "/" + route.strip("/").split("/")[0]
    for pb in PLAYBOOKS.values():
        if pb.route == route:
            return pb.key
    if route == "/decisions":
        return "decisions"
    return None


def public_playbooks() -> list[dict]:
    return [
        {
            "key": p.key,
            "label": p.label,
            "route": p.route,
            "purpose": p.purpose,
            "min_words": p.min_words,
            "max_words": p.max_words,
            "target_words": p.target_words,
            "sections": [{"key": s.key, "heading": s.heading, "show_heading": s.show_heading} for s in p.sections],
            "primary_sources": p.primary_sources,
            "color": p.color,
        }
        for p in PLAYBOOKS.values()
    ]
