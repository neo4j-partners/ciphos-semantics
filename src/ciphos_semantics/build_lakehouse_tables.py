"""Build the CIPHOS Bronze and Silver lakehouse contracts.

Raw CSV values stay in Bronze. Databricks is the system of record: any graph
projection must consume a published Silver snapshot, never these files directly.
The module has no import-time side effects, so ``--dry-run`` is also a useful
contract review command.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from databricks.sdk import WorkspaceClient
from dotenv import load_dotenv

from ciphos_semantics import contract

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent.parent
DEFAULT_CATALOG = "graph-on-databricks"
DEFAULT_SCHEMA = "ciphos-semantics"
DEFAULT_VOLUME = "ciphos-raw"
DEFAULT_DATA_DIR = PROJECT_DIR / "ciphos_data" / "csv"
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
SCHEMA_VERSION = "1"
# Stamped during upload so Bronze can record a real CSV line number instead of
# an ordering invented by the query engine.
SOURCE_ROW_COLUMN = "_ciphos_source_row"
TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELED", "CLOSED"})
NUMERIC_TYPES = "('numeric', 'number', 'decimal', 'integer', 'float', 'double')"
SourceKind = Literal["node", "relationship"]


@dataclass(frozen=True)
class Column:
    """A raw source column and the snake_case name Delta stores it under.

    ``source_name`` is the CSV's own spelling. It is legal only inside the
    conform CTE, which is the one place a query still sees the file's header.
    Everything downstream of that CTE uses ``name`` and nothing else.
    """

    source_name: str
    name: str


@dataclass(frozen=True)
class SourceTable:
    """A discovered node or relationship file and its Bronze contract."""

    path: Path
    source_kind: SourceKind
    name: str
    columns: tuple[Column, ...]
    row_count: int
    checksum: str
    schema_hash: str
    # Conformed names, because the predicate runs against the conform CTE.
    required_columns: tuple[str, ...]

    @property
    def bronze_name(self) -> str:
        return f"bronze_{self.source_kind}_{self.name}"

    @property
    def source_file(self) -> str:
        return self.path.name


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=os.getenv("CIPHOS_CATALOG", DEFAULT_CATALOG))
    parser.add_argument("--schema", default=os.getenv("CIPHOS_SCHEMA", DEFAULT_SCHEMA))
    parser.add_argument("--volume", default=os.getenv("CIPHOS_VOLUME", DEFAULT_VOLUME))
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.getenv("CIPHOS_DATA_DIR", DEFAULT_DATA_DIR)),
        help="Directory holding nodes/ and rels/ (default: CIPHOS_DATA_DIR).",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("DATABRICKS_PROFILE") or os.getenv("DATABRICKS_CONFIG_PROFILE"),
    )
    parser.add_argument("--warehouse-id", default=os.getenv("DATABRICKS_WAREHOUSE_ID"))
    parser.add_argument(
        "--batch-id",
        default=os.getenv("CIPHOS_BATCH_ID"),
        help="Immutable source batch ID; defaults to a manifest hash.",
    )
    parser.add_argument(
        "--statement-timeout",
        type=int,
        default=int(os.getenv("CIPHOS_STATEMENT_TIMEOUT_SECONDS", "900")),
        help="Seconds to wait for one SQL statement before cancelling it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print discovery and the SQL plan without external writes.",
    )
    parser.add_argument(
        "--skip-silver",
        action="store_true",
        help="Load Bronze only; do not refresh typed TagPropertyValue models.",
    )
    parser.add_argument(
        "--upload-workers",
        type=int,
        default=int(os.getenv("CIPHOS_UPLOAD_WORKERS", "4")),
        help="Concurrent CSV uploads (default: CIPHOS_UPLOAD_WORKERS or 4).",
    )
    parser.add_argument(
        "--bronze-workers",
        type=int,
        default=int(os.getenv("CIPHOS_BRONZE_WORKERS", "4")),
        help="Concurrent independent Bronze operations (default: CIPHOS_BRONZE_WORKERS or 4).",
    )
    return parser.parse_args(argv)


def snake_case(value: str) -> str:
    converted = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    converted = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", converted)
    return converted.lower()


def quote_identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


def quoted_path(catalog: str, schema: str, name: str) -> str:
    return ".".join(map(quote_identifier, (catalog, schema, name)))


def quote_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def validate_identifier(value: str, *, label: str) -> None:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_root(data_dir: Path) -> Path:
    if (data_dir / "nodes").is_dir() and (data_dir / "rels").is_dir():
        return data_dir
    raise ValueError(f"Expected a directory containing nodes/ and rels/: {data_dir}")


def _discover_directory(directory: Path, source_kind: SourceKind) -> list[SourceTable]:
    tables: list[SourceTable] = []
    for path in sorted(directory.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source)
            header = next(reader, None)
            if not header or any(not value for value in header):
                raise ValueError(f"CSV has an empty or missing header: {path}")
            row_count = sum(1 for _ in reader)
        if SOURCE_ROW_COLUMN in header:
            raise ValueError(f"{path} already uses the reserved column {SOURCE_ROW_COLUMN}.")
        normalized = [snake_case(value) for value in header]
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"Column names collide after normalization in {path}")
        name = snake_case(path.stem)
        validate_identifier(name, label="derived table name")
        columns = tuple(
            Column(raw, target) for raw, target in zip(header, normalized, strict=True)
        )
        by_source = {column.source_name: column for column in columns}
        if source_kind == "node":
            required = (columns[0].name,)
        else:
            missing = [name for name in ("from", "to") if name not in by_source]
            if missing:
                raise ValueError(f"Relationship CSV must have from/to columns: {path}")
            required = (by_source["from"].name, by_source["to"].name)
        schema_text = "|".join(
            f"{column.source_name}:{column.name}" for column in columns
        )
        tables.append(
            SourceTable(
                path=path,
                source_kind=source_kind,
                name=name,
                columns=columns,
                row_count=row_count,
                checksum=_sha256_file(path),
                schema_hash=hashlib.sha256(schema_text.encode()).hexdigest(),
                required_columns=required,
            )
        )
    if not tables:
        raise ValueError(f"No CSV files found in {directory}")
    return tables


def discover_source_tables(data_dir: Path) -> list[SourceTable]:
    """Inventory every source file, including graph relationship exports."""
    root = _source_root(data_dir)
    return [
        *_discover_directory(root / "nodes", "node"),
        *_discover_directory(root / "rels", "relationship"),
    ]


def verify_against_contract(tables: Iterable[SourceTable]) -> None:
    """Fail fast when the local export no longer matches the frozen inventory."""
    discovered = {("node", table.path.stem) for table in tables if table.source_kind == "node"}
    discovered |= {
        ("relationship", table.path.stem)
        for table in tables
        if table.source_kind == "relationship"
    }
    expected = {("node", name) for name in contract.source_nodes()}
    expected |= {("relationship", name) for name in contract.source_relationships()}
    if discovered != expected:
        missing = sorted(name for kind, name in expected - discovered)
        unexpected = sorted(name for kind, name in discovered - expected)
        raise ValueError(
            f"Source inventory drift: missing={missing}, unexpected={unexpected}"
        )


def default_batch_id(tables: Iterable[SourceTable]) -> str:
    manifest = "\n".join(
        f"{table.source_kind}|{table.source_file}|{table.checksum}|{table.schema_hash}"
        for table in sorted(tables, key=lambda item: (item.source_kind, item.source_file))
    )
    return f"ciphos-{hashlib.sha256(manifest.encode()).hexdigest()[:20]}"


def _statement_state(response: object) -> str | None:
    status = getattr(response, "status", None)
    state = getattr(status, "state", None)
    return getattr(state, "value", state)


def execute_sql(
    workspace: WorkspaceClient,
    warehouse_id: str,
    statement: str,
    *,
    timeout_seconds: int = 900,
    poll_seconds: float = 2.0,
) -> None:
    """Run one statement, polling until it reaches a terminal state.

    A fixed short wait would cancel any load large enough to matter, so the
    statement keeps running server side and this call polls for the result.
    """
    response = workspace.statement_execution.execute_statement(
        warehouse_id=warehouse_id, statement=statement, wait_timeout="30s"
    )
    deadline = time.monotonic() + timeout_seconds
    while _statement_state(response) not in TERMINAL_STATES:
        if time.monotonic() > deadline:
            if response.statement_id:
                workspace.statement_execution.cancel_execution(response.statement_id)
            raise RuntimeError(
                f"SQL statement exceeded {timeout_seconds}s and was cancelled."
            )
        time.sleep(poll_seconds)
        response = workspace.statement_execution.get_statement(response.statement_id)
    state = _statement_state(response)
    if state != "SUCCEEDED":
        error = getattr(getattr(response, "status", None), "error", None)
        raise RuntimeError(f"SQL statement failed with state {state}: {error}")


def ensure_volume(
    workspace: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
    schema: str,
    volume: str,
    **kwargs,
) -> None:
    execute_sql(
        workspace,
        warehouse_id,
        f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(catalog)}.{quote_identifier(schema)}",
        **kwargs,
    )
    execute_sql(
        workspace,
        warehouse_id,
        f"CREATE VOLUME IF NOT EXISTS {quoted_path(catalog, schema, volume)}",
        **kwargs,
    )


def write_stamped_csv(source_path: Path, target_path: Path) -> int:
    """Copy a source CSV, appending the original 1-based data row number.

    Bronze must be able to point an operator at the exact line of the exported
    file. Stamping during upload is the only place that number is still known.
    """
    written = 0
    with (
        source_path.open(encoding="utf-8-sig", newline="") as source,
        target_path.open("w", encoding="utf-8", newline="") as target,
    ):
        reader = csv.reader(source)
        writer = csv.writer(target, lineterminator="\n")
        header = next(reader)
        writer.writerow([*header, SOURCE_ROW_COLUMN])
        for row_number, row in enumerate(reader, start=1):
            writer.writerow([*row, row_number])
            written += 1
    return written


def upload_source_csv(workspace: WorkspaceClient, table: SourceTable, remote_path: str) -> None:
    """Upload a row-stamped copy while the recorded checksum stays the original."""
    with tempfile.TemporaryDirectory() as directory:
        stamped = Path(directory) / table.source_file
        written = write_stamped_csv(table.path, stamped)
        if written != table.row_count:
            raise RuntimeError(
                f"{table.source_file} changed while uploading: expected "
                f"{table.row_count} rows, wrote {written}."
            )
        with stamped.open("rb") as handle:
            workspace.files.upload(remote_path, handle, overwrite=True)


def remote_source_path(volume_path: str, table: SourceTable) -> str:
    return f"{volume_path}/source/{table.source_kind}s/{table.checksum}/{table.source_file}"


def _validate_worker_count(value: int, *, label: str) -> None:
    if value < 1:
        raise ValueError(f"{label} must be at least 1.")


def _run_parallel_tables(
    tables: Sequence[SourceTable],
    worker_count: int,
    operation: Callable[[SourceTable], None],
) -> None:
    """Run independent per-source work with bounded concurrency.

    Exceptions are surfaced after outstanding work finishes so the executor can
    clean up cleanly. Shared Delta-table operations are intentionally excluded
    from this helper and remain serialized by the caller.
    """
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(operation, table): table for table in tables}
        for future in as_completed(futures):
            future.result()


def control_table_statements(catalog: str, schema: str) -> list[str]:
    control = quoted_path(catalog, schema, "bronze_ingestion_control")
    quarantine = quoted_path(catalog, schema, "bronze_quarantine")
    return [
        f"""CREATE TABLE IF NOT EXISTS {control} (
  batch_id STRING NOT NULL, source_file STRING NOT NULL, source_kind STRING NOT NULL,
  file_checksum STRING NOT NULL, schema_hash STRING NOT NULL, schema_version STRING NOT NULL,
  expected_row_count BIGINT NOT NULL, loaded_row_count BIGINT, quarantined_row_count BIGINT,
  status STRING NOT NULL, error_message STRING, discovered_at TIMESTAMP NOT NULL,
  published_at TIMESTAMP
) USING DELTA""",
        f"""CREATE TABLE IF NOT EXISTS {quarantine} (
  batch_id STRING NOT NULL, source_file STRING NOT NULL, source_kind STRING NOT NULL,
  source_row_number BIGINT, file_checksum STRING NOT NULL, schema_hash STRING NOT NULL,
  reason STRING NOT NULL, raw_record STRING NOT NULL, quarantined_at TIMESTAMP NOT NULL
) USING DELTA""",
    ]


def create_bronze_table_statement(catalog: str, schema: str, table: SourceTable) -> str:
    raw = [
        f"{quote_identifier(column.name)} STRING COMMENT {quote_string(column.source_name)}"
        for column in table.columns
    ]
    metadata = [
        "source_file STRING NOT NULL",
        "source_kind STRING NOT NULL",
        "source_row_number BIGINT NOT NULL",
        "source_checksum STRING NOT NULL",
        "schema_hash STRING NOT NULL",
        "schema_version STRING NOT NULL",
        "source_batch_id STRING NOT NULL",
        "ingested_at TIMESTAMP NOT NULL",
    ]
    return (
        f"CREATE TABLE IF NOT EXISTS {quoted_path(catalog, schema, table.bronze_name)} (\n  "
        + ",\n  ".join([*raw, *metadata])
        + "\n) USING DELTA\n"
        + f"COMMENT {quote_string(f'Raw CIPHOS {table.source_kind} CSV: {table.source_file}')}"
    )


def _read_files_expression(volume_path: str, table: SourceTable) -> str:
    source_schema = ", ".join(
        [
            *(f"{quote_identifier(column.source_name)} STRING" for column in table.columns),
            f"{quote_identifier(SOURCE_ROW_COLUMN)} BIGINT",
        ]
    )
    return (
        "read_files(\n"
        f"  {quote_string(volume_path)}, format => 'csv', header => 'true',\n"
        "  inferSchema => 'false',\n"
        f"  schema => {quote_string(source_schema)}\n)"
    )


def _raw_record_expression(table: SourceTable) -> str:
    arguments = ", ".join(
        f"{quote_string(column.name)}, {quote_identifier(column.source_name)}"
        for column in table.columns
    )
    return f"to_json(named_struct({arguments}))"


def _conform_cte(volume_path: str, table: SourceTable) -> str:
    """Rename the CSV header to snake_case once, at the Bronze read boundary.

    A file cannot be read without naming its own columns, so the source
    spelling has to appear somewhere. Confining it to this CTE means every
    later clause, predicate and insert has exactly one spelling to get right.
    """
    renames = ",\n".join(
        f"    {quote_identifier(column.source_name)}"
        if column.source_name == column.name
        else f"    {quote_identifier(column.source_name)} AS {quote_identifier(column.name)}"
        for column in table.columns
    )
    return (
        "WITH conformed AS (\n"
        f"  SELECT\n{renames},\n"
        f"    {_raw_record_expression(table)} AS raw_record,\n"
        f"    {quote_identifier(SOURCE_ROW_COLUMN)} AS source_row_number\n"
        f"  FROM {_read_files_expression(volume_path, table)}\n"
        ")\n"
    )


def _missing_required_predicate(table: SourceTable) -> str:
    """Build the predicate against the conformed snake_case names.

    Always parenthesized. A bare multi-term OR would bind looser than the
    caller's AND, silently dropping the replay guard from all but the last
    term, so the helper never hands back a fragment a caller has to wrap.
    """
    terms = " OR ".join(
        f"trim(coalesce({quote_identifier(name)}, '')) = ''"
        for name in table.required_columns
    )
    return f"({terms})"


def schema_drift_statement(catalog: str, schema: str, table: SourceTable) -> str:
    control = quoted_path(catalog, schema, "bronze_ingestion_control")
    message = f"Schema drift for {table.source_file}; publish a new contract before loading"
    return (
        "SELECT CASE WHEN ("
        f"SELECT count(*) FROM {control} WHERE source_file = {quote_string(table.source_file)} "
        f"AND schema_hash <> {quote_string(table.schema_hash)} AND status = 'PUBLISHED'"
        f") > 0 THEN raise_error({quote_string(message)}) END"
    )


def discover_control_statement(
    catalog: str, schema: str, table: SourceTable, batch_id: str
) -> str:
    control = quoted_path(catalog, schema, "bronze_ingestion_control")
    return f"""MERGE INTO {control} AS target
