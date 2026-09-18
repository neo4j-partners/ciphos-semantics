"""Shared contracts for the source-derived CIPHOS LPG semantic map."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

NEOCARTA_VERSION = "0.8.0"
SOURCE_SCOPE_PREFIX = "neo4j"
IDENTITY_DELIMITER = "\x1f"
DIGEST_LENGTH = 16
UNLABELED_NODE = "<unlabeled>"
CIPHOS_MARKER_LABEL = "CiphosEntity"
STRUCTURAL_METADATA_NOTICE = (
    "Structural metadata only; no operational values or inferred definitions."
)

RecordKind = Literal["Database", "Schema", "Node", "Relationship", "Property"]
EdgeKind = Literal[
    "HAS_SCHEMA",
    "HAS_NODE",
    "HAS_RELATIONSHIP",
    "HAS_PROPERTY",
    "HAS_SOURCE_NODE",
    "HAS_TARGET_NODE",
]

RECORD_KINDS: tuple[RecordKind, ...] = (
    "Database",
    "Schema",
    "Node",
    "Relationship",
    "Property",
)
EDGE_KINDS: frozenset[str] = frozenset(
    {
        "HAS_SCHEMA",
        "HAS_NODE",
        "HAS_RELATIONSHIP",
        "HAS_PROPERTY",
        "HAS_SOURCE_NODE",
        "HAS_TARGET_NODE",
    }
)


def normalize_neo4j_uri(uri: str) -> str:
    """Return a stable, credential-free Neo4j server URI identity."""
    raw_uri = uri.strip()
    parsed = urlsplit(raw_uri)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError("Neo4j URI must include a scheme and hostname.")
    if parsed.query or parsed.fragment:
        raise ValueError("Neo4j URI identity must not contain a query or fragment.")

    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Neo4j URI contains an invalid port.") from error
    netloc = f"{host}:{port}" if port is not None else host
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


@dataclass(frozen=True, order=True)
class SourceIdentity:
    """Credential-free identity of one Neo4j source database."""

    uri: str
    database: str

    @classmethod
    def from_connection(cls, uri: str, database: str) -> SourceIdentity:
        normalized_database = database.strip()
        if not normalized_database:
            raise ValueError("Neo4j database name must not be empty.")
        return cls(normalize_neo4j_uri(uri), normalized_database)

    def as_dict(self) -> dict[str, str]:
        return {"uri": self.uri, "database": self.database}


def source_scope(identity: SourceIdentity) -> str:
    """Build the stable source scope from normalized URI and database identity."""
    value = IDENTITY_DELIMITER.join((identity.uri, identity.database))
    digest = hashlib.sha256(value.encode()).hexdigest()[:DIGEST_LENGTH]
    return f"{SOURCE_SCOPE_PREFIX}:{digest}"


def scoped_id(scope: str, kind: str, *parts: str) -> str:
    """Build a deterministic identifier within one source scope."""
    value = IDENTITY_DELIMITER.join(parts)
    digest = hashlib.sha256(value.encode()).hexdigest()[:DIGEST_LENGTH]
    return f"{scope}:{kind}:{digest}"


def canonical_label_set(labels: object) -> tuple[str, ...]:
    """Normalize a procedure label collection into a stable label-set identity."""
    if isinstance(labels, (str, bytes)) or not isinstance(labels, (list, tuple, set)):
        return (UNLABELED_NODE,)
    normalized = tuple(sorted({str(label).strip() for label in labels if str(label).strip()}))
    return normalized or (UNLABELED_NODE,)


def split_node_labels(labels: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    """Choose a domain primary label while retaining the complete label set."""
    normalized = canonical_label_set(labels)
    domain_labels = tuple(label for label in normalized if label != CIPHOS_MARKER_LABEL)
    primary = domain_labels[0] if domain_labels else normalized[0]
    additional = tuple(label for label in normalized if label != primary)
    return primary, additional


@dataclass(frozen=True, order=True)
class SemanticEdge:
    """One canonical relationship between LPG metadata records."""

    source_id: str
    kind: EdgeKind
    target_id: str

    def __post_init__(self) -> None:
        if self.kind not in EDGE_KINDS:
            raise ValueError(f"Unsupported semantic edge kind: {self.kind}")

    def as_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "kind": self.kind,
            "target_id": self.target_id,
        }


@dataclass(frozen=True)
class SemanticRecord:
    """A NeoCarta LPG record with its canonical record kind."""

    kind: RecordKind
    metadata: Mapping[str, Any]

    @property
    def id(self) -> str:
        return str(self.metadata["id"])

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, **self.metadata}


@dataclass(frozen=True)
class SchemaMap:
    """Canonical, in-memory LPG map for one operational source."""

    source_identity: SourceIdentity
    source_scope: str
    database: Mapping[str, Any]
    schema: Mapping[str, Any]
    nodes: tuple[Mapping[str, Any], ...]
    relationships: tuple[Mapping[str, Any], ...]
    properties: tuple[Mapping[str, Any], ...]
    edges: tuple[SemanticEdge, ...]
    endpoints_available: bool

    def __post_init__(self) -> None:
        """Reject maps whose links cannot be represented by the store writer.

        ``UPSERT_EDGE_CYPHER`` deliberately uses ``MATCH`` so it can never
        create an orphaned edge.  Without this check, however, a corrupt map
        with a missing endpoint would make that ``MATCH`` yield no rows and
        silently lose a declared link.  Reject it before the replacement
        transaction begins instead.
        """
        record_ids: set[str] = set()
        for record in self.records():
            raw_id = record.metadata.get("id")
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise ValueError(f"{record.kind} record must have a non-empty string id.")
            if raw_id in record_ids:
                raise ValueError(f"Schema map contains duplicate record id: {raw_id!r}.")
            record_ids.add(raw_id)

        for edge in self.edges:
            missing = sorted({edge.source_id, edge.target_id}.difference(record_ids))
            if missing:
                raise ValueError(
                    "Schema map edge references missing record id(s): "
                    + ", ".join(repr(record_id) for record_id in missing)
                    + "."
                )

    def records(self) -> Iterator[SemanticRecord]:
        yield SemanticRecord("Database", self.database)
        yield SemanticRecord("Schema", self.schema)
        yield from (SemanticRecord("Node", row) for row in self.nodes)
        yield from (SemanticRecord("Relationship", row) for row in self.relationships)
        yield from (SemanticRecord("Property", row) for row in self.properties)

    def persisted_record(self, record: SemanticRecord) -> dict[str, Any]:
        """Attach CIPHOS fields only after the NeoCarta-shaped record is built."""
        row = dict(record.metadata)
        row["source_scope"] = self.source_scope
        if record.kind == "Database":
            row.update(
                {
                    "source_uri": self.source_identity.uri,
                    "source_database": self.source_identity.database,
                    "endpoints_available": self.endpoints_available,
                }
            )
        return row


@dataclass(frozen=True)
class SemanticContext:
    """Stable JSON response returned by local inspection and MCP retrieval."""

    source_scope: str
    source_identity: SourceIdentity
    endpoints_available: bool
    records: tuple[SemanticRecord, ...]
    edges: tuple[SemanticEdge, ...]
    notice: str = STRUCTURAL_METADATA_NOTICE

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_scope": self.source_scope,
            "source_identity": self.source_identity.as_dict(),
            "endpoints_available": self.endpoints_available,
            "records": [record.as_dict() for record in self.records],
            "edges": [edge.as_dict() for edge in self.edges],
            "notice": self.notice,
        }
