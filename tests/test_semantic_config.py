"""Unit tests for semantic-store configuration."""

from __future__ import annotations

import unittest

from ciphos_semantics.semantic_config import (
    OperationalNeo4jConnection,
    SemanticStoreNeo4jConnection,
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

    def test_connection_repr_does_not_expose_secrets(self) -> None:
        source = operational_connection()
        store = store_connection()

        self.assertNotIn("operational-secret", repr(source))
        self.assertNotIn("store-secret", repr(store))


if __name__ == "__main__":
    unittest.main()
