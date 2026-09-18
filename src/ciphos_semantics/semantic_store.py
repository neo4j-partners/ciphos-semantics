"""Persistence and readback for a source-scoped CIPHOS LPG semantic map."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from neo4j import RoutingControl

from .semantic_config import (
    OperationalNeo4jConnection,
    SemanticStoreNeo4jConnection,
)
from .semantic_map_contract import (
    NEOCARTA_VERSION,
    RECORD_KINDS,
    SchemaMap,
    SemanticContext,
    SemanticEdge,
    SemanticRecord,
    SourceIdentity,
    source_scope,
)

DELETE_SCOPE_CYPHER = """
MATCH (entity {source_scope: $source_scope})
DETACH DELETE entity
"""
UPSERT_RECORD_CYPHER = {
    "Database": """
UNWIND $rows AS row
MERGE (entity:Database {id: row.id})
SET entity += row
""",
    "Schema": """
UNWIND $rows AS row
MERGE (entity:Schema {id: row.id})
SET entity += row
""",
    "Node": """
UNWIND $rows AS row
MERGE (entity:Node {id: row.id})
SET entity += row
""",
    "Relationship": """
UNWIND $rows AS row
MERGE (entity:Relationship {id: row.id})
SET entity += row
""",
    "Property": """
UNWIND $rows AS row
MERGE (entity:Property {id: row.id})
SET entity += row
""",
}
UPSERT_EDGE_CYPHER = {
    kind: f"""
UNWIND $rows AS row
MATCH (source {{id: row.source_id, source_scope: $source_scope}})
MATCH (target {{id: row.target_id, source_scope: $source_scope}})
MERGE (source)-[:{kind}]->(target)
"""
    for kind in (
        "HAS_SCHEMA",
        "HAS_NODE",
        "HAS_RELATIONSHIP",
        "HAS_PROPERTY",
        "HAS_SOURCE_NODE",
        "HAS_TARGET_NODE",
    )
}

LPG_ID_UNIQUENESS_CONSTRAINTS = (
    """CREATE CONSTRAINT database_id_constraint IF NOT EXISTS
FOR (d:Database) REQUIRE d.id IS UNIQUE;""",
    """CREATE CONSTRAINT schema_id_constraint IF NOT EXISTS
FOR (s:Schema) REQUIRE s.id IS UNIQUE;""",
    """CREATE CONSTRAINT node_id_constraint IF NOT EXISTS
FOR (n:Node) REQUIRE n.id IS UNIQUE;""",
    """CREATE CONSTRAINT relationship_id_constraint IF NOT EXISTS
FOR (r:Relationship) REQUIRE r.id IS UNIQUE;""",
    """CREATE CONSTRAINT property_id_constraint IF NOT EXISTS
FOR (p:Property) REQUIRE p.id IS UNIQUE;""",
)
UPSERT_NEOCARTA_GRAPH_CYPHER = """
MERGE (node:`__neocarta_graph__`)
ON CREATE SET
    node.initial_version = $version,
    node.latest_version = $version,
    node.create_date = datetime(),
    node.last_updated = datetime()
ON MATCH SET
    node.latest_version = $version,
    node.last_updated = datetime()
RETURN node.initial_version AS initial_version,
       node.latest_version AS latest_version,
       node.create_date AS create_date,
       node.last_updated AS last_updated
"""
READ_RECORDS_CYPHER = """
MATCH (entity {source_scope: $source_scope})
RETURN CASE
    WHEN entity:Database THEN 'Database'
    WHEN entity:Schema THEN 'Schema'
    WHEN entity:Node THEN 'Node'
    WHEN entity:Relationship THEN 'Relationship'
    WHEN entity:Property THEN 'Property'
    ELSE null
END AS kind, properties(entity) AS metadata
ORDER BY kind, entity.id
"""
READ_EDGES_CYPHER = """
MATCH (source {source_scope: $source_scope})-[relationship]->(target {source_scope: $source_scope})
RETURN source.id AS source_id, type(relationship) AS kind, target.id AS target_id
ORDER BY source_id, kind, target_id
"""
LIST_SOURCE_SCOPES_CYPHER = """
MATCH (database:Database)
WHERE database.source_scope IS NOT NULL
  AND database.source_uri IS NOT NULL
  AND database.source_database IS NOT NULL