USING (SELECT {quote_string(batch_id)} AS batch_id,
  {quote_string(table.source_file)} AS source_file) AS source
ON target.batch_id = source.batch_id AND target.source_file = source.source_file
WHEN NOT MATCHED THEN INSERT (batch_id, source_file, source_kind, file_checksum,
  schema_hash, schema_version, expected_row_count, status, discovered_at)
VALUES ({quote_string(batch_id)}, {quote_string(table.source_file)},
  {quote_string(table.source_kind)}, {quote_string(table.checksum)},
  {quote_string(table.schema_hash)}, {quote_string(SCHEMA_VERSION)},
  {table.row_count}, 'DISCOVERED', current_timestamp())"""


def quarantine_statement(
    catalog: str, schema: str, volume_path: str, table: SourceTable, batch_id: str
) -> str:
    quarantine = quoted_path(catalog, schema, "bronze_quarantine")
    reason = "missing required field: " + ", ".join(table.required_columns)
    return f"""{_conform_cte(volume_path, table)}INSERT INTO {quarantine}
SELECT {quote_string(batch_id)}, {quote_string(table.source_file)},
  {quote_string(table.source_kind)}, source_row_number, {quote_string(table.checksum)},
  {quote_string(table.schema_hash)}, {quote_string(reason)}, raw_record, current_timestamp()
