"""Compatibility checks for the pinned, experimental NeoCarta LPG models."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import unittest
import warnings
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ciphos_semantics.semantic_map_contract import (  # noqa: E402
    NEOCARTA_VERSION,
    SchemaMap,
    SemanticEdge,
    SemanticRecord,
    SourceIdentity,
    source_scope,
)

NEOCARTA_AVAILABLE = importlib.util.find_spec("neocarta") is not None
EXPECTED_WARNING = (
    "LPG data model components are an in-progress feature. "
    "There is no application in the current library version."
)


@unittest.skipUnless(
    NEOCARTA_AVAILABLE,
    f"run the isolated NeoCarta {NEOCARTA_VERSION} contract-test target",
)
class NeocartaLpgContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cls.lpg = importlib.import_module("neocarta.data_model.schema.lpg")
        cls.import_warnings = caught

    def test_import_emits_the_expected_in_progress_warning(self) -> None:
        self.assertTrue(
            any(
                item.category is UserWarning and str(item.message) == EXPECTED_WARNING
                for item in self.import_warnings
            )
        )

    def test_node_model_fields_match_the_pinned_contract(self) -> None:
        expected_fields = {
            "Database": {
                "id",
                "name",
                "platform",
                "service",
                "description",
                "embedding",
            },
            "Schema": {"id", "name", "description", "embedding"},
            "Node": {"id", "label", "additional_labels", "description", "embedding"},
            "Relationship": {"id", "type", "description", "embedding"},
            "Property": {
                "id",
                "name",
                "type",
                "description",
                "unique",
                "nullable",
                "indexed",
                "existence",
                "embedding",
            },
        }

        for model_name, field_names in expected_fields.items():
            with self.subTest(model=model_name):
                model = getattr(self.lpg, model_name)
                self.assertEqual(set(model.model_fields), field_names)

    def test_property_defaults_cannot_stand_in_for_unknown_evidence(self) -> None:
        value = self.lpg.Property(id="property-1", name="tagNumber").model_dump()

        self.assertIs(value["unique"], False)
        self.assertIs(value["nullable"], True)
        self.assertIs(value["indexed"], False)
        self.assertIs(value["existence"], False)

    def test_representative_canonical_records_validate(self) -> None:
        records = {
            "Database": {"id": "database-1", "name": "neo4j", "service": "NEO4J"},
            "Schema": {"id": "schema-1", "name": "default"},
            "Node": {
                "id": "node-1",
                "label": "Tag",
                "additional_labels": ["CiphosEntity"],
            },
            "Relationship": {"id": "relationship-1", "type": "CLASSIFIED_AS"},
            "Property": {
                "id": "property-1",
                "name": "tagNumber",
                "type": "STRING",
                "unique": True,
                "nullable": False,
                "indexed": True,
                "existence": False,
            },
        }

        for kind, record in records.items():
            with self.subTest(kind=kind):
                validated = getattr(self.lpg, kind).model_validate(record)
                for name, value in record.items():
                    self.assertEqual(validated.model_dump()[name], value)

    def test_all_edge_models_accept_the_frozen_identifiers(self) -> None:
        edge_values = {
            "HasSchema": {"database_id": "database-1", "schema_id": "schema-1"},
            "HasNode": {"schema_id": "schema-1", "node_id": "node-1"},
            "HasRelationship": {
                "schema_id": "schema-1",
                "relationship_id": "relationship-1",
            },
            "HasSourceNode": {
                "relationship_id": "relationship-1",
                "node_id": "node-1",
            },
            "HasTargetNode": {
                "relationship_id": "relationship-1",
                "node_id": "node-2",
            },
            "NodeHasProperty": {"source_id": "node-1", "property_id": "property-1"},
            "RelationshipHasProperty": {
                "source_id": "relationship-1",
                "property_id": "property-2",
            },
        }

        for model_name, values in edge_values.items():
            with self.subTest(model=model_name):
                model = getattr(self.lpg, model_name)
                self.assertEqual(model.model_validate(values).model_dump(), values)

    def test_neocarta_drops_scope_but_persistence_reattaches_it(self) -> None:
        raw = {"id": "node-1", "label": "Tag", "source_scope": "neo4j:scope"}
        validated = self.lpg.Node.model_validate(raw).model_dump(exclude_none=True)
        self.assertNotIn("source_scope", validated)

        identity = SourceIdentity.from_connection("neo4j+s://ops.example.com", "neo4j")
        scope = source_scope(identity)
        schema_map = SchemaMap(
            source_identity=identity,
            source_scope=scope,
            database={"id": "database-1", "name": "neo4j", "service": "NEO4J"},
            schema={"id": "schema-1", "name": "default"},
            nodes=(validated,),
            relationships=(),
            properties=(),
            edges=(SemanticEdge("database-1", "HAS_SCHEMA", "schema-1"),),
            endpoints_available=False,
        )

        persisted = schema_map.persisted_record(SemanticRecord("Node", validated))
        self.assertEqual(persisted["source_scope"], scope)


if __name__ == "__main__":
    unittest.main()