RETURN DISTINCT database.source_scope AS source_scope
ORDER BY source_scope
"""


def _record_rows(schema_map: SchemaMap) -> dict[str, list[dict[str, Any]]]:
    """Attach CIPHOS persistence fields after canonical records are already validated."""
    rows = {kind: [] for kind in RECORD_KINDS}
    for record in schema_map.records():
        rows[record.kind].append(schema_map.persisted_record(record))
    for kind in RECORD_KINDS:
        rows[kind].sort(key=lambda row: str(row["id"]))
    return rows


def _edge_rows(edges: Iterable[SemanticEdge]) -> dict[str, list[dict[str, str]]]:
    rows = {kind: [] for kind in UPSERT_EDGE_CYPHER}
    for edge in edges:
        rows[edge.kind].append(edge.as_dict())
    for kind in rows:
        rows[kind].sort(key=lambda row: (row["source_id"], row["target_id"]))
    return rows


class SemanticStore:
    """Write and read a semantic map through the dedicated store driver only."""

    def __init__(self, driver: Any, connection: SemanticStoreNeo4jConnection) -> None:
        self._driver = driver
        self._connection = connection

    @property
    def connection(self) -> SemanticStoreNeo4jConnection:
        """Return the store configuration without exposing credentials in its repr."""
        return self._connection

    def prepare(self) -> None:
        """Install the five LPG ID constraints and stamp the NeoCarta graph version."""
        for query in LPG_ID_UNIQUENESS_CONSTRAINTS:
            self._driver.execute_query(
                query_=query,
                database_=self._connection.database,
                routing_=RoutingControl.WRITE,
            )
        self._driver.execute_query(
            query_=UPSERT_NEOCARTA_GRAPH_CYPHER,
            parameters_={"version": NEOCARTA_VERSION},
            database_=self._connection.database,
            routing_=RoutingControl.WRITE,
        )

    def replace(self, schema_map: SchemaMap) -> None:
        """Atomically replace precisely one source scope with deterministic records and edges."""
        record_rows = _record_rows(schema_map)
        edge_rows = _edge_rows(schema_map.edges)
        with self._driver.session(database=self._connection.database) as session:
            session.execute_write(
                self._replace_transaction,
                schema_map.source_scope,
                record_rows,
                edge_rows,
            )

    @staticmethod
    def _replace_transaction(
        transaction: Any,
        scope: str,
        record_rows: dict[str, list[dict[str, Any]]],
        edge_rows: dict[str, list[dict[str, str]]],
    ) -> None:
        transaction.run(DELETE_SCOPE_CYPHER, source_scope=scope)
        for kind in RECORD_KINDS:
            rows = record_rows[kind]
            if rows:
                transaction.run(UPSERT_RECORD_CYPHER[kind], rows=rows)
        for kind, query in UPSERT_EDGE_CYPHER.items():
            rows = edge_rows[kind]
            if rows:
                transaction.run(query, source_scope=scope, rows=rows)

    def read_context(self, source_scope: str) -> SemanticContext:
        """Read one persisted source scope using read routing only."""
        records, _, _ = self._driver.execute_query(
            query_=READ_RECORDS_CYPHER,
            parameters_={"source_scope": source_scope},
            database_=self._connection.database,
            routing_=RoutingControl.READ,
        )
        edges, _, _ = self._driver.execute_query(
            query_=READ_EDGES_CYPHER,
            parameters_={"source_scope": source_scope},
            database_=self._connection.database,
            routing_=RoutingControl.READ,
        )
        return _context_from_rows(source_scope, records, edges)

    def list_source_scopes(self) -> tuple[str, ...]:
        """List persisted CIPHOS map scopes through the semantic-store driver only."""
        records, _, _ = self._driver.execute_query(
            query_=LIST_SOURCE_SCOPES_CYPHER,
            database_=self._connection.database,
            routing_=RoutingControl.READ,
        )
        return tuple(
            sorted(
                {
                    str(_row_value(record, "source_scope"))
                    for record in records
                    if _row_value(record, "source_scope") is not None
                }
            )
        )


def _row_value(row: Any, name: str) -> Any:
    if hasattr(row, "__getitem__"):
        return row[name]
    raise TypeError("Semantic-store query returned an unsupported record.")


def _context_from_rows(
    source_scope: str, record_rows: Iterable[Any], edge_rows: Iterable[Any]
) -> SemanticContext:
    records: list[SemanticRecord] = []
    source_identity: SourceIdentity | None = None
    endpoints_available: bool | None = None
    for row in record_rows:
        raw_kind = _row_value(row, "kind")
        if raw_kind not in RECORD_KINDS:
            raise ValueError("Semantic-store contains an unsupported LPG record kind.")
        kind = raw_kind
        metadata = dict(_row_value(row, "metadata"))
        if kind == "Database":
            source_identity = SourceIdentity.from_connection(
                str(metadata.pop("source_uri")), str(metadata.pop("source_database"))
            )
            endpoints_available = bool(metadata.pop("endpoints_available"))
        metadata.pop("source_scope", None)
        records.append(SemanticRecord(kind, metadata))
    if source_identity is None or endpoints_available is None:
        raise ValueError("Semantic-store scope does not contain required source metadata.")
    edges = tuple(
        SemanticEdge(
            source_id=str(_row_value(row, "source_id")),
            kind=_edge_kind(_row_value(row, "kind")),
            target_id=str(_row_value(row, "target_id")),
        )
        for row in edge_rows
    )
    return SemanticContext(
        source_scope=source_scope,
        source_identity=source_identity,
        endpoints_available=endpoints_available,
        records=tuple(records),
        edges=edges,
    )


def _edge_kind(value: Any) -> str:
    """Reject null or non-contract edge types before creating an edge record."""
    if value not in UPSERT_EDGE_CYPHER:
        raise ValueError("Semantic-store contains an unsupported LPG edge kind.")
    return value


def ingest_schema_map(
    store: SemanticStore,
    source: OperationalNeo4jConnection,
    schema_map: SchemaMap,
) -> None:
    """Create or replace a semantic scope from a freshly extracted schema map."""
    if schema_map.source_identity != source.identity:
        raise ValueError("Schema map source identity does not match the operational source.")
    if schema_map.source_scope != source_scope(source.identity):
        raise ValueError("Schema map source scope does not match the operational source.")
    store.prepare()
    store.replace(schema_map)
