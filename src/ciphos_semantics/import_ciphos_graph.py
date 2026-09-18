"""Validate and import CIPHOS CSV nodes and relationships into Neo4j."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from ciphos_semantics import contract
from ciphos_semantics.graph_projection_manifest import build_default_manifest

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent
DEFAULT_DATA_DIR = PROJECT_DIR / "ciphos_data" / "csv"
DEFAULT_MANIFEST_PATH = SCRIPT_DIR / "graph_projection_manifest.py"
NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
INTEGER_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)\.[0-9]+$")
IDENTIFIER_COLUMN_PATTERN = re.compile(r"(?:^|[a-z0-9])(?:Id|Ids|Number|Code)$")
# The frozen contract is the only place these lists are written down.
EXCLUDED_NODE_TYPES = frozenset(contract.excluded_nodes())
EXCLUDED_RELATIONSHIP_TYPES = frozenset(contract.excluded_relationships())


@dataclass(frozen=True)
class CsvFile:
    """A validated CSV file and the graph type it maps to."""

    path: Path
    graph_name: str
    id_column: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    """The result of validating the node and relationship export."""

    node_files: Sequence[CsvFile]
    relationship_files: Sequence[CsvFile]
    node_count: int
    relationship_count: int


@dataclass(frozen=True)
class ProjectionManifest:
    """Versioned description of the datasets eligible for a graph projection."""

    version: str
    name: str
    source_layer: str
    node_types: frozenset[str]
    excluded_node_types: frozenset[str]
    relationship_types: frozenset[str]
    excluded_relationship_types: frozenset[str]
    path: Path


@dataclass(frozen=True)
class ProjectionMetadata:
    """Lineage attached to one candidate or active graph snapshot."""

    source_batch_id: str
    source_snapshot_id: str
    graph_snapshot_id: str
    application_revision: str
    candidate: bool
    raw_source: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help=(
            "Local materialization of a published Silver snapshot containing nodes/ "
            "and rels/ (default: CIPHOS_SILVER_SNAPSHOT_DIR, then CIPHOS_DATA_DIR)."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="External versioned graph projection manifest JSON (default: bundled v1.0.0).",
    )
    parser.add_argument(
        "--source-batch-id",
        help="Published Silver batch ID (default: CIPHOS_SOURCE_BATCH_ID).",
    )
    parser.add_argument(
        "--source-snapshot-id",
        help="Immutable Silver snapshot ID (default: CIPHOS_SOURCE_SNAPSHOT_ID).",
    )
    parser.add_argument(
        "--graph-snapshot-id",
        help="Unique graph snapshot ID (default: CIPHOS_GRAPH_SNAPSHOT_ID).",
    )
    parser.add_argument(
        "--application-revision",
        help="Application revision used to build the graph (default: CIPHOS_APPLICATION_REVISION).",
    )
    parser.add_argument(
        "--candidate",
        action="store_true",
        help="Mark this build as a candidate; validate it before activation.",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Mark a successfully validated candidate snapshot as active.",
    )
    parser.add_argument(
        "--database",
        help="Candidate database to build into (default: CIPHOS_CANDIDATE_DATABASE).",
    )
    parser.add_argument(
        "--allow-raw-source",
        action="store_true",
        help=(
            "Project the raw Bronze-level export instead of a published Silver "
            "materialization, and record that fact on the projection node."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Rows per Neo4j transaction (default: IMPORT_BATCH_SIZE or 1000).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate CSV mappings without connecting to Neo4j.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete only existing :CiphosEntity nodes before importing.",
    )
    parser.add_argument(
        "--counts", action="store_true", help="Report CIPHOS graph counts and exit."
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Compare graph counts, labels, and types with the CSV export.",
    )
    return parser.parse_args()


def resolve_source(data_dir: Path | None, silver_dir: str) -> tuple[Path, bool]:
    """Resolve the source directory and whether it is a published Silver snapshot.

    Lineage has to record what was really read, so an unrecognised directory
    counts as a raw export rather than being assumed to be Silver.
    """
    silver = Path(silver_dir).resolve() if silver_dir else None
    if data_dir is not None:
        resolved = data_dir.resolve()
        return resolved, resolved != silver
    if silver is not None:
        return silver, False
    return Path(os.getenv("CIPHOS_DATA_DIR", DEFAULT_DATA_DIR)).resolve(), True


def resolve_database(
    requested: str | None, serving_database: str, *, read_only: bool
) -> str:
    """Pick the target database, refusing to build a candidate over the served one."""
    if read_only:
        return requested or serving_database
    database = (requested or os.getenv("CIPHOS_CANDIDATE_DATABASE", "")).strip()
    if not database:
        raise ValueError(
            "A candidate import needs its own database. Pass --database or set "
            f"CIPHOS_CANDIDATE_DATABASE to something other than {serving_database!r}."
        )
    if database == serving_database:
        raise ValueError(
            f"Candidate database {database!r} is the active serving database. "
            "Build candidates in isolation, then activate."
        )
    return database


def load_environment() -> None:
    """Load local overrides without replacing explicitly exported variables."""
    load_dotenv(PROJECT_DIR / ".env", override=False)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("<"):
        raise ValueError(f"Set {name} in {PROJECT_DIR / '.env'} before importing.")
    return value


def as_cypher_name(value: str, path: Path) -> str:
    if not NAME_PATTERN.fullmatch(value):
        raise ValueError(f"Unsafe graph name {value!r} derived from {path}.")
    return value


def manifest_type_set(
    document: dict[str, Any], section: str, key: str, path: Path
) -> frozenset[str]:
    value = document.get(section, {}).get(key)
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"Manifest {path} requires a non-empty {section}.{key} list.")
    if not all(isinstance(name, str) and NAME_PATTERN.fullmatch(name) for name in value):
        raise ValueError(f"Manifest {path} has an unsafe name in {section}.{key}.")
    names = frozenset(value)
    if len(names) != len(value):
        raise ValueError(f"Manifest {path} has duplicate names in {section}.{key}.")
    return names


def load_projection_manifest(path: Path | None = None) -> ProjectionManifest:
    """Load and validate a manifest before inspecting any projected CSV files."""
    if path is None:
        document: Any = build_default_manifest()
        path = DEFAULT_MANIFEST_PATH
    else:
        try:
            with path.open(encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Unable to read projection manifest {path}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError(f"Projection manifest {path} must contain a JSON object.")

    version = document.get("manifest_version")
    name = document.get("projection_name")
    source_layer = document.get("source_layer")
    if not isinstance(version, str) or not SEMVER_PATTERN.fullmatch(version):
        raise ValueError(f"Manifest {path} has an invalid manifest_version; use x.y.z.")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Manifest {path} requires projection_name.")
    if source_layer != "silver":
        raise ValueError(
            f"Manifest {path} must declare source_layer 'silver', not {source_layer!r}."
        )

    node_types = manifest_type_set(document, "nodes", "include", path)
    excluded_node_types = manifest_type_set(document, "nodes", "exclude", path)
    relationship_types = manifest_type_set(document, "relationships", "include", path)
    excluded_relationship_types = manifest_type_set(
        document, "relationships", "exclude", path
    )
    if node_types & excluded_node_types:
        raise ValueError(f"Manifest {path} includes and excludes the same node type.")
    if relationship_types & excluded_relationship_types:
        raise ValueError(f"Manifest {path} includes and excludes the same relationship type.")
    if EXCLUDED_NODE_TYPES & node_types:
        raise ValueError("TagPropertyValue instances cannot be included in this projection.")
    if EXCLUDED_RELATIONSHIP_TYPES & relationship_types:
        raise ValueError("Tag-property value relationships cannot be included in this projection.")
    if not excluded_node_types >= EXCLUDED_NODE_TYPES:
        raise ValueError("Manifest must explicitly exclude TagPropertyValue.")
    if not excluded_relationship_types >= EXCLUDED_RELATIONSHIP_TYPES:
        raise ValueError(
            "Manifest must explicitly exclude HAS_PROPERTY_VALUE, VALUE_OF, "
            "MEASURED_IN, and SOURCED_FROM."
        )
    return ProjectionManifest(
        version=version,
        name=name.strip(),
        source_layer=source_layer,
        node_types=node_types,
        excluded_node_types=excluded_node_types,
        relationship_types=relationship_types,
        excluded_relationship_types=excluded_relationship_types,
        path=path,
    )


def discover_csv_files(
    data_dir: Path, subdirectory: str, *, nodes: bool
) -> list[CsvFile]:
    directory = data_dir / subdirectory
    if not directory.is_dir():
        raise ValueError(f"Expected CSV directory does not exist: {directory}")

    files: list[CsvFile] = []
    for path in sorted(directory.glob("*.csv")):
        graph_name = as_cypher_name(path.stem, path)
        with path.open(encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.reader(csv_file)
            header = next(reader, None)
        if not header:
            raise ValueError(f"CSV file has no header: {path}")
        if nodes:
            if not header[0]:
                raise ValueError(f"Node CSV has an empty ID column: {path}")
            files.append(CsvFile(path, graph_name, header[0]))
        else:
            if "from" not in header or "to" not in header:
                raise ValueError(f"Relationship CSV must have from/to columns: {path}")
            files.append(CsvFile(path, graph_name))
    if not files:
        raise ValueError(f"No CSV files found in {directory}")
    return files


def discover_projection_files(
    data_dir: Path,
    subdirectory: str,
    *,
    nodes: bool,
    included_types: frozenset[str],
    excluded_types: frozenset[str],
) -> list[CsvFile]:
    """Resolve the manifest against the source snapshot without silent omission."""
    all_files = discover_csv_files(data_dir, subdirectory, nodes=nodes)
    by_name = {csv_file.graph_name: csv_file for csv_file in all_files}
    available_types = frozenset(by_name)
    declared_types = included_types | excluded_types
    missing_types = included_types - available_types
    undeclared_types = available_types - declared_types
    if missing_types or undeclared_types:
        details: list[str] = []
        if missing_types:
            details.append(f"missing from source: {', '.join(sorted(missing_types))}")
        if undeclared_types:
            details.append(
                f"not classified by manifest: {', '.join(sorted(undeclared_types))}"
            )
        raise ValueError(
            f"Projection manifest does not completely classify {subdirectory}: "
            + "; ".join(details)
        )
    return [by_name[name] for name in sorted(included_types)]


def csv_rows(csv_file: CsvFile) -> Iterator[dict[str, str]]:
    with csv_file.path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def validate_files(
    node_files: Sequence[CsvFile], relationship_files: Sequence[CsvFile]
) -> ValidationReport:
    """Prove selected node IDs are unique and every selected endpoint resolves."""
    identifiers: dict[str, Path] = {}
    node_count = 0

    for csv_file in node_files:
        assert csv_file.id_column is not None
        for line_number, row in enumerate(csv_rows(csv_file), start=2):
            external_id = (row.get(csv_file.id_column) or "").strip()
            if not external_id:
                raise ValueError(
                    f"Missing {csv_file.id_column} in {csv_file.path}:{line_number}"
                )
            previous = identifiers.get(external_id)
            if previous:
                raise ValueError(
                    f"Duplicate node ID {external_id!r} in {csv_file.path}; "
                    f"already present in {previous}"
                )
            identifiers[external_id] = csv_file.path
            node_count += 1

    missing = Counter()
    examples: dict[tuple[str, str], str] = {}
    relationship_count = 0
    for csv_file in relationship_files:
        for line_number, row in enumerate(csv_rows(csv_file), start=2):
            relationship_count += 1
            for column in ("from", "to"):
                external_id = (row.get(column) or "").strip()
                if not external_id:
                    raise ValueError(
                        f"Missing {column} in {csv_file.path}:{line_number}"
                    )
                if external_id not in identifiers:
                    key = (csv_file.graph_name, column)
                    missing[key] += 1
                    examples.setdefault(key, external_id)
    if missing:
        details = "; ".join(
            f"{name}.{column}: {count} (for example {examples[name, column]!r})"
            for (name, column), count in sorted(missing.items())
        )
        raise ValueError(
            f"Relationship endpoint IDs are missing from node CSVs: {details}"
        )

    return ValidationReport(
        node_files, relationship_files, node_count, relationship_count
    )


def validate_export(data_dir: Path) -> ValidationReport:
    """Validate the complete export, including data intentionally absent from Neo4j."""
    return validate_files(
        discover_csv_files(data_dir, "nodes", nodes=True),
        discover_csv_files(data_dir, "rels", nodes=False),
    )


def validate_projection(
    data_dir: Path, manifest: ProjectionManifest
) -> ValidationReport:
    """Validate only datasets selected by the versioned serving projection."""
    node_files = discover_projection_files(
        data_dir,
        "nodes",
        nodes=True,
        included_types=manifest.node_types,
        excluded_types=manifest.excluded_node_types,
    )
    relationship_files = discover_projection_files(
        data_dir,
        "rels",
        nodes=False,
        included_types=manifest.relationship_types,
        excluded_types=manifest.excluded_relationship_types,
    )
    return validate_files(node_files, relationship_files)


def chunks(rows: Iterator[dict[str, str]], size: int) -> Iterator[list[dict[str, str]]]:
    batch: list[dict[str, str]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def is_identifier_column(column: str) -> bool:
    """Identifier-shaped columns stay strings so MERGE lookups keep matching."""
    return bool(IDENTIFIER_COLUMN_PATTERN.search(column))


def graph_value(value: str | None, *, coerce: bool = True) -> Any:
    """Convert unambiguous scalar CSV values while preserving identifiers and dates."""
    value = (value or "").strip()
    if not value:
        return None
    if not coerce:
        return value
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if INTEGER_PATTERN.fullmatch(value):
        return int(value)
    if DECIMAL_PATTERN.fullmatch(value):
        return float(value)
    return value


def node_batch(csv_file: CsvFile, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    assert csv_file.id_column is not None
    mapped_rows = []
    for row in rows:
        properties = {
            key: converted
            for key, value in row.items()
            if (
                converted := graph_value(
                    value,
                    coerce=key != csv_file.id_column and not is_identifier_column(key),
                )
            )
            is not None
        }
        mapped_rows.append(
            {
                "externalId": row[csv_file.id_column].strip(),
                "properties": {**properties, "sourceFile": csv_file.path.name},
            }
        )
    return mapped_rows


def relationship_batch(
    csv_file: CsvFile, rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    mapped_rows = []
    for row in rows:
        source_id = row["from"].strip()
        target_id = row["to"].strip()
        properties = {
            key: converted
            for key, value in row.items()
            if key not in {"from", "to"}
            and (converted := graph_value(value, coerce=not is_identifier_column(key)))
            is not None
        }
        # Identity is the endpoint pair, so a changed property updates the
        # existing edge instead of creating a parallel one.
        fingerprint = f"{csv_file.graph_name}|{source_id}|{target_id}"
        mapped_rows.append(
            {
                "sourceId": source_id,
                "targetId": target_id,
                "edgeKey": hashlib.sha256(fingerprint.encode()).hexdigest(),
                "properties": {**properties, "sourceFile": csv_file.path.name},
            }
        )
    return mapped_rows


def content_digest(report: ValidationReport) -> str:
    """Hash the bytes actually projected so lineage names real files, not a label."""
    digest = hashlib.sha256()
    for csv_file in (*report.node_files, *report.relationship_files):
        digest.update(f"{csv_file.path.name}\0".encode())
        with csv_file.path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\n")
    return digest.hexdigest()


def run_write(session: Any, query: str, rows: list[dict[str, Any]]) -> None:
    session.run(query, rows=rows).consume()


def create_schema(session: Any) -> None:
    """Create identity constraints and traversal entry-point indexes idempotently."""
    statements = (
        "CREATE CONSTRAINT ciphos_entity_external_id IF NOT EXISTS "
        "FOR (node:CiphosEntity) REQUIRE node.externalId IS UNIQUE",
        "CREATE CONSTRAINT ciphos_projection_snapshot IF NOT EXISTS "
        "FOR (projection:CiphosProjection) "
        "REQUIRE projection.graphSnapshotId IS UNIQUE",
        "CREATE INDEX ciphos_tag_number IF NOT EXISTS "
        "FOR (node:Tag) ON (node.tagNumber)",
        "CREATE INDEX ciphos_ot_asset_id IF NOT EXISTS "
        "FOR (node:OTAsset) ON (node.otAssetId)",
        "CREATE INDEX ciphos_vulnerability_cve_id IF NOT EXISTS "
        "FOR (node:Vulnerability) ON (node.cveId)",
        "CREATE INDEX ciphos_document_number IF NOT EXISTS "
        "FOR (node:Document) ON (node.documentNumber)",
        "CREATE INDEX ciphos_asset_zone_id IF NOT EXISTS "
        "FOR (node:AssetZone) ON (node.zoneId)",
    )
    for statement in statements:
        session.run(statement).consume()


def projection_metadata_from_args(
    args: argparse.Namespace, raw_source: bool | None = None
) -> ProjectionMetadata:
    """Require immutable source lineage before a graph is built or activated."""
    source_batch_id = (args.source_batch_id or os.getenv("CIPHOS_SOURCE_BATCH_ID", "")).strip()
    source_snapshot_id = (
        args.source_snapshot_id or os.getenv("CIPHOS_SOURCE_SNAPSHOT_ID", "")
    ).strip()
    graph_snapshot_id = (
        args.graph_snapshot_id or os.getenv("CIPHOS_GRAPH_SNAPSHOT_ID", "")
    ).strip()
    application_revision = (
        args.application_revision
        or os.getenv("CIPHOS_APPLICATION_REVISION", "")
    ).strip()
    missing = [
        name
        for name, value in (
            ("source batch ID", source_batch_id),
            ("source snapshot ID", source_snapshot_id),
            ("graph snapshot ID", graph_snapshot_id),
            ("application revision", application_revision),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "A graph import requires " + ", ".join(missing) + ". Set the matching "
            "--... option or CIPHOS_SOURCE_BATCH_ID, CIPHOS_SOURCE_SNAPSHOT_ID, "
            "CIPHOS_GRAPH_SNAPSHOT_ID, and CIPHOS_APPLICATION_REVISION."
        )
    if args.activate and not args.candidate:
        raise ValueError("--activate requires --candidate after candidate validation.")
    return ProjectionMetadata(
        source_batch_id=source_batch_id,
        source_snapshot_id=source_snapshot_id,
        graph_snapshot_id=graph_snapshot_id,
        application_revision=application_revision,
        candidate=args.candidate,
        raw_source=args.allow_raw_source if raw_source is None else raw_source,
    )


def record_projection(
    session: Any,
    manifest: ProjectionManifest,
    metadata: ProjectionMetadata,
    *,
    status: str,
    report: ValidationReport | None = None,
    rejected_rows: int = 0,
    duration_ms: int | None = None,
    create: bool = False,
) -> None:
    """Persist graph lineage and outcome as a separate, non-domain metadata node.

    ``create`` claims the snapshot ID. A snapshot ID is immutable, so reusing
    one is an error rather than a silent overwrite of earlier lineage.
    """
    properties: dict[str, Any] = {
        "projectionName": manifest.name,
        "manifestVersion": manifest.version,
        "manifestPath": str(manifest.path),
        "sourceLayer": manifest.source_layer,
        "sourceBatchId": metadata.source_batch_id,
        "sourceSnapshotId": metadata.source_snapshot_id,
        "sourceMaterialization": "raw-export" if metadata.raw_source else "silver",
        "applicationRevision": metadata.application_revision,
        "status": status,
        "candidate": metadata.candidate,
        "rejectedRows": rejected_rows,
        "recordedAt": datetime.now(UTC).isoformat(),
    }
    if report is not None:
        properties.update(
            {
                "sourceContentDigest": content_digest(report),
                "nodeCount": report.node_count,
                "relationshipCount": report.relationship_count,
                "nodeLabelCount": len(report.node_files),
                "relationshipTypeCount": len(report.relationship_files),
            }
        )
    if duration_ms is not None:
        properties["durationMs"] = duration_ms
    if create:
        existing = session.run(
            "MATCH (projection:CiphosProjection {graphSnapshotId: $graphSnapshotId}) "
            "RETURN projection.status AS status",
            graphSnapshotId=metadata.graph_snapshot_id,
        ).single()
        if existing is not None:
            raise ValueError(
                f"Graph snapshot {metadata.graph_snapshot_id!r} already exists with "
                f"status {existing['status']!r}. Snapshot IDs are immutable; "
                "choose a new one."
            )
        session.run(
            "CREATE (projection:CiphosProjection {graphSnapshotId: $graphSnapshotId}) "
            "SET projection += $properties",
            graphSnapshotId=metadata.graph_snapshot_id,
            properties=properties,
        ).consume()
        return
    updated = session.run(
        "MATCH (projection:CiphosProjection {graphSnapshotId: $graphSnapshotId}) "
        "SET projection += $properties "
        "RETURN count(projection) AS updated",
        graphSnapshotId=metadata.graph_snapshot_id,
        properties=properties,
    ).single()
    if updated is None or updated["updated"] == 0:
        raise ValueError(
            f"Graph snapshot {metadata.graph_snapshot_id!r} is not registered; "
            "its lineage node was removed mid-import."
        )


def activate_projection(session: Any, graph_snapshot_id: str) -> None:
    """Atomically make one already-validated snapshot the recorded active version.

    Activation that matches nothing is a failure, not a quiet no-op.
    """
    result = session.run(
        "MATCH (projection:CiphosProjection {graphSnapshotId: $graphSnapshotId}) "
        "WHERE projection.status = 'VALIDATED' "
        "OPTIONAL MATCH (active:CiphosProjection {status: 'ACTIVE'}) "
        "WHERE active.graphSnapshotId <> projection.graphSnapshotId "
        "SET active.status = 'SUPERSEDED', active.supersededAt = $recordedAt, "
        "    projection.status = 'ACTIVE', projection.activatedAt = $recordedAt "
        "RETURN count(DISTINCT projection) AS activated",
        graphSnapshotId=graph_snapshot_id,
        recordedAt=datetime.now(UTC).isoformat(),
    ).single()
    if result is None or result["activated"] == 0:
        raise ValueError(
            f"Graph snapshot {graph_snapshot_id!r} was not activated: no projection "
            "with that ID is in the VALIDATED state."
        )


def clear_ciphos_data(session: Any) -> None:
    deleted = 0
    while True:
        result = session.run(
            "MATCH (node:CiphosEntity) WITH node LIMIT 10000 "
            "DETACH DELETE node RETURN count(*) AS deleted"
        ).single()
        batch_count = result["deleted"] if result else 0
        deleted += batch_count
        if batch_count == 0:
            break
    print(f"Cleared {deleted:,} CIPHOS-owned nodes.")


def import_nodes(session: Any, report: ValidationReport, batch_size: int) -> None:
    for csv_file in report.node_files:
        query = (
            f"UNWIND $rows AS row MERGE (node:CiphosEntity:{csv_file.graph_name} "
            "{externalId: row.externalId}) SET node += row.properties"
        )
        imported = 0
        for raw_rows in chunks(csv_rows(csv_file), batch_size):
            rows = node_batch(csv_file, raw_rows)
            run_write(session, query, rows)
            imported += len(rows)
        print(f"  nodes {csv_file.graph_name}: {imported:,}")


def import_relationships(
    session: Any, report: ValidationReport, batch_size: int
) -> None:
    for csv_file in report.relationship_files:
        query = (
            "UNWIND $rows AS row "
            "MATCH (source:CiphosEntity {externalId: row.sourceId}) "
            "MATCH (target:CiphosEntity {externalId: row.targetId}) "
            f"MERGE (source)-[relationship:{csv_file.graph_name} "
            "{edgeKey: row.edgeKey}]->(target) "
            "SET relationship += row.properties"
        )
        imported = 0
        for raw_rows in chunks(csv_rows(csv_file), batch_size):
            rows = relationship_batch(csv_file, raw_rows)
            run_write(session, query, rows)
            imported += len(rows)
        print(f"  relationships {csv_file.graph_name}: {imported:,}")


def print_counts(session: Any) -> None:
    result = session.run(
        "MATCH (node:CiphosEntity) "
        "OPTIONAL MATCH (node)-[relationship]-() "
        "RETURN count(DISTINCT node) AS nodes, count(DISTINCT relationship) AS relationships"
    ).single()
    print(
        f"CIPHOS graph: {result['nodes']:,} nodes, "
        f"{result['relationships']:,} relationships"
    )


def verify_import(session: Any, report: ValidationReport) -> None:
    """Compare graph totals and graph shape with the validated CSV export."""
    result = session.run(
        "MATCH (node:CiphosEntity) "
        "WITH count(node) AS nodes "
        "CALL () { "
        "  MATCH (source:CiphosEntity)-[relationship]->(target:CiphosEntity) "
        "  WHERE relationship.edgeKey IS NOT NULL "
        "  RETURN count(relationship) AS relationships, "
        "         count(DISTINCT type(relationship)) AS relationshipTypes "
        "} "
        "CALL () { "
        "  MATCH (node:CiphosEntity) "
        "  UNWIND labels(node) AS label "
        "  WITH DISTINCT label WHERE label <> 'CiphosEntity' "
        "  RETURN count(label) AS nodeLabels "
        "} "
        "CALL () { "
        "  MATCH (node:CiphosEntity:TagPropertyValue) "
        "  RETURN count(node) AS excludedNodes "
        "} "
        "CALL () { "
        "  MATCH (:CiphosEntity)-[relationship]->(:CiphosEntity) "
        "  WHERE type(relationship) IN $excludedRelationshipTypes "
        "  RETURN count(relationship) AS excludedRelationships "
        "} "
        "RETURN nodes, relationships, nodeLabels, relationshipTypes, "
        "excludedNodes, excludedRelationships",
        excludedRelationshipTypes=sorted(EXCLUDED_RELATIONSHIP_TYPES),
    ).single()
    actual = {
        "nodes": result["nodes"],
        "relationships": result["relationships"],
        "node labels": result["nodeLabels"],
        "relationship types": result["relationshipTypes"],
        "excluded nodes": result["excludedNodes"],
        "excluded relationships": result["excludedRelationships"],
    }
    expected = {
        "nodes": report.node_count,
        "relationships": report.relationship_count,
        "node labels": len(report.node_files),
        "relationship types": len(report.relationship_files),
        "excluded nodes": 0,
        "excluded relationships": 0,
    }
    mismatches = [
        f"{name}: expected {expected[name]:,}, found {actual[name]:,}"
        for name in expected
        if actual[name] != expected[name]
    ]
    if mismatches:
        raise ValueError("Graph verification failed: " + "; ".join(mismatches))
    print(
        "Graph verification passed: "
        f"{actual['nodes']:,} nodes, {actual['relationships']:,} relationships, "
        f"{actual['node labels']} labels, and {actual['relationship types']} types."
    )


def main() -> int:
    load_environment()
    args = parse_args()
    if args.validate_only and (args.clear or args.counts or args.verify):
        raise ValueError(
            "--validate-only cannot be combined with --clear, --counts, or --verify"
        )
    if args.counts and args.clear:
        raise ValueError("--counts cannot be combined with --clear")
    if args.counts and args.verify:
        raise ValueError("--counts cannot be combined with --verify")
    if args.activate and (args.validate_only or args.counts or args.verify):
        raise ValueError("--activate can only be used while importing a candidate.")

    silver_dir = os.getenv("CIPHOS_SILVER_SNAPSHOT_DIR", "").strip()
    data_dir, raw_source = resolve_source(args.data_dir, silver_dir)
    read_only = args.validate_only or args.counts or args.verify
    if raw_source and not args.allow_raw_source and not read_only:
        raise ValueError(
            "Databricks is the system of record. Point --data-dir or "
            "CIPHOS_SILVER_SNAPSHOT_DIR at a published Silver materialization, or "
            "pass --allow-raw-source to project the raw export and have that "
            "recorded on the projection node."
        )
    batch_size = args.batch_size or int(os.getenv("IMPORT_BATCH_SIZE", "1000"))
    if batch_size <= 0:
        raise ValueError("Batch size must be a positive integer")

    manifest = None
    if args.counts:
        report = None
    else:
        manifest = load_projection_manifest(
            args.manifest.resolve() if args.manifest is not None else None
        )
        print(
            f"Validating {manifest.name} manifest v{manifest.version} against "
            f"the local materialization at {data_dir}..."
        )
        report = validate_projection(data_dir, manifest)
        print(
            f"Validated {report.node_count:,} projected nodes across "
            f"{len(report.node_files)} files and "
            f"{report.relationship_count:,} relationships across "
            f"{len(report.relationship_files)} files."
        )
        if args.validate_only:
            return 0

    driver = GraphDatabase.driver(
        require_env("NEO4J_URI"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    database = resolve_database(
        args.database, require_env("NEO4J_DATABASE"), read_only=args.counts or args.verify
    )
    try:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            if args.counts:
                print_counts(session)
                return 0
            if args.verify:
                assert report is not None
                verify_import(session, report)
                return 0
            assert manifest is not None
            metadata = projection_metadata_from_args(args, raw_source=raw_source)
            if not metadata.candidate:
                raise ValueError(
                    "Projection imports must use --candidate and a separate candidate "
                    "database or graph context before activation."
                )
            create_schema(session)
            started_at = time.perf_counter()
            record_projection(
                session, manifest, metadata, status="LOADING", report=report, create=True
            )
            if args.clear:
                clear_ciphos_data(session)
            assert report is not None
            print("Importing nodes...")
            import_nodes(session, report, batch_size)
            print("Importing relationships...")
            import_relationships(session, report, batch_size)
            verify_import(session, report)
            duration_ms = round((time.perf_counter() - started_at) * 1000)
            record_projection(
                session,
                manifest,
                metadata,
                status="VALIDATED",
                report=report,
                duration_ms=duration_ms,
            )
            if args.activate:
                activate_projection(session, metadata.graph_snapshot_id)
            print(
                f"Candidate {metadata.graph_snapshot_id!r} validated in "
                f"{duration_ms:,} ms and is "
                f"{'active' if args.activate else 'ready for activation'}.")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Neo4jError, OSError, ValueError) as error:
        print(f"Import failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
