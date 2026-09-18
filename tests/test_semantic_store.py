"""Unit tests for source-scoped semantic-store persistence and readback."""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any

from neo4j import RoutingControl

from ciphos_semantics.semantic_config import (
    OperationalNeo4jConnection,
    SemanticStoreNeo4jConnection,
)
from ciphos_semantics.semantic_map_contract import (
    SchemaMap,
    SemanticEdge,
    SourceIdentity,
    scoped_id,
    source_scope,
)
from ciphos_semantics.semantic_store import (
    DELETE_SCOPE_CYPHER,
    LIST_SOURCE_SCOPES_CYPHER,
    LPG_ID_UNIQUENESS_CONSTRAINTS,
    READ_EDGES_CYPHER,
    READ_RECORDS_CYPHER,
    UPSERT_NEOCARTA_GRAPH_CYPHER,
    SemanticStore,
    ingest_schema_map,
)


def source_connection() -> OperationalNeo4jConnection:
    return OperationalNeo4jConnection(
        uri="neo4j+s://reader:source-secret@ops.example.com",
        username="reader",
        password="source-secret",
        database="neo4j",
    )


def store_connection() -> SemanticStoreNeo4jConnection:
    return SemanticStoreNeo4jConnection(
        uri="neo4j+s://writer:store-secret@store.example.com",
        username="writer",
        password="store-secret",
        database="neo4j",
    )


def schema_map() -> SchemaMap:
    identity = SourceIdentity.from_connection("neo4j+s://ops.example.com", "neo4j")
    scope = source_scope(identity)
    database_id = scoped_id(scope, "database", "neo4j")
    schema_id = scoped_id(scope, "schema", "default")
    node_id = scoped_id(scope, "node", "Tag")
    property_id = scoped_id(scope, "property", "node", "Tag", "tagNumber")
    return SchemaMap(
        source_identity=identity,
        source_scope=scope,
        database={"id": database_id, "name": "neo4j", "service": "NEO4J"},
        schema={"id": schema_id, "name": "default"},
        nodes=({"id": node_id, "label": "Tag", "additional_labels": []},),
        relationships=(),
        properties=(
            {
                "id": property_id,
                "name": "tagNumber",
                "type": "STRING",
                "unique": True,
                "nullable": False,
                "indexed": True,
                "existence": True,
            },
        ),
        edges=(
            SemanticEdge(database_id, "HAS_SCHEMA", schema_id),
            SemanticEdge(schema_id, "HAS_NODE", node_id),
            SemanticEdge(node_id, "HAS_PROPERTY", property_id),
        ),
        endpoints_available=False,
    )


class TransactionStub:
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, query: str, **parameters: Any) -> None:
        self.calls.append((query, parameters))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("write failed")


class SessionStub:
    def __init__(self, transaction: TransactionStub) -> None:
        self.transaction = transaction
        self.write_calls = 0

    def __enter__(self) -> SessionStub:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute_write(self, callback: Any, *args: Any) -> Any:
        self.write_calls += 1
        return callback(self.transaction, *args)


class DriverStub:
    def __init__(
        self,
        transaction: TransactionStub | None = None,
        query_results: list[list[dict[str, Any]]] | None = None,
    ) -> None:
        self.transaction = transaction or TransactionStub()
        self.session_instance = SessionStub(self.transaction)
        self.query_results = query_results or []
        self.execute_calls: list[dict[str, Any]] = []

    def session(self, **kwargs: Any) -> SessionStub:
        self.session_kwargs = kwargs
        return self.session_instance

    def execute_query(self, **kwargs: Any) -> tuple[list[dict[str, Any]], None, None]:
        self.execute_calls.append(kwargs)
        return (self.query_results.pop(0) if self.query_results else []), None, None


