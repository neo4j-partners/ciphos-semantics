"""Tests for CIPHOS semantic-map command composition."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ciphos_semantics.semantic_cli import resolve_source_scope


class StoreStub:
    def __init__(self, scopes: tuple[str, ...]) -> None:
        self.scopes = scopes
        self.calls = 0

    def list_source_scopes(self) -> tuple[str, ...]:
        self.calls += 1
        return self.scopes


class SemanticCliTests(unittest.TestCase):
    def test_explicit_scope_never_reads_operational_or_store_discovery_state(self) -> None:
        store = StoreStub(("neo4j:other",))

        with patch(
            "ciphos_semantics.semantic_cli.load_operational_connection",
            side_effect=AssertionError("operational configuration must not be read"),
        ):
            scope = resolve_source_scope(store, "neo4j:requested")

        self.assertEqual(scope, "neo4j:requested")
        self.assertEqual(store.calls, 0)

    def test_unique_persisted_scope_is_auto_detected(self) -> None:
        self.assertEqual(resolve_source_scope(StoreStub(("neo4j:one",))), "neo4j:one")

    def test_missing_or_ambiguous_scope_is_actionable(self) -> None:
        with self.assertRaisesRegex(ValueError, "no CIPHOS LPG map"):
            resolve_source_scope(StoreStub(()))
        with self.assertRaisesRegex(ValueError, "multiple CIPHOS LPG maps"):
            resolve_source_scope(StoreStub(("neo4j:a", "neo4j:b")))


if __name__ == "__main__":
    unittest.main()
