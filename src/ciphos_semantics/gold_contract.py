"""Row-grain and idempotency contracts for graph-derived Gold publication.

Actual Gold writes belong to the lakehouse pipeline. The demo uses these
helpers to make the required row identity explicit before a publisher is wired
to a published Silver and graph run.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class GoldGraphRun:
    """Metadata shared by every result created during one graph calculation."""

    run_id: str
    source_snapshot_id: str
    graph_snapshot_id: str
    algorithm_name: str
    algorithm_version: str
    computed_at: datetime


@dataclass(frozen=True)
class GoldExposureRow:
    """One source entity, impacted entity, and calculated path or score."""

    run_id: str
    source_entity_id: str
    impacted_entity_id: str
    path_id: str
    exposure_score: float | None = None

    @property
    def idempotency_key(self) -> str:
        return stable_key(
            self.run_id,
            self.source_entity_id,
            self.impacted_entity_id,
            self.path_id,
        )


@dataclass(frozen=True)
class GoldPathHop:
    """One ordered hop inside a published graph path."""

    run_id: str
    path_id: str
    hop_number: int
    from_entity_id: str
    relationship_type: str
    to_entity_id: str

    @property
    def idempotency_key(self) -> str:
        return stable_key(self.run_id, self.path_id, str(self.hop_number))


def stable_key(*parts: str) -> str:
    """Return a deterministic key for a documented Gold-table grain."""
    if any(not part for part in parts):
        raise ValueError("Gold identifiers must be non-empty.")
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _deduplicate(rows: Iterable[GoldExposureRow | GoldPathHop]) -> list:
    deduplicated: dict[str, GoldExposureRow | GoldPathHop] = {}
    for row in rows:
        key = row.idempotency_key
        existing = deduplicated.setdefault(key, row)
        if existing != row:
            raise ValueError(f"Conflicting Gold rows share key {key}.")
    return list(deduplicated.values())


def unique_rows(rows: Iterable[GoldExposureRow]) -> list[GoldExposureRow]:
    """Reject duplicate exposure rows rather than making publication non-idempotent."""
    return _deduplicate(rows)


def unique_hops(hops: Iterable[GoldPathHop]) -> list[GoldPathHop]:
    """Apply the same idempotency rule to path hops as to exposure rows."""
    return _deduplicate(hops)
