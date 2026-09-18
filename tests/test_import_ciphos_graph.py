"""Unit tests for the manifest-driven Neo4j projection contract."""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from ciphos_semantics.demo import graph as demo_graph
from ciphos_semantics.import_ciphos_graph import (
    EXCLUDED_RELATIONSHIP_TYPES,
    CsvFile,
    graph_value,
    load_projection_manifest,
    projection_metadata_from_args,
    relationship_batch,
    require_env,
    resolve_source,
    validate_projection,
)


class ProjectionManifestTest(unittest.TestCase):
    def write_manifest(self, directory: Path, **overrides: object) -> Path:
        manifest = {
            "manifest_version": "1.0.0",
            "projection_name": "test-projection",
            "source_layer": "silver",
            "nodes": {
                "include": ["Tag"],
                "exclude": ["TagPropertyValue"],
            },
            "relationships": {
                "include": ["CLASSIFIED_AS"],
                "exclude": sorted(EXCLUDED_RELATIONSHIP_TYPES),
            },
        }
        manifest.update(overrides)
        path = directory / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def write_csv(self, directory: Path, relative_path: str, contents: str) -> None:
        path = directory / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def test_projection_excludes_property_value_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            self.write_csv(directory, "nodes/Tag.csv", "tagNumber\nTAG-1\n")
            self.write_csv(
                directory,
                "nodes/TagPropertyValue.csv",
                "tpvId\nTPV-1\n",
            )
            self.write_csv(
                directory,
                "rels/CLASSIFIED_AS.csv",
                "from,to\nTAG-1,TAG-1\n",
            )
            self.write_csv(
                directory,
                "rels/HAS_PROPERTY_VALUE.csv",
                "from,to\nTAG-1,TPV-1\n",
            )

            manifest = load_projection_manifest(self.write_manifest(directory))
            report = validate_projection(directory, manifest)

            self.assertEqual(report.node_count, 1)
            self.assertEqual(report.relationship_count, 1)
            self.assertEqual([file.graph_name for file in report.node_files], ["Tag"])
            self.assertEqual(
                [file.graph_name for file in report.relationship_files], ["CLASSIFIED_AS"]
            )

    def test_projected_relationship_requires_projected_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            self.write_csv(directory, "nodes/Tag.csv", "tagNumber\nTAG-1\n")
            self.write_csv(
                directory,
                "nodes/TagPropertyValue.csv",
                "tpvId\nTPV-1\n",
            )
            self.write_csv(
                directory,
                "rels/CLASSIFIED_AS.csv",
                "from,to\nTAG-1,TPV-1\n",
            )
            self.write_csv(
                directory,
                "rels/HAS_PROPERTY_VALUE.csv",
                "from,to\nTAG-1,TPV-1\n",
            )

            manifest = load_projection_manifest(self.write_manifest(directory))
            with self.assertRaisesRegex(ValueError, "endpoint IDs are missing"):
                validate_projection(directory, manifest)

    def test_manifest_cannot_reintroduce_property_value_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            path = self.write_manifest(
                directory,
                nodes={
                    "include": ["Tag", "TagPropertyValue"],
                    "exclude": ["OtherExcludedNode"],
                },
            )
            with self.assertRaisesRegex(ValueError, "TagPropertyValue"):
                load_projection_manifest(path)

    def test_import_metadata_requires_reproducible_lineage(self) -> None:
        args = Namespace(
            source_batch_id="silver-batch-001",
            source_snapshot_id="silver-snapshot-001",
            graph_snapshot_id="graph-snapshot-001",
            application_revision="abc123",
            allow_raw_source=False,
        )
        metadata = projection_metadata_from_args(args)
        self.assertEqual(metadata.source_snapshot_id, "silver-snapshot-001")

        args.application_revision = None
        with (
            patch.dict("os.environ", {"CIPHOS_APPLICATION_REVISION": ""}),
            self.assertRaisesRegex(ValueError, "application revision"),
        ):
            projection_metadata_from_args(args)


class IsolationTests(unittest.TestCase):
    def test_importer_refuses_a_pre_rename_operational_environment(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"NEO4J_URI": "neo4j+s://semantic.example.com"},
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "moved to OPS_NEO4J"),
        ):
            require_env("OPS_NEO4J_URI")

    def test_demo_refuses_a_pre_rename_operational_environment(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"NEO4J_DATABASE": "neo4j"},
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "moved to OPS_NEO4J"),
        ):
            demo_graph._require("OPS_NEO4J_DATABASE")

    def test_unrecognised_directory_counts_as_a_raw_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            silver = root / "silver"
            other = root / "other"
            silver.mkdir()
            other.mkdir()
            self.assertEqual((silver, False), resolve_source(None, str(silver)))
            self.assertEqual((silver, False), resolve_source(silver, str(silver)))
            self.assertEqual((other, True), resolve_source(other, str(silver)))


class ProjectionValueTests(unittest.TestCase):
    def test_relationship_identity_ignores_properties(self) -> None:
        csv_file = CsvFile(Path("rels/CONNECTED_TO.csv"), "CONNECTED_TO")
        first = relationship_batch(
            csv_file, [{"from": "A", "to": "B", "connectionType": "ethernet"}]
        )
        second = relationship_batch(
            csv_file, [{"from": "A", "to": "B", "connectionType": "serial"}]
        )
        self.assertEqual(first[0]["edgeKey"], second[0]["edgeKey"])

    def test_identifier_shaped_values_stay_strings(self) -> None:
        self.assertEqual("00123", graph_value("00123", coerce=False))
        self.assertEqual(123, graph_value("123"))
        self.assertIs(True, graph_value("true"))
        row = {"from": "A", "to": "B", "reportingDeadlineHours": "72", "zoneId": "12"}
        properties = relationship_batch(
            CsvFile(Path("rels/REPORTED_UNDER.csv"), "REPORTED_UNDER"), [row]
        )[0]["properties"]
        self.assertEqual(72, properties["reportingDeadlineHours"])
        self.assertEqual("12", properties["zoneId"])


if __name__ == "__main__":
    unittest.main()
