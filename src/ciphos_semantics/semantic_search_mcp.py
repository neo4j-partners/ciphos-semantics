"""Serve NeoCarta table/column search plus read-only CIPHOS LPG context."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from ciphos_semantics.semantic_cli import (
    DEFAULT_MCP_HOST,
    load_environment,
    open_semantic_store,
    resolve_source_scope,
)
from ciphos_semantics.semantic_index import embedding_endpoint_model
from ciphos_semantics.semantic_mcp import (
    register_ciphos_context_tool,
    semantic_store_context_reader,
)

DEFAULT_MCP_PORT = 8000


async def run_server(*, port: int, source_scope: str | None) -> None:
    """Run NeoCarta's searchable catalog server with the CIPHOS context tool."""
    from neo4j import AsyncGraphDatabase, NotificationMinimumSeverity
    from neocarta._mcp.embeddings import create_embedder
    from neocarta._mcp.server import create_mcp_server
    from neocarta._mcp.settings import mcp_server_settings

    # NeoCarta probes optional metadata components.  They are absent in this
    # deliberately small structural map and are not actionable warnings.
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    context_driver, store = open_semantic_store()
    async_driver = AsyncGraphDatabase.driver(
        mcp_server_settings.neo4j_uri,
        auth=(mcp_server_settings.neo4j_username, mcp_server_settings.neo4j_password),
        warn_notification_severity=NotificationMinimumSeverity.OFF,
    )
    try:
        scope = resolve_source_scope(store, source_scope)
        embedder = create_embedder(async_driver, mcp_server_settings.neo4j_database)
        server = await create_mcp_server(
            async_driver,
            mcp_server_settings.neo4j_database,
            embedder,
        )
        # Register on NeoCarta's server, rather than running a second service,
        # so one query gets vector search and graph-structure context together.
        register_ciphos_context_tool(server, semantic_store_context_reader(store, scope))
        print(
            f"CIPHOS semantic search MCP is listening at http://{DEFAULT_MCP_HOST}:{port}/mcp",
            file=sys.stderr,
        )
        await server.run_http_async(
            transport="streamable-http",
            host=DEFAULT_MCP_HOST,
            port=port,
        )
    finally:
        await async_driver.close()
        context_driver.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_MCP_PORT)
    parser.add_argument(
        "--source-scope", help="Persisted CIPHOS LPG scope; auto-detected if unique."
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Load the isolated store configuration and run the loopback MCP service."""
    args = _parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise ValueError("--port must be between 1 and 65535")
    load_environment()
    embedding_model = os.environ.get("CIPHOS_SEMANTIC_EMBEDDING_MODEL", "").strip()
    if not embedding_model:
        raise ValueError("Set CIPHOS_SEMANTIC_EMBEDDING_MODEL before starting semantic search.")
    os.environ["EMBEDDING_MODEL"] = embedding_endpoint_model(embedding_model)
    asyncio.run(run_server(port=args.port, source_scope=args.source_scope))


if __name__ == "__main__":
    main()
