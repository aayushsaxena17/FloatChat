"""Checked transitions and aggregate outcomes shared by SQL/controller tests."""

from collections.abc import Iterable
from datetime import datetime, timedelta

from .numeric import Rejection
from .planning import Interval, RunPolicy

TERMINAL = frozenset({"complete", "quarantined", "failed"})
TRANSITIONS = {
    "planned": frozenset({"fetching", "failed"}),
    "fetching": frozenset({"fetching", "landed", "quarantined", "failed"}),
    "landed": frozenset({"landed", "validating", "quarantined", "failed"}),
    "validating": frozenset({"validating", "publishing", "quarantined", "failed"}),
    "publishing": frozenset({"publishing", "complete", "quarantined", "failed"}),
    "complete": frozenset(),
    "quarantined": frozenset(),
    "failed": frozenset(),
}
EXIT_CODES = {"complete": 0, "partial": 3, "quarantined": 4, "failed": 5, "overlap_skip": 6}


def transition(current: str, proposed: str) -> None:
    if proposed not in TRANSITIONS.get(current, frozenset()):
        raise Rejection("invalid_state_transition")


def reduce_run(leaves: Iterable[str]) -> str:
    states = list(leaves)
    if not states or any(x not in TERMINAL for x in states):
        raise Rejection("unfinished_run")
    if all(x == "complete" for x in states):
        return "complete"
    if "complete" in states:
        return "partial"
    if "quarantined" in states and "failed" not in states:
        return "quarantined"
    return "failed"


def exit_code(state: str, *, cancellation_affected: bool = False) -> int:
    return 130 if cancellation_affected else EXIT_CODES[state]


def schedule_interval(policy: RunPolicy, watermark: datetime | None) -> Interval:
    """One oldest-first tick; completion, not observations, advances the watermark."""
    if policy.mode != "normal":
        raise Rejection("acceptance_schedule_disabled")
    start = max(policy.eligible.start, (watermark or policy.reference) - timedelta(days=14))
    end = min(policy.reference, start + timedelta(days=31))
    return Interval(start, end)
