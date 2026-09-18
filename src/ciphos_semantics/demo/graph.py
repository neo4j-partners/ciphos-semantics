"""Neo4j connection helpers for the CIPHOS hybrid demo."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent.parent


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("<"):
        raise ValueError(f"Set {name} in {PROJECT_DIR / '.env'} before running the demo.")
    return value


def connect() -> tuple[Driver, str]:
    """Open a driver against the explicitly configured serving database.

    There is no fallback database: reading from the wrong graph silently is
    worse than refusing to start.
    """
    load_dotenv(PROJECT_DIR / ".env", override=False)
    driver = GraphDatabase.driver(
        _require("NEO4J_URI"), auth=(_require("NEO4J_USERNAME"), _require("NEO4J_PASSWORD"))
    )
    database = _require("NEO4J_DATABASE")
    driver.verify_connectivity()
    return driver, database


def run_query(
    driver: Driver, database: str, query: str, **parameters: Any
) -> list[dict[str, Any]]:
    """Run a read query and return plain row dictionaries."""
    records = driver.execute_query(query, database_=database, **parameters).records
    return [record.data() for record in records]


def active_projection(driver: Driver, database: str) -> dict[str, Any] | None:
    """Return lineage for the projection currently marked active, if any."""
    rows = run_query(
        driver,
        database,
        "MATCH (projection:CiphosProjection {status: 'ACTIVE'}) "
        "RETURN projection.graphSnapshotId AS graph_snapshot_id, "
        "       projection.sourceSnapshotId AS source_snapshot_id, "
        "       projection.sourceBatchId AS source_batch_id, "
        "       projection.sourceMaterialization AS source_materialization, "
        "       projection.sourceContentDigest AS source_content_digest, "
        "       projection.manifestVersion AS manifest_version, "
        "       projection.nodeCount AS node_count, "
        "       projection.relationshipCount AS relationship_count "
        "ORDER BY projection.activatedAt DESC LIMIT 1",
    )
    return rows[0] if rows else None


def sample_tags(driver: Driver, database: str, limit: int = 50) -> list[str]:
    """Return a short list of tag numbers to populate the selector."""
    rows = run_query(
        driver,
        database,
        "MATCH (tag:Tag) RETURN tag.tagNumber AS tag_number ORDER BY tag_number LIMIT $limit",
        limit=limit,
    )
    return [row["tag_number"] for row in rows if row["tag_number"]]
