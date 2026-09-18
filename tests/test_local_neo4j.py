"""Tests for opt-in, runtime-only Docker Compose Neo4j settings."""

from __future__ import annotations

import unittest

from ciphos_semantics.local_neo4j import configure_local_neo4j


class LocalNeo4jTests(unittest.TestCase):
    def test_remote_configuration_is_untouched_without_explicit_flag(self) -> None:
        environment = {
            "OPS_NEO4J_URI": "neo4j+s://ops.example.com",
            "NEO4J_URI": "neo4j+s://store.example.com",
        }

        self.assertFalse(configure_local_neo4j(environment))
        self.assertEqual(environment["OPS_NEO4J_URI"], "neo4j+s://ops.example.com")
        self.assertEqual(environment["NEO4J_URI"], "neo4j+s://store.example.com")

    def test_explicit_flag_replaces_both_connections_only_in_runtime_mapping(self) -> None:
        environment = {
            "NEO4J_LOCAL": "true",
            "CIPHOS_TEST_NEO4J_PASSWORD": "local-password",
            "OPS_NEO4J_URI": "neo4j+s://ops.example.com",
            "NEO4J_URI": "neo4j+s://store.example.com",
        }

        self.assertTrue(configure_local_neo4j(environment))
        self.assertEqual(environment["OPS_NEO4J_URI"], "bolt://127.0.0.1:17688")
        self.assertEqual(environment["NEO4J_URI"], "bolt://127.0.0.1:17689")
        self.assertEqual(environment["OPS_NEO4J_PASSWORD"], "local-password")
        self.assertEqual(environment["NEO4J_PASSWORD"], "local-password")


if __name__ == "__main__":
    unittest.main()