class SemanticStoreTests(unittest.TestCase):
    def test_prepare_installs_exactly_five_constraints_then_stamps_pinned_version(self) -> None:
        driver = DriverStub()
        store = SemanticStore(driver, store_connection())

        store.prepare()

        self.assertEqual(len(LPG_ID_UNIQUENESS_CONSTRAINTS), 5)
        self.assertEqual(
            [call["query_"] for call in driver.execute_calls[:5]],
            list(LPG_ID_UNIQUENESS_CONSTRAINTS),
        )
        self.assertEqual(driver.execute_calls[5]["query_"], UPSERT_NEOCARTA_GRAPH_CYPHER)
        self.assertEqual(driver.execute_calls[5]["parameters_"], {"version": "0.8.0"})
        self.assertTrue(
            all(call["routing_"] == RoutingControl.WRITE for call in driver.execute_calls)
        )

    def test_replace_attaches_scope_after_canonical_rows_and_orders_transaction_calls(self) -> None:
        driver = DriverStub()
        semantic_map = schema_map()

        SemanticStore(driver, store_connection()).replace(semantic_map)

        calls = driver.transaction.calls
        self.assertEqual(driver.session_instance.write_calls, 1)
        self.assertEqual(calls[0][0], DELETE_SCOPE_CYPHER)
        self.assertEqual(calls[0][1], {"source_scope": semantic_map.source_scope})
        database_rows = calls[1][1]["rows"]
        self.assertEqual(database_rows[0]["source_scope"], semantic_map.source_scope)
        self.assertEqual(database_rows[0]["source_uri"], "neo4j+s://ops.example.com")
        self.assertNotIn("source_scope", semantic_map.database)
        self.assertIn("HAS_SCHEMA", calls[-3][0])
        self.assertIn("HAS_NODE", calls[-2][0])
        self.assertIn("HAS_PROPERTY", calls[-1][0])

    def test_failed_transaction_stops_at_failure_with_no_later_write_calls(self) -> None:
        transaction = TransactionStub(fail_on_call=3)
        driver = DriverStub(transaction=transaction)

        with self.assertRaisesRegex(RuntimeError, "write failed"):
            SemanticStore(driver, store_connection()).replace(schema_map())

        self.assertEqual(len(transaction.calls), 3)
        self.assertEqual(transaction.calls[0][0], DELETE_SCOPE_CYPHER)
        self.assertEqual(driver.session_instance.write_calls, 1)

    def test_replacement_query_design_is_idempotent_and_scope_isolated(self) -> None:
        driver = DriverStub()
        store = SemanticStore(driver, store_connection())
        store.replace(schema_map())
        first_queries = [query for query, _ in driver.transaction.calls]
        driver.transaction.calls.clear()
        store.replace(schema_map())
        second_queries = [query for query, _ in driver.transaction.calls]

        self.assertEqual(first_queries, second_queries)
        self.assertIn("source_scope: $source_scope", DELETE_SCOPE_CYPHER)
        for query in second_queries[1:]:
            self.assertIn("MERGE", query)

    def test_map_rejects_an_edge_that_the_store_would_otherwise_silently_skip(self) -> None:
        semantic_map = schema_map()

        with self.assertRaisesRegex(ValueError, "references missing record id"):
            replace(
                semantic_map,
                edges=(
                    *semantic_map.edges,
                    SemanticEdge(semantic_map.nodes[0]["id"], "HAS_PROPERTY", "missing-id"),
                ),
            )

    def test_context_round_trip_uses_read_routing_and_removes_persistence_only_fields(self) -> None:
        semantic_map = schema_map()
        persisted = [semantic_map.persisted_record(record) for record in semantic_map.records()]
        record_rows = [
            {"kind": kind, "metadata": row}
            for kind, row in zip(
                ("Database", "Schema", "Node", "Property"),
                persisted,
                strict=True,
            )
        ]
        edge_rows = [edge.as_dict() for edge in semantic_map.edges]
        driver = DriverStub(query_results=[record_rows, edge_rows])

        context = SemanticStore(driver, store_connection()).read_context(semantic_map.source_scope)

        self.assertEqual(context.source_identity, semantic_map.source_identity)
        self.assertFalse(context.endpoints_available)
        self.assertEqual(context.edges, semantic_map.edges)
        self.assertNotIn("source_scope", context.records[0].metadata)
        self.assertNotIn("source_uri", context.records[0].metadata)
        self.assertEqual(driver.execute_calls[0]["query_"], READ_RECORDS_CYPHER)
        self.assertEqual(driver.execute_calls[1]["query_"], READ_EDGES_CYPHER)
        self.assertIn("CASE", READ_RECORDS_CYPHER)
        self.assertNotIn("labels(entity)[0]", READ_RECORDS_CYPHER)
        self.assertTrue(
            all(call["routing_"] == RoutingControl.READ for call in driver.execute_calls)
        )

    def test_context_rejects_an_unrecognised_persisted_record_label(self) -> None:
        driver = DriverStub(query_results=[[{"kind": None, "metadata": {}}], []])

        with self.assertRaisesRegex(ValueError, "unsupported LPG record kind"):
            SemanticStore(driver, store_connection()).read_context("neo4j:scope")

    def test_list_source_scopes_reads_only_persisted_ciphos_database_scopes(self) -> None:
        driver = DriverStub(
            query_results=[
                [
                    {"source_scope": "neo4j:second"},
                    {"source_scope": "neo4j:first"},
                    {"source_scope": "neo4j:second"},
                ]
            ]
        )

        scopes = SemanticStore(driver, store_connection()).list_source_scopes()

        self.assertEqual(scopes, ("neo4j:first", "neo4j:second"))
        self.assertEqual(driver.execute_calls[0]["query_"], LIST_SOURCE_SCOPES_CYPHER)
        self.assertEqual(driver.execute_calls[0]["routing_"], RoutingControl.READ)
        self.assertNotIn("OPS_NEO4J", LIST_SOURCE_SCOPES_CYPHER)
        self.assertIn("database.source_uri IS NOT NULL", LIST_SOURCE_SCOPES_CYPHER)
        self.assertIn("database.source_database IS NOT NULL", LIST_SOURCE_SCOPES_CYPHER)

    def test_ingest_rejects_mismatched_map_identity_before_store_access(self) -> None:
        driver = DriverStub()
        other_identity = SourceIdentity.from_connection("neo4j+s://other.example.com", "neo4j")
        mismatched_map = replace(
            schema_map(),
            source_identity=other_identity,
            source_scope=source_scope(other_identity),
        )

        with self.assertRaisesRegex(ValueError, "source identity"):
            ingest_schema_map(
                SemanticStore(driver, store_connection()), source_connection(), mismatched_map
            )

        self.assertEqual(driver.execute_calls, [])
        self.assertEqual(driver.session_instance.write_calls, 0)

    def test_ingest_rejects_mismatched_map_scope_before_store_access(self) -> None:
        driver = DriverStub()
        mismatched_map = replace(schema_map(), source_scope="neo4j:not-the-source-scope")

        with self.assertRaisesRegex(ValueError, "source scope"):
            ingest_schema_map(
                SemanticStore(driver, store_connection()), source_connection(), mismatched_map
            )

        self.assertEqual(driver.execute_calls, [])
        self.assertEqual(driver.session_instance.write_calls, 0)


if __name__ == "__main__":
    unittest.main()
