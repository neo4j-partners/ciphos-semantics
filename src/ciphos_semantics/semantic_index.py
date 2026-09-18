"""Index curated CIPHOS lakehouse metadata and create its semantic vectors.

The semantic store receives Unity Catalog table and column metadata only.  It
never receives CIPHOS measurement, document, asset, or security values.
"""

from __future__ import annotations

import argparse
import os
import re
from typing import Any

from databricks import sql
from databricks.sdk.core import Config
from neo4j import GraphDatabase, RoutingControl

from ciphos_semantics.semantic_cli import load_environment
from ciphos_semantics.semantic_config import load_semantic_store_connection

# The supported analytical surface intentionally excludes Bronze loader tables
# and append-only history. These views cover traceability, provenance,
# publication freshness, and quality without duplicating snapshot rows.
DEFAULT_INDEXED_TABLES = (
    "silver_data_quality_results",
    "silver_snapshots",
    "silver_tag_property_value_enriched",
    "silver_tag_property_value_sources",
)
DEFAULT_CATALOG = "graph-on-databricks"
DEFAULT_SCHEMA = "ciphos-semantics"
MODEL_SERVICE_ENDPOINT_ALIASES = {
    # LiteLLM's Databricks provider calls /serving-endpoints, whereas this is
    # the canonical Unity Gateway model-service name. The workspace publishes
    # the same GTE model through this endpoint alias.
    "databricks/system.ai.gte-large-en": "databricks/databricks-gte-large-en",
}
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def require_env(name: str) -> str:
    """Return a configured value with a concise error for incomplete setup."""
    value = os.environ.get(name, "").strip()
    if not value or value.startswith("<"):
        raise ValueError(f"Set {name} before running semantic indexing.")
    return value


def lakehouse_catalog() -> str:
    """Use the same catalog default as the CIPHOS lakehouse publisher."""
    return os.environ.get("CIPHOS_CATALOG", "").strip() or DEFAULT_CATALOG


def lakehouse_schema() -> str:
    """Use the same schema default as the CIPHOS lakehouse publisher."""
    return os.environ.get("CIPHOS_SCHEMA", "").strip() or DEFAULT_SCHEMA


def embedding_endpoint_model(model: str) -> str:
    """Resolve Unity Gateway embedding model names for LiteLLM endpoint calls."""
    return MODEL_SERVICE_ENDPOINT_ALIASES.get(model, model)


def indexed_table_names(value: str | None = None) -> tuple[str, ...]:
    """Return the intentional query surface, not every Bronze implementation table."""
    raw = value if value is not None else os.environ.get("CIPHOS_SEMANTIC_TABLES", "")
    tables = tuple(name.strip() for name in raw.split(",") if name.strip())
    tables = tables or DEFAULT_INDEXED_TABLES
    invalid = sorted(name for name in tables if not IDENTIFIER_PATTERN.fullmatch(name))
    if invalid:
        raise ValueError(f"CIPHOS_SEMANTIC_TABLES has invalid table name(s): {invalid}")
    return tuple(sorted(set(tables)))


def databricks_access_token() -> str:
    """Use a supplied PAT, or obtain a short-lived token through the configured profile."""
    token = os.environ.get("DATABRICKS_TOKEN", "").strip()
    if token:
        return token

    profile = os.environ.get("DATABRICKS_PROFILE") or os.environ.get(
        "DATABRICKS_CONFIG_PROFILE"
    )
    authorization = Config(profile=profile or None).authenticate().get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        raise RuntimeError("The configured Databricks profile did not provide a bearer token.")
    return token


def databricks_server_hostname() -> str:
    """Resolve the SQL endpoint hostname through the active Databricks profile."""
    configured = os.environ.get("DATABRICKS_SERVER_HOSTNAME", "").strip()
    if configured:
        return configured
    host = Config(
        profile=os.environ.get("DATABRICKS_PROFILE")
        or os.environ.get("DATABRICKS_CONFIG_PROFILE")
        or None
    ).host
    if not host:
        raise ValueError(
            "Set DATABRICKS_SERVER_HOSTNAME or configure a workspace host in the profile."
        )
    return host.removeprefix("https://").removeprefix("http://").split("/", 1)[0]


