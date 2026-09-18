"""Cached, read-only connections shared by the CIPHOS explorer pages."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from databricks.sdk.service.sql import ExecuteStatementRequestOnWaitTimeout, Format
from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

from ciphos_semantics import hybrid_data
from ciphos_semantics.demo import graph
from ciphos_semantics.local_neo4j import configure_local_neo4j
from ciphos_semantics.semantic_config import load_semantic_store_connection

PROJECT_DIR = Path(__file__).resolve().parents[3]
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class WarehouseConnection:
    """The configured warehouse and SDK client, or a safe connection error."""

    ok: bool
    warehouse_id: str = ""
    catalog: str = ""
    schema: str = ""
    workspace: WorkspaceClient | None = None
    error: str | None = None


@dataclass(frozen=True)
class GraphConnection:
    """The configured CIPHOS serving graph, or a safe connection error."""

    ok: bool
    driver: Driver | None = None
    database: str = ""
    host: str = ""
    error: str | None = None


@dataclass(frozen=True)
class SemanticStoreConnection:
    """The configured NeoCarta semantic store, or a safe connection error."""

    ok: bool
    driver: Driver | None = None
    database: str = ""
    host: str = ""
    error: str | None = None


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("<"):
        raise ValueError(f"Set {name} in {PROJECT_DIR / '.env'} before starting the explorer.")
    return value


def quote_identifier(value: str) -> str:
    """Quote a Unity Catalog identifier after accepting its supported spelling."""
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid Unity Catalog identifier: {value!r}")
    return f"`{value}`"


def qualified_table(catalog: str, schema: str, table: str) -> str:
    """Build a SQL identifier solely from the configured catalog and allowlist."""
    return ".".join(quote_identifier(value) for value in (catalog, schema, table))


@st.cache_resource(show_spinner="Connecting to Databricks SQL…")
def warehouse_connection() -> WarehouseConnection:
    """Create and verify the one SDK-authenticated warehouse client."""
    try:
        load_dotenv(PROJECT_DIR / ".env", override=False)
        warehouse_id = _required_environment("DATABRICKS_WAREHOUSE_ID")
        catalog = os.getenv("CIPHOS_CATALOG", "graph-on-databricks")
        schema = os.getenv("CIPHOS_SCHEMA", "ciphos-semantics")
        quote_identifier(catalog)
        quote_identifier(schema)
        profile = os.getenv("DATABRICKS_PROFILE") or os.getenv("DATABRICKS_CONFIG_PROFILE")
        config = Config(profile=profile) if profile else Config()
        workspace = WorkspaceClient(config=config)
        query_rows(workspace, warehouse_id, "SELECT 1 AS connected")
    except Exception as error:
        return WarehouseConnection(ok=False, error=str(error))
    return WarehouseConnection(
        ok=True,
        warehouse_id=warehouse_id,
        catalog=catalog,
        schema=schema,
        workspace=workspace,
    )


@st.cache_resource(show_spinner="Connecting to the operational graph…")
def operational_graph_connection() -> GraphConnection:
    """Open the explicitly configured serving graph and verify it is reachable."""
    try:
        load_dotenv(PROJECT_DIR / ".env", override=False)
        configure_local_neo4j()
        driver, database = graph.connect()
    except Exception as error:
        return GraphConnection(ok=False, error=str(error))
    return GraphConnection(
        ok=True, driver=driver, database=database, host=os.getenv("OPS_NEO4J_URI", "")
    )


@st.cache_resource(show_spinner="Connecting to the semantic store…")
def semantic_store_connection() -> SemanticStoreConnection:
    """Open the configured NeoCarta semantic store and verify it is reachable."""
    try:
        load_dotenv(PROJECT_DIR / ".env", override=False)
        configure_local_neo4j()
        connection = load_semantic_store_connection()
        driver = GraphDatabase.driver(
            connection.uri, auth=(connection.username, connection.password)
        )
        driver.verify_connectivity()
    except Exception as error:
        return SemanticStoreConnection(ok=False, error=str(error))
    return SemanticStoreConnection(
        ok=True, driver=driver, database=connection.database, host=connection.uri
    )


def query_rows(
    workspace: WorkspaceClient, warehouse_id: str, statement: str
) -> list[dict[str, Any]]:
    """Run one bounded, read-only statement and decode its JSON result."""
    response = workspace.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=statement,
        format=Format.JSON_ARRAY,
        wait_timeout="50s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CANCEL,
    )
    return hybrid_data._statement_rows(response)