FROM conformed WHERE {_missing_required_predicate(table)}
  AND (SELECT count(*) FROM {quarantine} WHERE batch_id = {quote_string(batch_id)}
    AND source_file = {quote_string(table.source_file)}) = 0"""


def load_bronze_statement(
    catalog: str, schema: str, volume_path: str, table: SourceTable, batch_id: str
) -> str:
    bronze = quoted_path(catalog, schema, table.bronze_name)
    control = quoted_path(catalog, schema, "bronze_ingestion_control")
    columns = ", ".join(quote_identifier(column.name) for column in table.columns)
    return f"""{_conform_cte(volume_path, table)}INSERT INTO {bronze} ({columns},
  source_file, source_kind, source_row_number, source_checksum, schema_hash,
  schema_version, source_batch_id, ingested_at)
SELECT {columns}, {quote_string(table.source_file)},
  {quote_string(table.source_kind)}, source_row_number, {quote_string(table.checksum)},
  {quote_string(table.schema_hash)}, {quote_string(SCHEMA_VERSION)},
  {quote_string(batch_id)}, current_timestamp()
FROM conformed WHERE NOT {_missing_required_predicate(table)}
  AND (SELECT count(*) FROM {control} WHERE batch_id = {quote_string(batch_id)}
    AND source_file = {quote_string(table.source_file)} AND status = 'PUBLISHED') = 0"""


def publish_control_statement(
    catalog: str, schema: str, table: SourceTable, batch_id: str
) -> str:
    control = quoted_path(catalog, schema, "bronze_ingestion_control")
    bronze = quoted_path(catalog, schema, table.bronze_name)
    quarantine = quoted_path(catalog, schema, "bronze_quarantine")
    return f"""UPDATE {control}