def databricks_http_path() -> str:
    """Return an explicit warehouse path or derive it from the configured warehouse ID."""
    configured = os.environ.get("DATABRICKS_HTTP_PATH", "").strip()
    return configured or f"/sql/1.0/warehouses/{require_env('DATABRICKS_WAREHOUSE_ID')}"


def create_embeddings(driver: Any, database: str, model: str) -> None:
    """Embed only table and column descriptions, names, and governed metadata."""
    from neocarta import NodeLabel
    from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector

    connector = LiteLLMEmbeddingsConnector(
        neo4j_driver=driver,
        embedding_model=model,
        database_name=database,
    )
    connector.run(node_labels=[NodeLabel.TABLE, NodeLabel.COLUMN])


def remove_unselected_tables(
    driver: Any,
    *,
    database: str,
    catalog: str,
    schema: str,
    allowed_tables: tuple[str, ...],
) -> None:
    """Keep the retrievable surface on curated Silver views after schema discovery.

    NeoCarta's Databricks connector discovers a schema as a unit.  The CIPHOS
    schema also has Bronze controls and raw exports, so trim those metadata
    nodes before embeddings are created instead of making them searchable.
    """
    query = """
MATCH (:Database {name: $catalog})-[:HAS_SCHEMA]->(:Schema {name: $schema})
      -[:HAS_TABLE]->(table:Table)
WHERE NOT table.name IN $allowed_tables
OPTIONAL MATCH (table)-[:HAS_COLUMN]->(column:Column)
WITH collect(DISTINCT table) + collect(DISTINCT column) AS entities
UNWIND entities AS entity
DETACH DELETE entity
"""
    driver.execute_query(
        query_=query,
        parameters_={
            "catalog": catalog,
            "schema": schema,
            "allowed_tables": list(allowed_tables),
        },
        database_=database,
        routing_=RoutingControl.WRITE,
    )


def ingest_metadata() -> tuple[str, str, tuple[str, ...]]:
    """Ingest the configured Silver metadata, trim it, and persist semantic vectors."""
    from neocarta.connectors.databricks import DatabricksSchemaConnector

    catalog = lakehouse_catalog()
    schema = lakehouse_schema()
    require_env("DATABRICKS_WAREHOUSE_ID")
    tables = indexed_table_names()
    model = embedding_endpoint_model(require_env("CIPHOS_SEMANTIC_EMBEDDING_MODEL"))
    store = load_semantic_store_connection()
    access_token = databricks_access_token()
    driver = GraphDatabase.driver(store.uri, auth=(store.username, store.password))
    try:
        driver.verify_connectivity()
        with sql.connect(
            server_hostname=databricks_server_hostname(),
            http_path=databricks_http_path(),
            access_token=access_token,
            catalog=catalog,
            schema=schema,
        ) as connection:
            DatabricksSchemaConnector(
                connection=connection,
                catalog=catalog,
                neo4j_driver=driver,
                database_name=store.database,
                value_sample_limit=0,
            ).ingest(schema=schema)
        remove_unselected_tables(
            driver,
            database=store.database,
            catalog=catalog,
            schema=schema,
            allowed_tables=tables,
        )
        create_embeddings(driver, store.database, model)
    finally:
        driver.close()
    return catalog, schema, tables


def main(argv: list[str] | None = None) -> None:
    """Run the metadata-only CIPHOS semantic-index publication."""
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    load_environment()
    catalog, schema, tables = ingest_metadata()
    print(
        "Indexed CIPHOS Silver metadata and stored semantic embeddings for "
        f"{catalog}.{schema}: {', '.join(tables)}. Value sampling was disabled."
    )


if __name__ == "__main__":
    main()
