"""Tests for metadata-only extraction of the CIPHOS Neo4j schema map."""

from __future__ import annotations

import unittest
from copy import deepcopy
from typing import Any

from neo4j import RoutingControl
from neo4j.exceptions import Neo4jError
from tests.semantic_fixtures import ENDPOINTS, SCHEMA_METADATA, SOURCE_DATABASE, SOURCE_URI

from ciphos_semantics.neo4j_schema_extract import (
    CONSTRAINTS_QUERY,
    ENDPOINTS_QUERY,
    INDEXES_QUERY,
    LABELS_QUERY,
    NODE_PROPERTIES_QUERY,
    RELATIONSHIP_PROPERTIES_QUERY,
    RELATIONSHIP_TYPES_QUERY,
    REQUIRED_SCHEMA_QUERIES,
    SCHEMA_QUERY_ALLOWLIST,
    SchemaExtractionError,
    build_schema_map,
    extract_schema_map,
)
from ciphos_semantics.semantic_map_contract import SourceIdentity


class SourceDriver:
    """Fake source driver that exposes schema fixtures and records every query."""

    def __init__(self, *, fail_query: str | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_query = fail_query
        self.results = {
            LABELS_QUERY: SCHEMA_METADATA["labels"],
            RELATIONSHIP_TYPES_QUERY: SCHEMA_METADATA["relationship_types"],
            NODE_PROPERTIES_QUERY: SCHEMA_METADATA["node_properties"],
            RELATIONSHIP_PROPERTIES_QUERY: SCHEMA_METADATA["relationship_properties"],
            CONSTRAINTS_QUERY: SCHEMA_METADATA["constraints"],
            INDEXES_QUERY: SCHEMA_METADATA["indexes"],
            ENDPOINTS_QUERY: ENDPOINTS,
        }

    def execute_query(self, query_: str, **kwargs: Any) -> tuple[list[dict[str, Any]], None, None]:
        self.calls.append((query_, kwargs))
        if query_ not in SCHEMA_QUERY_ALLOWLIST:
            raise AssertionError(f"Unexpected query: {query_}")
        if query_ == self.fail_query:
            raise Neo4jError("permission denied")
        return deepcopy(self.results[query_]), None, None


class Neo4jSchemaExtractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = SourceIdentity.from_connection(SOURCE_URI, SOURCE_DATABASE)

    def test_extracts_only_the_exact_allowlist_with_read_routing(self) -> None:
        driver = SourceDriver()

        schema_map = extract_schema_map(driver, self.identity)

        self.assertTrue(schema_map.endpoints_available)
        self.assertEqual({query for query, _ in driver.calls}, SCHEMA_QUERY_ALLOWLIST)
        self.assertEqual(len(driver.calls), 7)
        for _, kwargs in driver.calls:
            self.assertEqual(kwargs["database_"], SOURCE_DATABASE)
            self.assertEqual(kwargs["routing_"], RoutingControl.READ)

    def test_builds_deterministic_records_and_real_property_flags(self) -> None:
        schema_map = build_schema_map(
            self.identity,
            SCHEMA_METADATA,
            ENDPOINTS,
            endpoints_available=True,
        )

        node_labels = {
            (row["label"], tuple(row.get("additional_labels", []))) for row in schema_map.nodes
        }
        self.assertIn(("Tag", ("CiphosEntity",)), node_labels)
        self.assertIn(("CiphosEntity", ()), node_labels)
        self.assertIn(("<unlabeled>", ()), node_labels)

        properties = {(row["name"], row["type"]): row for row in schema_map.properties}
        self.assertTrue(properties[("tagNumber", "STRING")]["unique"])
        self.assertTrue(properties[("tagNumber", "STRING")]["indexed"])
        self.assertTrue(properties[("documentNumber", "STRING")]["existence"])
        confidence = properties[("confidence", "FLOAT | INTEGER")]
        self.assertTrue(confidence["indexed"])
        self.assertTrue(confidence["existence"])
        self.assertFalse(confidence["unique"])
        self.assertTrue(confidence["nullable"])
        self.assertEqual(len(schema_map.properties), 7)
        repeated_map = build_schema_map(
            self.identity, SCHEMA_METADATA, ENDPOINTS, endpoints_available=True
        )
        self.assertEqual(schema_map, repeated_map)
        self.assertTrue(
            all("source_scope" not in record.metadata for record in schema_map.records())
        )

    def test_ambiguous_endpoint_label_expands_to_every_matching_label_set(self) -> None:
        schema_map = build_schema_map(
            self.identity,
            SCHEMA_METADATA,
            ENDPOINTS,
            endpoints_available=True,
        )
        nodes_by_id = {row["id"]: row for row in schema_map.nodes}
        relationship = next(
            row for row in schema_map.relationships if row["type"] == "HAS_VULNERABILITY"
        )
        source_ids = {
            edge.target_id
            for edge in schema_map.edges
            if edge.source_id == relationship["id"] and edge.kind == "HAS_SOURCE_NODE"
        }

        self.assertEqual(
            {
                (
                    nodes_by_id[node_id]["label"],
                    tuple(nodes_by_id[node_id].get("additional_labels", [])),
                )
                for node_id in source_ids
            },
            {
                ("Tag", ()),
                ("Archived", ("Tag",)),
                ("Tag", ("CiphosEntity",)),
            },
        )

    def test_endpoint_permission_failure_is_optional_but_required_queries_are_not(self) -> None:
        optional_driver = SourceDriver(fail_query=ENDPOINTS_QUERY)
        schema_map = extract_schema_map(optional_driver, self.identity)

        self.assertFalse(schema_map.endpoints_available)
        self.assertFalse(any(edge.kind == "HAS_SOURCE_NODE" for edge in schema_map.edges))

        for query in (CONSTRAINTS_QUERY, INDEXES_QUERY):
            with self.subTest(query=query):
                required_driver = SourceDriver(fail_query=query)
                with self.assertRaisesRegex(SchemaExtractionError, "constraints and indexes"):
                    extract_schema_map(required_driver, self.identity)

    def test_unusable_visualization_rows_are_recorded_as_unavailable_endpoints(self) -> None:
        driver = SourceDriver()
        driver.results[ENDPOINTS_QUERY] = [
            {
                "relationship_type": None,
                "source_label": None,
                "target_label": None,
            }
        ]

        schema_map = extract_schema_map(driver, self.identity)

        self.assertFalse(schema_map.endpoints_available)
        self.assertFalse(any(edge.kind == "HAS_SOURCE_NODE" for edge in schema_map.edges))

    def test_rejects_malformed_property_rows_with_an_actionable_error(self) -> None:
        malformed = deepcopy(SCHEMA_METADATA)
        malformed["node_properties"][0]["mandatory"] = "false"

        with self.assertRaisesRegex(SchemaExtractionError, "mandatory must be a boolean"):
            build_schema_map(self.identity, malformed, ENDPOINTS, endpoints_available=True)

    def test_constraints_never_invent_property_records(self) -> None:
        metadata = deepcopy(SCHEMA_METADATA)
        metadata["constraints"].append(
            {
                "entityType": "NODE",
                "labelsOrTypes": ["Tag"],
                "properties": ["absentProperty"],
                "type": "UNIQUENESS",
            }
        )

        schema_map = build_schema_map(self.identity, metadata, ENDPOINTS, endpoints_available=True)

        self.assertNotIn("absentProperty", {row["name"] for row in schema_map.properties})

    def test_retains_propertyless_node_and_relationship_types_without_properties(self) -> None:
        metadata = deepcopy(SCHEMA_METADATA)
        metadata["node_properties"].append(
            {
                "nodeType": ":`CiphosEntity`:`PropertylessNode`",
                "nodeLabels": ["CiphosEntity", "PropertylessNode"],
                "propertyName": None,
                "propertyTypes": None,
                "mandatory": False,
            }
        )
        metadata["relationship_properties"].append(
            {
                "relType": ":`PROPERTYLESS_RELATIONSHIP`",
                "propertyName": None,
                "propertyTypes": None,
                "mandatory": False,
            }
        )

        schema_map = build_schema_map(self.identity, metadata, ENDPOINTS, endpoints_available=True)

        self.assertIn(
            ("PropertylessNode", ("CiphosEntity",)),
            {(row["label"], tuple(row.get("additional_labels", []))) for row in schema_map.nodes},
        )
        self.assertIn(
            "PROPERTYLESS_RELATIONSHIP",
            {row["type"] for row in schema_map.relationships},
        )
        self.assertEqual(len(schema_map.properties), 7)

    def test_rejects_partially_populated_propertyless_sentinel_rows(self) -> None:
        cases = (
            (
                {
                    "relType": ":`INVALID_RELATIONSHIP`",
                    "propertyName": "presentName",
                    "propertyTypes": None,
                    "mandatory": False,
                },
                "propertyTypes must be a collection",
            ),
            (
                {
                    "relType": ":`INVALID_RELATIONSHIP`",
                    "propertyName": None,
                    "propertyTypes": ["STRING"],
                    "mandatory": False,
                },
                "propertyName must not be empty",
            ),
        )
        for row, message in cases:
            with self.subTest(row=row):
                metadata = deepcopy(SCHEMA_METADATA)
                metadata["relationship_properties"].append(row)
                with self.assertRaisesRegex(SchemaExtractionError, message):
                    build_schema_map(self.identity, metadata, ENDPOINTS, endpoints_available=True)

    def test_ignores_propertyless_node_and_relationship_lookup_indexes(self) -> None:
        metadata = deepcopy(SCHEMA_METADATA)
        metadata["indexes"].extend(
            [
                {
                    "entityType": "NODE",
                    "labelsOrTypes": None,
                    "properties": [],
                    "type": "LOOKUP",
                },
                {
                    "entityType": "RELATIONSHIP",
                    "labelsOrTypes": None,
                    "properties": None,
                    "type": "LOOKUP",
                },
            ]
        )

        schema_map = build_schema_map(self.identity, metadata, ENDPOINTS, endpoints_available=True)

        self.assertEqual(len(schema_map.properties), 7)

    def test_required_query_map_contains_six_queries_plus_optional_visualization(self) -> None:
        self.assertEqual(set(REQUIRED_SCHEMA_QUERIES), {
            "labels",
            "relationship_types",
            "node_properties",
            "relationship_properties",
            "constraints",
            "indexes",
        })
        self.assertEqual(len(SCHEMA_QUERY_ALLOWLIST), 7)


if __name__ == "__main__":
    unittest.main()