SET status = 'PUBLISHED', published_at = current_timestamp(),
  loaded_row_count = (SELECT count(*) FROM {bronze}
    WHERE source_batch_id = {quote_string(batch_id)}),
  quarantined_row_count = (SELECT count(*) FROM {quarantine}
    WHERE batch_id = {quote_string(batch_id)}
    AND source_file = {quote_string(table.source_file)})
WHERE batch_id = {quote_string(batch_id)} AND source_file = {quote_string(table.source_file)}
  AND status = 'DISCOVERED'"""


def bronze_statements(
    catalog: str, schema: str, volume_path: str, table: SourceTable, batch_id: str
) -> list[str]:
    """The ordered, replayable statement sequence for one source file."""
    remote = remote_source_path(volume_path, table)
    return [
        create_bronze_table_statement(catalog, schema, table),
        discover_control_statement(catalog, schema, table, batch_id),
        schema_drift_statement(catalog, schema, table),
        quarantine_statement(catalog, schema, remote, table, batch_id),
        load_bronze_statement(catalog, schema, remote, table, batch_id),
        publish_control_statement(catalog, schema, table, batch_id),
    ]


def silver_snapshot_id(batch_id: str) -> str:
    """Silver is a deterministic function of Bronze, so its ID is derived."""
    return f"{batch_id}-silver"


def _quality_rules(catalog: str, schema: str, batch_id: str) -> list[tuple[str, str]]:
    """One counting query per contract quality rule, in contract order."""
    values = quoted_path(catalog, schema, "silver_tag_property_value_snapshots")
    sources = quoted_path(catalog, schema, "silver_tag_property_value_source_snapshots")
    tag = quoted_path(catalog, schema, "bronze_node_tag")
    prop = quoted_path(catalog, schema, "bronze_node_property")
    uom = quoted_path(catalog, schema, "bronze_node_unit_of_measure")
    snapshot = quote_string(silver_snapshot_id(batch_id))
    batch = quote_string(batch_id)
    scope = f"FROM {values} v WHERE v.silver_snapshot_id = {snapshot}"
    return [
        (
            "tag_property_value_required_identifiers",
            f"""SELECT count(*) AS evaluated_row_count,
  sum(CASE WHEN trim(coalesce(v.tpv_id, '')) = '' OR trim(coalesce(v.tag_number, '')) = ''
    OR trim(coalesce(v.property_id, '')) = '' THEN 1 ELSE 0 END) AS failed_row_count
{scope}""",
        ),
        (
            "tag_property_value_numeric_parse",
            f"""SELECT count(*) AS evaluated_row_count,
  sum(CASE WHEN v.parse_status <> 'PARSED' THEN 1 ELSE 0 END) AS failed_row_count
{scope} AND v.value_type IN {NUMERIC_TYPES}""",
        ),
        (
            "tag_property_value_tag_endpoint",
            f"""SELECT count(*) AS evaluated_row_count,
  sum(CASE WHEN t.tag_number IS NULL THEN 1 ELSE 0 END) AS failed_row_count
