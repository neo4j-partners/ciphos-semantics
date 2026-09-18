"""Tests for the frozen CIPHOS LPG map contract."""

from __future__ import annotations

import unittest

from ciphos_semantics.semantic_map_contract import (
    CIPHOS_MARKER_LABEL,
    SourceIdentity,
    canonical_label_set,
    normalize_neo4j_uri,
    scoped_id,
    source_scope,
    split_node_labels,
)


class SourceIdentityTests(unittest.TestCase):
    def test_uri_identity_is_normalized_and_credential_free(self) -> None:
        identity = SourceIdentity.from_connection(
            " NEO4J+S://reader:secret@Ops.Example.COM/ ", "neo4j"
        )

        self.assertEqual(identity.uri, "neo4j+s://ops.example.com")
        self.assertNotIn("reader", source_scope(identity))
        self.assertNotIn("secret", source_scope(identity))

    def test_same_database_on_different_uris_has_distinct_identity(self) -> None:
        source = SourceIdentity.from_connection("neo4j+s://ops.example.com", "neo4j")
        store = SourceIdentity.from_connection("neo4j+s://store.example.com", "neo4j")

        self.assertNotEqual(source, store)
        self.assertNotEqual(source_scope(source), source_scope(store))

    def test_scope_and_ids_are_deterministic(self) -> None:
        identity = SourceIdentity.from_connection("neo4j+s://ops.example.com", "neo4j")
        scope = source_scope(identity)

        self.assertEqual(scope, source_scope(identity))
        self.assertEqual(
            scoped_id(scope, "node", CIPHOS_MARKER_LABEL, "Tag"),
            scoped_id(scope, "node", CIPHOS_MARKER_LABEL, "Tag"),
        )

    def test_query_and_fragment_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "query or fragment"):
            normalize_neo4j_uri("neo4j+s://ops.example.com?secret=value")


class LabelContractTests(unittest.TestCase):
    def test_single_label_is_primary(self) -> None:
        self.assertEqual(split_node_labels(("Tag",)), ("Tag", ()))

    def test_marker_is_demoted_without_changing_full_label_set(self) -> None:
        labels = canonical_label_set(["Tag", CIPHOS_MARKER_LABEL])

        self.assertEqual(labels, (CIPHOS_MARKER_LABEL, "Tag"))
        self.assertEqual(split_node_labels(labels), ("Tag", (CIPHOS_MARKER_LABEL,)))

    def test_marker_only_stays_primary(self) -> None:
        self.assertEqual(
            split_node_labels((CIPHOS_MARKER_LABEL,)),
            (CIPHOS_MARKER_LABEL, ()),
        )

    def test_unlabeled_results_have_a_stable_sentinel(self) -> None:
        self.assertEqual(canonical_label_set([]), ("<unlabeled>",))


if __name__ == "__main__":
    unittest.main()
