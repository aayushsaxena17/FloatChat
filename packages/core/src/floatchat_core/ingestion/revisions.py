"""Conservative component-wise source revisions, never retrieval timestamps."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

RevisionOutcome = Literal[
    "insert", "newer", "revision_only", "noop", "unordered_noop", "stale_skip", "revision_conflict"
]


@dataclass(frozen=True)
class Revision:
    kind: str
    components: tuple[tuple[str, datetime], ...]

    def __post_init__(self) -> None:
        keys = [key for key, _ in self.components]
        if not keys or keys != sorted(set(keys)):
            raise ValueError("invalid_revision_vector")


def compare(
    incoming_hash: str, incoming: Revision | None, stored_hash: str | None, stored: Revision | None
) -> RevisionOutcome:
    if stored_hash is None:
        return "insert"
    equal = incoming_hash == stored_hash
    if incoming is None and stored is None:
        return "noop" if equal else "revision_conflict"
    if incoming is not None and stored is not None and incoming.kind == stored.kind:
        a, b = dict(incoming.components), dict(stored.components)
        if a.keys() == b.keys():
            if a == b:
                return "noop" if equal else "revision_conflict"
            if all(a[k] >= b[k] for k in a):
                return "revision_only" if equal else "newer"
            if all(a[k] <= b[k] for k in a):
                return "stale_skip"
    return "unordered_noop" if equal else "revision_conflict"
