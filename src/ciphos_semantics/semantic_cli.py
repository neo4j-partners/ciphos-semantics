"""Command-line composition for CIPHOS LPG semantic-map operations."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase

from ciphos_semantics.local_neo4j import configure_local_neo4j
from ciphos_semantics.neo4j_schema_extract import (
    SUPPRESSED_SOURCE_NOTIFICATIONS,
    extract_schema_map,
)
from ciphos_semantics.semantic_config import (
    OperationalNeo4jConnection,
    SemanticStoreNeo4jConnection,
    load_operational_connection,
    load_semantic_store_connection,
)
from ciphos_semantics.semantic_mcp import create_ciphos_mcp_server
from ciphos_semantics.semantic_store import SemanticStore, ingest_schema_map
from ciphos_semantics.validate_semantic_map import validate_semantic_map

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8000


def load_environment() -> None:
    """Load local values without replacing explicitly exported configuration."""
    load_dotenv(PROJECT_DIR / ".env", override=False)
    configure_local_neo4j()


def _driver(connection: OperationalNeo4jConnection | SemanticStoreNeo4jConnection) -> Any:
    return GraphDatabase.driver(
        connection.uri,
        auth=(connection.username, connection.password),
    )


def _source_driver(connection: OperationalNeo4jConnection) -> Any:
    """Open the metadata-read driver with its inherent notifications silenced."""
    return GraphDatabase.driver(
        connection.uri,
        auth=(connection.username, connection.password),
        notifications_disabled_classifications=list(SUPPRESSED_SOURCE_NOTIFICATIONS),
    )


def resolve_source_scope(store: SemanticStore, requested: str | None = None) -> str:
    """Resolve one persisted CIPHOS scope without consulting source configuration."""
    if requested and requested.strip():
        return requested.strip()
    scopes = store.list_source_scopes()
    if not scopes:
        raise ValueError(
            "The semantic store contains no CIPHOS LPG map. Run semantic ingestion first."
        )
    if len(scopes) > 1:
        raise ValueError(
            "The semantic store contains multiple CIPHOS LPG maps. Pass --source-scope "
            "or set CIPHOS_SEMANTIC_SOURCE_SCOPE."
        )
    return scopes[0]


def _requested_scope(argument: str | None) -> str | None:
    return argument or os.environ.get("CIPHOS_SEMANTIC_SOURCE_SCOPE", "").strip() or None


def open_source_driver(connection: OperationalNeo4jConnection) -> Any:
    """Open the operational metadata-read driver, verifying connectivity first."""
    driver = _source_driver(connection)
    try:
        driver.verify_connectivity()
    except Exception:
        driver.close()
        raise
    return driver


def open_semantic_store() -> tuple[Any, SemanticStore]:
    """Open the semantic store, verifying connectivity before handing it over."""
    connection = load_semantic_store_connection()
    driver = _driver(connection)
    try:
        driver.verify_connectivity()
    except Exception:
        driver.close()
        raise
    return driver, SemanticStore(driver, connection)


def ingest_main() -> None:
    """Extract, atomically replace, and read-validate the configured semantic map."""
    load_environment()
    source = load_operational_connection()
    store_connection = load_semantic_store_connection()
    source_driver = _source_driver(source)
    store_driver = _driver(store_connection)
    try:
        source_driver.verify_connectivity()
        store_driver.verify_connectivity()
        schema_map = extract_schema_map(source_driver, source.identity)
        store = SemanticStore(store_driver, store_connection)
        ingest_schema_map(store, source, schema_map)
        validate_semantic_map(schema_map, store.read_context(schema_map.source_scope))
    finally:
        source_driver.close()
        store_driver.close()

    print(
        "Ingested and validated CIPHOS LPG metadata "
        f"scope={schema_map.source_scope} nodes={len(schema_map.nodes)} "
        f"relationships={len(schema_map.relationships)} "
        f"properties={len(schema_map.properties)} "
        f"endpoints_available={schema_map.endpoints_available}."
    )


def context_main(argv: Sequence[str] | None = None) -> None:
    """Print one persisted CIPHOS LPG context as canonical JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-scope", help="Persisted source scope; auto-detected if unique.")
    args = parser.parse_args(argv)
    load_environment()
    driver, store = open_semantic_store()
    try:
        scope = resolve_source_scope(store, _requested_scope(args.source_scope))
        context = store.read_context(scope)
    finally:
        driver.close()
    print(json.dumps(context.as_dict(), indent=2, sort_keys=True))


def validate_main() -> None:
    """Compare a fresh metadata-only extraction with the persisted CIPHOS map."""
    load_environment()
    source = load_operational_connection()
    store_connection = load_semantic_store_connection()
    source_driver = _source_driver(source)
    store_driver = _driver(store_connection)
    try:
        source_driver.verify_connectivity()
        store_driver.verify_connectivity()
        schema_map = extract_schema_map(source_driver, source.identity)
        context = SemanticStore(store_driver, store_connection).read_context(
            schema_map.source_scope
        )
        validate_semantic_map(schema_map, context)
    finally:
        source_driver.close()
        store_driver.close()
    print(
        "Validated persisted CIPHOS LPG metadata against a fresh extraction "
        f"for scope={schema_map.source_scope}."
    )


async def _run_mcp_server(
    server: Any,
    *,
    transport: str,
    port: int,
) -> None:
    if transport == "stdio":
        await server.run_stdio_async()
        return
    await server.run_http_async(
        transport="streamable-http",
        host=DEFAULT_MCP_HOST,
        port=port,
    )


def mcp_main(argv: Sequence[str] | None = None) -> None:
    """Run the standalone, semantic-store-only CIPHOS MCP server."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_MCP_PORT)
    parser.add_argument("--source-scope", help="Persisted source scope; auto-detected if unique.")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    load_environment()
    driver, store = open_semantic_store()
    try:
        scope = resolve_source_scope(store, _requested_scope(args.source_scope))

        async def read_context() -> Any:
            return await asyncio.to_thread(store.read_context, scope)

        server = create_ciphos_mcp_server(read_context)
        if args.transport == "streamable-http":
            print(
                f"CIPHOS semantic MCP is listening at "
                f"http://{DEFAULT_MCP_HOST}:{args.port}/mcp",
                file=sys.stderr,
            )
        asyncio.run(
            _run_mcp_server(
                server,
                transport=args.transport,
                port=args.port,
            )
        )
    finally:
        driver.close()


if __name__ == "__main__":
    ingest_main()
