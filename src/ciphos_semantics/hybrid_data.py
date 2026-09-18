"""Read-only adapters for the Delta-plus-Neo4j traceability experience.

Engineering facts stay in Delta and connected context stays in Neo4j. This
module contains no Streamlit calls, so its contracts can be exercised without
either external service.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    ExecuteStatementRequestOnWaitTimeout,
    Format,
    StatementParameterListItem,
)
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
DEFAULT_PROPERTY_VIEW = "silver_tag_property_value_enriched"


class QueryExecutor(Protocol):
    """Minimal statement-execution surface used by :class:`DeltaTraceability`."""

    def execute_statement(self, **kwargs: Any) -> Any:
        """Execute a SQL statement."""


@dataclass(frozen=True)
class ServiceResult:
    """A service response that can preserve a partial hybrid answer."""

    rows: tuple[dict[str, Any], ...]
    snapshot_id: str | None
    error: str | None = None
    source_snapshot_id: str | None = None

    @property
    def available(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class HybridTraceability:
    """The independently retrievable portions of a traceability response."""

    tag_number: str
    lakehouse: ServiceResult
    graph: ServiceResult


def _qualified_identifier(value: str) -> str:
    """Quote a three-part Unity Catalog identifier from trusted configuration."""
    parts = value.split(".")
    if len(parts) != 3 or any(not IDENTIFIER_PATTERN.fullmatch(part) for part in parts):
        raise ValueError(
            "CIPHOS_SILVER_PROPERTY_VIEW must be a catalog.schema.view identifier."
        )
    return ".".join(f"`{part}`" for part in parts)


class DeltaTraceability:
    """Execute the lakehouse half of property traceability through a warehouse."""

    def __init__(
        self,
        statement_execution: QueryExecutor,
        warehouse_id: str,
        property_view: str,
    ) -> None:
        self._statement_execution = statement_execution
        self._warehouse_id = warehouse_id
        self._property_view = _qualified_identifier(property_view)

    def property_traceability(self, tag_number: str) -> ServiceResult:
        """Return typed values and aggregated provenance for one tag.

        The enriched view is already one row per value, so this query cannot
        fan out the way a join against the provenance table would.
        """
        statement = f"""
SELECT
  tpv_id,
  tag_number,
  property_id,
  property_name,
  raw_value,
  value_type,
  numeric_value,
  text_value,
  unit_of_measure_id,
  uom_symbol,
  parse_status,
  source_document_count,
  source_document_numbers,
  silver_snapshot_id