FROM {values} v LEFT JOIN {tag} t ON t.tag_number = v.tag_number AND t.source_batch_id = {batch}
WHERE v.silver_snapshot_id = {snapshot}""",
        ),
        (
            "tag_property_value_property_endpoint",
            f"""SELECT count(*) AS evaluated_row_count,
  sum(CASE WHEN p.property_id IS NULL THEN 1 ELSE 0 END) AS failed_row_count
FROM {values} v LEFT JOIN {prop} p ON p.property_id = v.property_id AND p.source_batch_id = {batch}
WHERE v.silver_snapshot_id = {snapshot}""",
        ),
        (
            "tag_property_value_unit_endpoint",
            f"""SELECT count(*) AS evaluated_row_count,
  sum(CASE WHEN u.uom_id IS NULL THEN 1 ELSE 0 END) AS failed_row_count
FROM {values} v LEFT JOIN {uom} u ON u.uom_id = v.unit_of_measure_id AND u.source_batch_id = {batch}
WHERE v.silver_snapshot_id = {snapshot} AND trim(coalesce(v.unit_of_measure_id, '')) <> ''""",
        ),
        (
            "tag_property_value_provenance",
            f"""SELECT count(*) AS evaluated_row_count,
  sum(CASE WHEN s.tpv_id IS NULL THEN 1 ELSE 0 END) AS failed_row_count
