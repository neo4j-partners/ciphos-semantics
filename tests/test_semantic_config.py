"""Unit tests for semantic-store configuration and target guards."""

from __future__ import annotations

import unittest

from neo4j import RoutingControl

from ciphos_semantics.semantic_config import (
    OPERATIONAL_GRAPH_LABELS,
    OPERATIONAL_LABEL_CHECK_CYPHER,
    OperationalNeo4jConnection,
    SemanticStoreNeo4jConnection,
    assert_no_operational_graph_nodes,
    assert_safe_semantic_store_target,
    load_operational_connection,
    load_semantic_store_connection,
)


def operational_connection() -> OperationalNeo4jConnection:
    return OperationalNeo4jConnection(
        uri="neo4j+s://reader:operational-secret@ops.example.com",
        username="reader",
        password="operational-secret",
        database="neo4j",
    )


def store_connection() -> SemanticStoreNeo4jConnection:
    return SemanticStoreNeo4jConnection(
        uri="neo4j+s://writer:store-secret@store.example.com",
        username="writer",
        password="store-secret",
        database="neo4j",
    )


class DriverStub:
    def __init__(self, count: int) -> None:
        self.count = count
        self.calls: list[dict[str, object]] = []

    def execute_query(self, **kwargs: object) -> tuple[list[dict[str, int]], None, None]:
        self.calls.append(kwargs)
        return [{"operational_node_count": self.count}], None, None


class SemanticConfigTests(unittest.TestCase):
    def test_loads_distinct_operational_and_store_namespaces(self) -> None:
        environment = {
            "OPS_NEO4J_URI": "neo4j+s://ops.example.com",
            "OPS_NEO4J_USERNAME": "reader",
            "OPS_NEO4J_PASSWORD": "read-secret",
            "OPS_NEO4J_DATABASE": "neo4j",
            "NEO4J_URI": "neo4j+s://store.example.com",
            "NEO4J_USERNAME": "writer",
            "NEO4J_PASSWORD": "write-secret",
            "NEO4J_DATABASE": "neo4j",
        }

        source = load_operational_connection(environment)
        store = load_semantic_store_connection(environment)

        self.assertEqual(source.username, "reader")
        self.assertEqual(store.username, "writer")
        self.assertNotEqual(source.identity, store.identity)

    def test_stale_pre_rename_refusal_covers_each_operational_name(self) -> None:
        complete = {
            "OPS_NEO4J_URI": "neo4j+s://ops.example.com",
            "OPS_NEO4J_USERNAME": "reader",
            "OPS_NEO4J_PASSWORD": "read-secret",
            "OPS_NEO4J_DATABASE": "neo4j",
            "NEO4J_URI": "neo4j+s://store.example.com",
            "NEO4J_USERNAME": "writer",
            "NEO4J_PASSWORD": "write-secret",
            "NEO4J_DATABASE": "metadata",
        }
        pairs = (
            ("OPS_NEO4J_URI", "NEO4J_URI"),
            ("OPS_NEO4J_USERNAME", "NEO4J_USERNAME"),
            ("OPS_NEO4J_PASSWORD", "NEO4J_PASSWORD"),
            ("OPS_NEO4J_DATABASE", "NEO4J_DATABASE"),
        )

        for operational_name, legacy_name in pairs:
            with self.subTest(operational_name=operational_name):
                environment = dict(complete)
                environment[operational_name] = ""
                with self.assertRaisesRegex(ValueError, operational_name) as error:
                    load_operational_connection(environment)
                self.assertIn(legacy_name, str(error.exception))
                self.assertNotIn("read-secret", str(error.exception))
                self.assertNotIn("write-secret", str(error.exception))

    def test_connection_repr_and_target_errors_do_not_expose_secrets(self) -> None:
        source = operational_connection()
        store = store_connection()

        self.assertNotIn("operational-secret", repr(source))
        self.assertNotIn("store-secret", repr(store))
        same_target = SemanticStoreNeo4jConnection(
            uri=source.uri,
            username="reader",
            password="operational-secret",
            database=source.database,
        )
        with self.assertRaises(ValueError) as error:
            assert_safe_semantic_store_target(source, same_target)
        self.assertNotIn("operational-secret", str(error.exception))

    def test_same_database_name_on_different_uris_is_safe(self) -> None:
        assert_safe_semantic_store_target(operational_connection(), store_connection())

    def test_candidate_identity_uses_operational_uri(self) -> None:
        source = operational_connection()
        candidate_store = SemanticStoreNeo4jConnection(
            uri=source.uri,
            username="writer",
            password="store-secret",
            database="candidate",
        )

        with self.assertRaisesRegex(ValueError, "candidate"):
            assert_safe_semantic_store_target(
                source,
                candidate_store,
                candidate_database="candidate",
            )

    def test_operational_label_check_uses_read_routing_and_rejects_target(self) -> None:
        driver = DriverStub(count=2)

        with self.assertRaisesRegex(ValueError, "operational graph nodes"):
            assert_no_operational_graph_nodes(driver, store_connection())

        self.assertEqual(driver.calls[0]["query_"], OPERATIONAL_LABEL_CHECK_CYPHER)
        self.assertEqual(
            driver.calls[0]["parameters_"],
            {"operational_labels": list(OPERATIONAL_GRAPH_LABELS)},
        )
        self.assertEqual(driver.calls[0]["routing_"], RoutingControl.READ)
        self.assertNotIn(":CiphosEntity", OPERATIONAL_LABEL_CHECK_CYPHER)

    def test_empty_target_passes_operational_label_check(self) -> None:
        assert_no_operational_graph_nodes(DriverStub(count=0), store_connection())


if __name__ == "__main__":
    unittest.main()