FROM {self._property_view}
WHERE tag_number = :tag_number
ORDER BY property_name, tpv_id
"""
        try:
            # An interactive page must not leave a query running once the
            # reader has given up, so this half deliberately bounds the wait.
            response = self._statement_execution.execute_statement(
                warehouse_id=self._warehouse_id,
                statement=statement,
                format=Format.JSON_ARRAY,
                wait_timeout="50s",
                on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CANCEL,
                parameters=[
                    StatementParameterListItem(
                        name="tag_number", type="STRING", value=tag_number
                    )
                ],
            )
            rows = _statement_rows(response)
            snapshot_ids = {row.get("silver_snapshot_id") for row in rows}
            snapshot_id = next(iter(snapshot_ids)) if len(snapshot_ids) == 1 else None
            return ServiceResult(tuple(rows), snapshot_id, source_snapshot_id=snapshot_id)
        except Exception as exc:
            return ServiceResult((), None, str(exc))


def _statement_rows(response: Any) -> list[dict[str, Any]]:
    """Convert a JSON-array statement response to named row dictionaries."""
    state = getattr(getattr(response, "status", None), "state", None)
    state_value = getattr(state, "value", state)
    if state_value != "SUCCEEDED":
        error = getattr(getattr(response, "status", None), "error", None)
        raise RuntimeError(f"Lakehouse SQL failed with state {state_value}: {error}")

    manifest = getattr(response, "manifest", None)
    schema = getattr(manifest, "schema", None)
    columns = getattr(schema, "columns", None) or []
    names = [column.name for column in columns]
    data = getattr(getattr(response, "result", None), "data_array", None) or []
    return [dict(zip(names, values, strict=True)) for values in data]


def get_delta_traceability() -> DeltaTraceability:
    """Create the configured Delta adapter using SDK-based Databricks auth."""
    load_dotenv(PROJECT_DIR / ".env", override=False)
    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "").strip()
    if not warehouse_id or warehouse_id.startswith("<"):
        raise ValueError("Set DATABRICKS_WAREHOUSE_ID before using hybrid traceability.")

    catalog = os.environ.get("CIPHOS_CATALOG", "graph-on-databricks")
    schema = os.environ.get(
        "CIPHOS_SILVER_SCHEMA", os.environ.get("CIPHOS_SCHEMA", "ciphos-semantics")
    )
    property_view = os.environ.get(
        "CIPHOS_SILVER_PROPERTY_VIEW", f"{catalog}.{schema}.{DEFAULT_PROPERTY_VIEW}"
    )
    workspace = WorkspaceClient(
        profile=os.environ.get("DATABRICKS_PROFILE")
        or os.environ.get("DATABRICKS_CONFIG_PROFILE")
        or None
    )
    return DeltaTraceability(workspace.statement_execution, warehouse_id, property_view)


GRAPH_TRACEABILITY_CYPHER = """
MATCH (tag:Tag {tagNumber: $tag_number})
CALL (tag) {
  OPTIONAL MATCH (plant:Plant)-[:HAS_FACILITY]->(facility:Facility)
                 -[:HAS_SYSTEM]->(system:System)-[:CONTAINS_TAG]->(tag)
  RETURN collect(DISTINCT {
    plant: plant.name, facility: facility.name, system: system.name
  }) AS hierarchy
}
CALL (tag) {
  OPTIONAL MATCH (tag)-[:CLASSIFIED_AS]->(equipment_class:EquipmentClass)
  OPTIONAL MATCH (equipment_class)-[:HAS_APPLICABLE_PROPERTY]->(property:Property)
  OPTIONAL MATCH (property)-[:DEFAULT_UNIT]->(unit:UnitOfMeasure)
  RETURN collect(DISTINCT {
    equipment_class: equipment_class.className,
    applicable_property: property.propertyName,
    default_unit: unit.uomSymbol
  }) AS ontology
}
CALL (tag) {
  OPTIONAL MATCH (tag)-[:HAS_OT_REPRESENTATION]->(asset:OTAsset)
  OPTIONAL MATCH (asset)-[:MEMBER_OF_ZONE]->(zone:AssetZone)
  OPTIONAL MATCH (asset)-[:HAS_VULNERABILITY]->(vulnerability:Vulnerability)
  RETURN collect(DISTINCT {
    ot_asset_id: asset.otAssetId,
    zone: zone.zoneName,
    vulnerability: vulnerability.cveId,
    severity: vulnerability.severity
  }) AS ot_context
}
OPTIONAL MATCH (projection:CiphosProjection {status: 'ACTIVE'})
WITH tag, hierarchy, ontology, ot_context,
     max(projection.graphSnapshotId) AS active_graph_snapshot_id,
     max(projection.sourceSnapshotId) AS active_source_snapshot_id
RETURN tag.tagNumber AS tag_number,
       hierarchy,
       ontology,
       ot_context,
       coalesce(active_graph_snapshot_id, tag.graphSnapshotId, 'unrecorded') AS graph_snapshot_id,
       coalesce(active_source_snapshot_id, tag.sourceSnapshotId) AS source_snapshot_id
"""


def graph_traceability(driver: Any, database: str, tag_number: str) -> ServiceResult:
    """Return hierarchy, ontology, OT context, and graph snapshot for one tag."""
    try:
        records = driver.execute_query(
            GRAPH_TRACEABILITY_CYPHER, database_=database, tag_number=tag_number
        ).records
        rows = [record.data() for record in records]
        snapshot_id = rows[0].get("graph_snapshot_id") if rows else None
        source_snapshot_id = rows[0].get("source_snapshot_id") if rows else None
        return ServiceResult(
            tuple(rows), snapshot_id, source_snapshot_id=source_snapshot_id
        )
    except Exception as exc:
        return ServiceResult((), None, str(exc))
