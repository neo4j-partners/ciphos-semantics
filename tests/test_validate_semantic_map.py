"""Tests for pure persisted CIPHOS semantic-map drift comparison."""

from __future__ import annotations

import unittest

from ciphos_semantics.semantic_map_contract import (
    SchemaMap,
    SemanticContext,
    SemanticEdge,
    SemanticRecord,
    SourceIdentity,
)
from ciphos_semantics.validate_semantic_map import (
    SemanticMapDriftError,
    compare_semantic_map,
    context_from_schema_map,
    validate_semantic_map,
)


def build_schema_map() -> SchemaMap:
    """Create a minimal canonical map without requiring Neo4j or extraction."""
    identity = SourceIdentity.from_connection("neo4j+s://ops.example.com", "neo4j")
    database = {"id": "database-id", "name": "neo4j", "service": "NEO4J"}
    schema = {"id": "schema-id", "name": "default"}
    node = {"id": "node-id", "label": "Tag"}
    relationship = {"id": "relationship-id", "type": "REFERENCES"}
    property_row = {
        "id": "property-id",
        "name": "tagNumber",
        "type": "STRING",
        "nullable": False,
        "unique": True,
        "indexed": True,
        "existence": True,
    }
    return SchemaMap(
        source_identity=identity,
        source_scope="neo4j:test-scope",
        database=database,
        schema=schema,
        nodes=(node,),
        relationships=(relationship,),
        properties=(property_row,),
        edges=(
            SemanticEdge("database-id", "HAS_SCHEMA", "schema-id"),
            SemanticEdge("schema-id", "HAS_NODE", "node-id"),
            SemanticEdge("schema-id", "HAS_RELATIONSHIP", "relationship-id"),
            SemanticEdge("node-id", "HAS_PROPERTY", "property-id"),
        ),
        endpoints_available=True,
    )


class SemanticMapValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema_map = build_schema_map()

    def test_matching_context_has_no_drift(self) -> None:
        report = compare_semantic_map(self.schema_map, context_from_schema_map(self.schema_map))

        self.assertTrue(report.is_clean)
        self.assertEqual(report.as_dict()["missing"], {"records": [], "edges": []})

    def test_reports_missing_unexpected_and_changed_records_and_edges(self) -> None:
        expected = context_from_schema_map(self.schema_map)
        actual_records = list(expected.records)
        actual_records.remove(next(record for record in actual_records if record.id == "node-id"))
        actual_records.append(SemanticRecord("Node", {"id": "other-node", "label": "Other"}))
        actual_records = [
            SemanticRecord("Property", {**record.metadata, "name": "different"})
            if record.id == "property-id"
            else record
            for record in actual_records
        ]
        actual = SemanticContext(
            source_scope="neo4j:other-scope",
            source_identity=SourceIdentity.from_connection("neo4j+s://other.example.com", "other"),
            endpoints_available=False,
            records=tuple(actual_records),
            edges=(SemanticEdge("database-id", "HAS_SCHEMA", "schema-id"),),
        )

        report = compare_semantic_map(self.schema_map, actual).as_dict()

        self.assertEqual([row["id"] for row in report["missing"]["records"]], ["node-id"])
        self.assertEqual(
            [row["id"] for row in report["unexpected"]["records"]], ["other-node"]
        )
        self.assertEqual(report["changed"]["records"][0]["id"], "property-id")
        self.assertEqual(len(report["missing"]["edges"]), 3)
        self.assertEqual(report["changed"]["source_scope"]["actual"], "neo4j:other-scope")
        self.assertFalse(report["changed"]["endpoints_available"]["actual"])

    def test_validation_error_redacts_accidental_uri_credentials_and_record_secrets(self) -> None:
        expected = context_from_schema_map(self.schema_map)
        actual = SemanticContext(
            source_scope=expected.source_scope,
            source_identity=SourceIdentity("neo4j+s://reader:secret@other.example.com", "neo4j"),
            endpoints_available=expected.endpoints_available,
            records=(
                SemanticRecord(
                    "Database",
                    {
                        "id": "database-id",
                        "password": "also-secret",
                        "source_uri": "neo4j+s://reader:secret@other.example.com",
                    },
                ),
            ),
            edges=expected.edges,
        )

        with self.assertRaises(SemanticMapDriftError) as caught:
            validate_semantic_map(self.schema_map, actual)

        message = str(caught.exception)
        self.assertNotIn("secret", message)
        self.assertNotIn("reader", message)
        self.assertIn("<redacted>", message)
        self.assertIn("neo4j+s://other.example.com", message)

    def test_duplicate_record_ids_are_rejected_before_comparison(self) -> None:
        expected = context_from_schema_map(self.schema_map)
        duplicate = SemanticContext(
            source_scope=expected.source_scope,
            source_identity=expected.source_identity,
            endpoints_available=True,
            records=(
                SemanticRecord("Node", {"id": "duplicate", "label": "Tag"}),
                SemanticRecord("Node", {"id": "duplicate", "label": "Document"}),
            ),
            edges=(),
        )

        with self.assertRaisesRegex(ValueError, "duplicate record id"):
            compare_semantic_map(self.schema_map, duplicate)


if __name__ == "__main__":
    unittest.main()