FROM {values} v
LEFT JOIN (SELECT DISTINCT tpv_id FROM {sources} WHERE silver_snapshot_id = {snapshot}) s
  ON s.tpv_id = v.tpv_id
WHERE v.silver_snapshot_id = {snapshot}""",
        ),
    ]


def silver_statements(catalog: str, schema: str, batch_id: str) -> list[str]:
    """Publish the typed TagPropertyValue snapshot and its quality verdict.

    Values and their source documents share one append-only snapshot model, so
    a published snapshot is never rewritten and the current views are the only
    moving part.
    """
    control = quoted_path(catalog, schema, "silver_snapshots")
    value_snapshots = quoted_path(catalog, schema, "silver_tag_property_value_snapshots")
    source_snapshots = quoted_path(
        catalog, schema, "silver_tag_property_value_source_snapshots"
    )
    quality = quoted_path(catalog, schema, "silver_data_quality_results")
    values_view = quoted_path(catalog, schema, "silver_tag_property_value")
    sources_view = quoted_path(catalog, schema, "silver_tag_property_value_sources")
    enriched_view = quoted_path(catalog, schema, "silver_tag_property_value_enriched")
    bronze_value = quoted_path(catalog, schema, "bronze_node_tag_property_value")
    bronze_property = quoted_path(catalog, schema, "bronze_node_property")
    bronze_uom = quoted_path(catalog, schema, "bronze_node_unit_of_measure")
    bronze_document = quoted_path(catalog, schema, "bronze_node_document")
    bronze_sourced_from = quoted_path(catalog, schema, "bronze_relationship_sourced_from")

    snapshot = quote_string(silver_snapshot_id(batch_id))
    batch = quote_string(batch_id)
    version = quote_string(contract.contract_version())
    unpublished = f"(SELECT count(*) FROM {control} WHERE silver_snapshot_id = {snapshot}) = 0"
    numeric_type = f"lower(coalesce(p.data_type, '')) IN {NUMERIC_TYPES}"

    rules = _quality_rules(catalog, schema, batch_id)
    declared = tuple(name for name, _ in rules)
    if set(declared) != set(contract.quality_rules()):
        raise ValueError(
            "Quality rules drifted from the contract: "
            f"emitted={sorted(declared)}, contract={sorted(contract.quality_rules())}"
        )
    rule_union = "\nUNION ALL\n".join(
        f"SELECT {quote_string(name)} AS rule_name, evaluated_row_count, "
        f"failed_row_count\nFROM ({sql})"
        for name, sql in rules
    )

    return [
        f"""CREATE TABLE IF NOT EXISTS {control} (
  silver_snapshot_id STRING NOT NULL, source_batch_id STRING NOT NULL,
  contract_version STRING NOT NULL, value_row_count BIGINT NOT NULL,
  source_row_count BIGINT NOT NULL, status STRING NOT NULL, published_at TIMESTAMP NOT NULL
) USING DELTA COMMENT 'Append-only register of published Silver snapshots.'""",
        f"""CREATE TABLE IF NOT EXISTS {value_snapshots} (
  tpv_id STRING NOT NULL, tag_number STRING, property_id STRING, raw_value STRING,
  value_type STRING NOT NULL, numeric_value DOUBLE, text_value STRING,
  unit_of_measure_id STRING, parse_status STRING NOT NULL,
  source_batch_id STRING NOT NULL, silver_snapshot_id STRING NOT NULL,
  source_file STRING NOT NULL, source_row_number BIGINT NOT NULL, published_at TIMESTAMP NOT NULL
) USING DELTA COMMENT 'Append-only typed tag-property values, one row per value per snapshot.'""",
        f"""CREATE TABLE IF NOT EXISTS {source_snapshots} (
  tpv_id STRING NOT NULL, document_number STRING NOT NULL,
  source_batch_id STRING NOT NULL, silver_snapshot_id STRING NOT NULL,
  source_file STRING NOT NULL, source_row_number BIGINT NOT NULL, published_at TIMESTAMP NOT NULL
) USING DELTA COMMENT 'Append-only value provenance, one row per value and source document.'""",
        f"""CREATE TABLE IF NOT EXISTS {quality} (
  silver_snapshot_id STRING NOT NULL, source_batch_id STRING NOT NULL, rule_name STRING NOT NULL,
  evaluated_row_count BIGINT NOT NULL, failed_row_count BIGINT NOT NULL,
  status STRING NOT NULL, evaluated_at TIMESTAMP NOT NULL
) USING DELTA COMMENT 'One row per contract quality rule per Silver snapshot.'""",
        f"""INSERT INTO {value_snapshots}
