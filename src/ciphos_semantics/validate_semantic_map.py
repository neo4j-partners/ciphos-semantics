"""Pure drift checks for a persisted CIPHOS semantic map.

This module deliberately knows nothing about Neo4j drivers, environment
variables, or extraction.  Keeping comparison here makes it safe to use in a
CLI, a deployment check, or unit tests without accidentally reconnecting to
the operational graph.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ciphos_semantics.semantic_map_contract import (
    SchemaMap,
    SemanticContext,
    SemanticEdge,
    SemanticRecord,
)

_SENSITIVE_FIELD_FRAGMENTS = ("password", "secret", "token", "credential", "authorization")


def context_from_schema_map(schema_map: SchemaMap) -> SemanticContext:
    """Return the canonical context a fresh extraction is expected to persist."""
    return SemanticContext(
        source_scope=schema_map.source_scope,
        source_identity=schema_map.source_identity,
        endpoints_available=schema_map.endpoints_available,
        records=tuple(schema_map.records()),
        edges=schema_map.edges,
    )


def _safe_uri(value: object) -> str:
    """Remove URI user information before including it in diagnostics."""
    text = str(value)
    parsed = urlsplit(text)
    if not parsed.scheme or not parsed.hostname:
        return "<redacted-invalid-uri>"
    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError:
        return "<redacted-invalid-uri>"
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path.rstrip("/"), "", ""))


def _safe_value(value: Any, *, field_name: str = "") -> Any:
    """Produce diagnostics without disclosing accidental credential fields."""
    lowered = field_name.lower()
    if any(fragment in lowered for fragment in _SENSITIVE_FIELD_FRAGMENTS):
        return "<redacted>"
    if lowered in {"uri", "source_uri", "target_uri", "url"}:
        return _safe_uri(value)
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(item, field_name=str(key)) for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_safe_value(item) for item in value]
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


def _safe_identity(context: SemanticContext) -> dict[str, str]:
    identity = context.source_identity
    return {"uri": _safe_uri(identity.uri), "database": str(identity.database)}


def _record_rows(records: tuple[SemanticRecord, ...]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.id in rows:
            raise ValueError(f"Semantic context has duplicate record id {record.id!r}.")
        rows[record.id] = record.as_dict()
    return rows


def _edge_rows(edges: tuple[SemanticEdge, ...]) -> set[tuple[str, str, str]]:
    return {(edge.source_id, edge.kind, edge.target_id) for edge in edges}


def _edge_dict(edge: tuple[str, str, str]) -> dict[str, str]:
    source_id, kind, target_id = edge
    return {"source_id": source_id, "kind": kind, "target_id": target_id}


@dataclass(frozen=True)
class DriftReport:
    """Structured, credential-safe differences between fresh and stored maps."""

    missing: Mapping[str, tuple[dict[str, Any], ...]]
    unexpected: Mapping[str, tuple[dict[str, Any], ...]]
    changed: Mapping[str, Any]

    @property
    def is_clean(self) -> bool:
        """Whether no persisted-map drift was detected."""
        return not (
            any(self.missing.values())
            or any(self.unexpected.values())
            or any(self.changed.values())
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly, secret-safe diagnostics document."""
        return {
            "missing": _safe_value(dict(self.missing)),
            "unexpected": _safe_value(dict(self.unexpected)),
            "changed": _safe_value(dict(self.changed)),
        }


class SemanticMapDriftError(RuntimeError):
    """Raised when the persisted semantic map differs from fresh metadata."""

    def __init__(self, report: DriftReport) -> None:
        self.report = report
        super().__init__(
            "Persisted CIPHOS semantic map differs from fresh source metadata: "
            + json.dumps(report.as_dict(), sort_keys=True, default=str)
        )


def compare_semantic_map(expected: SchemaMap, actual: SemanticContext) -> DriftReport:
    """Compare a fresh :class:`SchemaMap` with its stored canonical context.

    Record modifications are matched by their stable IDs.  Edges have no
    independent identifier, so an altered edge is represented as one missing
    edge and one unexpected edge.  All output is deterministic and safe to
    print in operator-facing diagnostics.
    """
    fresh = context_from_schema_map(expected)
    expected_records = _record_rows(fresh.records)
    actual_records = _record_rows(actual.records)
    expected_edges = _edge_rows(fresh.edges)
    actual_edges = _edge_rows(actual.edges)

    missing_records = tuple(
        _safe_value(expected_records[record_id])
        for record_id in sorted(expected_records.keys() - actual_records.keys())
    )
    unexpected_records = tuple(
        _safe_value(actual_records[record_id])
        for record_id in sorted(actual_records.keys() - expected_records.keys())
    )
    changed_records = tuple(
        {
            "id": record_id,
            "expected": _safe_value(expected_records[record_id]),
            "actual": _safe_value(actual_records[record_id]),
        }
        for record_id in sorted(expected_records.keys() & actual_records.keys())
        if expected_records[record_id] != actual_records[record_id]
    )

    missing_edges = tuple(_edge_dict(edge) for edge in sorted(expected_edges - actual_edges))
    unexpected_edges = tuple(_edge_dict(edge) for edge in sorted(actual_edges - expected_edges))
    changed: dict[str, Any] = {"records": changed_records, "edges": ()}
    if fresh.source_identity != actual.source_identity:
        changed["source_identity"] = {
            "expected": _safe_identity(fresh),
            "actual": _safe_identity(actual),
        }
    if fresh.source_scope != actual.source_scope:
        changed["source_scope"] = {
            "expected": fresh.source_scope,
            "actual": actual.source_scope,
        }
    if fresh.endpoints_available != actual.endpoints_available:
        changed["endpoints_available"] = {
            "expected": fresh.endpoints_available,
            "actual": actual.endpoints_available,
        }

    return DriftReport(
        missing={"records": missing_records, "edges": missing_edges},
        unexpected={"records": unexpected_records, "edges": unexpected_edges},
        changed=changed,
    )


def validate_semantic_map(expected: SchemaMap, actual: SemanticContext) -> None:
    """Raise :class:`SemanticMapDriftError` if a stored map has drifted."""
    report = compare_semantic_map(expected, actual)
    if not report.is_clean:
        raise SemanticMapDriftError(report)
