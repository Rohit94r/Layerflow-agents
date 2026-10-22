"""Article state machine (plan §7.2). Illegal transitions raise; every transition is audited by the caller."""

from __future__ import annotations

ARTICLE_STATES = (
    "queued",
    "researching",
    "drafting",
    "editing",
    "seo",
    "qa",
    "in_review",
    "approved",
    "scheduled",
    "publishing",
    "published",
    "archived",
    "needs_sources",
    "failed",
)

IN_FLIGHT = frozenset({"researching", "drafting", "editing", "seo", "qa", "publishing"})
TERMINAL_FOR_EDITS = frozenset({"scheduled", "publishing"})

# stage name (what a user/agent runs) -> article state while that stage runs
STAGE_STATE = {
    "research": "researching",
    "write": "drafting",
    "edit": "editing",
    "seo": "seo",
    "qa": "qa",
}
STAGE_ORDER = ("research", "write", "edit", "seo", "qa")

_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"researching", "archived", "failed"}),
    "researching": frozenset({"drafting", "needs_sources", "failed", "queued"}),
    "drafting": frozenset({"editing", "failed", "researching"}),
    "editing": frozenset({"seo", "failed", "drafting"}),
    "seo": frozenset({"qa", "failed", "editing"}),
    # qa -> drafting/editing is the revise loop (max 2, enforced by the orchestrator)
    "qa": frozenset({"in_review", "drafting", "editing", "seo", "needs_sources", "failed"}),
    "in_review": frozenset({"approved", "archived", "drafting", "editing", "seo", "qa", "researching"}),
    "approved": frozenset({"scheduled", "in_review", "drafting", "editing", "seo", "qa", "archived"}),
    "scheduled": frozenset({"publishing", "approved"}),
    "publishing": frozenset({"published", "failed", "scheduled", "approved"}),
    # published is terminal for a version; an edit creates a new version that goes back through review
    "published": frozenset({"in_review", "editing", "seo", "qa", "drafting", "publishing", "approved", "scheduled"}),
    "archived": frozenset({"queued", "in_review"}),
    "needs_sources": frozenset({"researching", "archived", "queued"}),
    "failed": frozenset({"queued", "researching", "drafting", "editing", "seo", "qa", "in_review", "archived", "approved"}),
}


class IllegalTransition(Exception):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"Illegal article transition {current} -> {target}")
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in _TRANSITIONS.get(current, frozenset())


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise IllegalTransition(current, target)


def runnable_stages(state: str, *, busy: bool = False) -> list[str]:
    """Stages a user may start manually. `busy` = the article has a queued/running job. A stage state with no
    active job (e.g. 'drafting' after a manual Write run) is idle and can move on."""
    if busy or state in TERMINAL_FOR_EDITS or state == "archived":
        return []
    return [s for s in STAGE_ORDER if can_transition(state, STAGE_STATE[s])]


def next_stage(stage: str) -> str | None:
    idx = STAGE_ORDER.index(stage)
    return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else None