SELECT v.tpv_id, v.tag_number, v.property_id, v.value AS raw_value,
  lower(coalesce(p.data_type, 'unknown')) AS value_type,
  CASE WHEN {numeric_type} THEN try_cast(v.value AS DOUBLE) END AS numeric_value,
  CASE WHEN {numeric_type} THEN NULL ELSE v.value END AS text_value,
  nullif(trim(v.unit_of_measure_id), '') AS unit_of_measure_id,
  CASE WHEN {numeric_type} AND try_cast(v.value AS DOUBLE) IS NULL THEN 'UNPARSED' ELSE 'PARSED' END
    AS parse_status,
  {batch}, {snapshot}, v.source_file, v.source_row_number, current_timestamp()
FROM {bronze_value} v
LEFT JOIN {bronze_property} p ON p.property_id = v.property_id AND p.source_batch_id = {batch}
WHERE v.source_batch_id = {batch} AND {unpublished}""",
        f"""INSERT INTO {source_snapshots}
SELECT s.`from` AS tpv_id, s.`to` AS document_number, {batch}, {snapshot},
  min(s.source_file) AS source_file, min(s.source_row_number) AS source_row_number,
  current_timestamp()
FROM {bronze_sourced_from} s
WHERE s.source_batch_id = {batch} AND {unpublished}
GROUP BY s.`from`, s.`to`""",
        f"""INSERT INTO {quality}
SELECT {snapshot}, {batch}, rule_name, evaluated_row_count, failed_row_count,
  CASE WHEN failed_row_count = 0 THEN 'PASS' ELSE 'WARN' END, current_timestamp()
FROM (
{rule_union}
)
WHERE (SELECT count(*) FROM {quality} WHERE silver_snapshot_id = {snapshot}) = 0""",
        f"""INSERT INTO {control}
SELECT {snapshot}, {batch}, {version},
  (SELECT count(*) FROM {value_snapshots} WHERE silver_snapshot_id = {snapshot}),
  (SELECT count(*) FROM {source_snapshots} WHERE silver_snapshot_id = {snapshot}),
  'PUBLISHED', current_timestamp()
WHERE {unpublished}""",
        f"""CREATE OR REPLACE VIEW {values_view}
COMMENT 'Current published Silver tag-property values.' AS
SELECT tpv_id, tag_number, property_id, raw_value, value_type, numeric_value, text_value,
  unit_of_measure_id, parse_status, source_batch_id, silver_snapshot_id,
  source_file, source_row_number, true AS is_current
FROM {value_snapshots} WHERE silver_snapshot_id = {snapshot}""",
        f"""CREATE OR REPLACE VIEW {sources_view}
COMMENT 'Current published value provenance, one row per value and source document.' AS
SELECT tpv_id, document_number, source_batch_id, silver_snapshot_id, source_file, source_row_number
FROM {source_snapshots} WHERE silver_snapshot_id = {snapshot}""",
        f"""CREATE OR REPLACE VIEW {enriched_view}
COMMENT 'One row per tag-property value; source documents are aggregated, never fanned out.' AS
WITH documents AS (
  SELECT s.tpv_id,
    count(DISTINCT s.document_number) AS source_document_count,
    sort_array(collect_set(s.document_number)) AS source_document_numbers,
    sort_array(collect_set(d.document_title)) AS source_document_titles
  FROM {source_snapshots} s
  LEFT JOIN {bronze_document} d ON d.document_number = s.document_number
    AND d.source_batch_id = {batch}
  WHERE s.silver_snapshot_id = {snapshot}
  GROUP BY s.tpv_id
)
SELECT v.*, p.property_name, lower(coalesce(p.data_type, 'unknown')) AS property_data_type,
  u.uom_symbol, u.uom_name,
  coalesce(docs.source_document_count, 0) AS source_document_count,
  coalesce(docs.source_document_numbers, array()) AS source_document_numbers,
  coalesce(docs.source_document_titles, array()) AS source_document_titles
FROM {values_view} v
LEFT JOIN {bronze_property} p ON p.property_id = v.property_id AND p.source_batch_id = {batch}
LEFT JOIN {bronze_uom} u ON u.uom_id = v.unit_of_measure_id AND u.source_batch_id = {batch}
LEFT JOIN documents docs ON docs.tpv_id = v.tpv_id""",
    ]


def build_plan(
    catalog: str,
    schema: str,
    volume: str,
    tables: Sequence[SourceTable],
    batch_id: str,
    *,
    include_silver: bool = True,
) -> list[str]:
    """The full ordered statement plan; ``--dry-run`` prints exactly this."""
    volume_path = f"/Volumes/{catalog}/{schema}/{volume}"
    statements = list(control_table_statements(catalog, schema))
    for table in tables:
        statements.extend(bronze_statements(catalog, schema, volume_path, table, batch_id))
    if include_silver:
        statements.extend(silver_statements(catalog, schema, batch_id))
    return statements


def load_bronze_tables(
    workspace: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
    schema: str,
    volume_path: str,
    tables: Sequence[SourceTable],
    batch_id: str,
    *,
    worker_count: int,
    timeout_seconds: int,
) -> None:
    """Load all Bronze sources while serializing writes to shared Delta tables."""
    statements_by_table = {
        table: bronze_statements(catalog, schema, volume_path, table, batch_id)
        for table in tables
    }

    def execute_for(table: SourceTable, statement_index: int) -> None:
        execute_sql(
            workspace,
            warehouse_id,
            statements_by_table[table][statement_index],
            timeout_seconds=timeout_seconds,
        )

    # Each source owns its Bronze table, so these DDL statements can overlap.
    _run_parallel_tables(tables, worker_count, lambda table: execute_for(table, 0))
    print(f"created {len(tables)} Bronze tables")

    # All sources update the same control table. Serializing prevents Delta
    # optimistic-concurrency retries from erasing the gain from parallel work.
    for table in tables:
        execute_for(table, 1)
    print(f"registered {len(tables)} Bronze sources")

    # Schema checks are read-only and can safely share the warehouse.
    _run_parallel_tables(tables, worker_count, lambda table: execute_for(table, 2))
    print(f"validated {len(tables)} Bronze schemas")

    # Quarantine and publication share Delta tables, so they stay ordered.
    for table in tables:
        execute_for(table, 3)
    print(f"quarantined invalid rows for {len(tables)} Bronze sources")

    # Every load has its own target Bronze table and may run independently.
    _run_parallel_tables(tables, worker_count, lambda table: execute_for(table, 4))
    print(f"loaded {len(tables)} Bronze tables")

    for table in tables:
        execute_for(table, 5)
    print(f"published {len(tables)} Bronze ingestion records")


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(PROJECT_DIR / ".env")
    args = parse_args(argv)
    _validate_worker_count(args.upload_workers, label="--upload-workers")
    _validate_worker_count(args.bronze_workers, label="--bronze-workers")
    for value, label in (
        (args.catalog, "catalog"),
        (args.schema, "schema"),
        (args.volume, "volume"),
    ):
        validate_identifier(value, label=label)

    tables = discover_source_tables(args.data_dir)
    verify_against_contract(tables)
    batch_id = args.batch_id or default_batch_id(tables)
    volume_path = f"/Volumes/{args.catalog}/{args.schema}/{args.volume}"
    statements = build_plan(
        args.catalog,
        args.schema,
        args.volume,
        tables,
        batch_id,
        include_silver=not args.skip_silver,
    )

    node_count = sum(1 for table in tables if table.source_kind == "node")
    print(f"batch_id: {batch_id}")
    print(f"contract: {contract.contract_version()}")
    print(f"sources: {node_count} node, {len(tables) - node_count} relationship")
    print(f"rows: {sum(table.row_count for table in tables):,}")
    print(f"statements: {len(statements)}")

    if args.dry_run:
        for statement in statements:
            print(f"\n-- {'-' * 70}\n{statement};")
        return 0

    if not args.warehouse_id:
        print("--warehouse-id (or DATABRICKS_WAREHOUSE_ID) is required.", file=sys.stderr)
        return 2

    workspace = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    timeout = {"timeout_seconds": args.statement_timeout}
    ensure_volume(workspace, args.warehouse_id, args.catalog, args.schema, args.volume, **timeout)
    _run_parallel_tables(
        tables,
        args.upload_workers,
        lambda table: upload_source_csv(workspace, table, remote_source_path(volume_path, table)),
    )
    print(f"uploaded {len(tables)} CSV sources")

    for statement in control_table_statements(args.catalog, args.schema):
        execute_sql(workspace, args.warehouse_id, statement, **timeout)
    load_bronze_tables(
        workspace,
        args.warehouse_id,
        args.catalog,
        args.schema,
        volume_path,
        tables,
        batch_id,
        worker_count=args.bronze_workers,
        timeout_seconds=args.statement_timeout,
    )
    if not args.skip_silver:
        silver = silver_statements(args.catalog, args.schema, batch_id)
        for index, statement in enumerate(silver, start=1):
            execute_sql(workspace, args.warehouse_id, statement, **timeout)
            print(f"silver [{index}/{len(silver)}] ok")
        print(f"published silver snapshot {silver_snapshot_id(batch_id)}")
    else:
        print("Bronze load complete; Silver publication was skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
