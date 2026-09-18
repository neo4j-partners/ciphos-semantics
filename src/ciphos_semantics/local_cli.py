"""Start, seed, and accept the disposable local CIPHOS Neo4j environment.

``up`` is the project's local acceptance harness.  It runs the same sequence the
semantics proposal requires before retrieval is enabled: ingest, drift
validation, a second ingestion for idempotency, a source-scope isolation proof,
a deliberately failed write, and an in-process MCP retrieval.  Every check runs
against throwaway containers, so a failure here is a code defect rather than an
operational incident.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from neo4j import RoutingControl
from neo4j.exceptions import Neo4jError

from ciphos_semantics.local_neo4j import LOCAL_NEO4J_FLAG
from ciphos_semantics.neo4j_schema_extract import extract_schema_map
from ciphos_semantics.semantic_cli import (
    context_main,
    ingest_main,
    load_environment,
    open_semantic_store,
    open_source_driver,
    resolve_source_scope,
    validate_main,
)
from ciphos_semantics.semantic_config import load_operational_connection
from ciphos_semantics.semantic_map_contract import SchemaMap, SemanticContext
from ciphos_semantics.semantic_mcp import TOOL_NAME, create_ciphos_mcp_server_for_store
from ciphos_semantics.semantic_store import SemanticStore
from ciphos_semantics.validate_semantic_map import validate_semantic_map

PROJECT_DIR = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_DIR / "docker-compose.semantic-test.yml"
FOREIGN_SCOPE = "neo4j:0000000000000000"
FOREIGN_SCOPE_ID = f"{FOREIGN_SCOPE}:database:local-isolation-probe"

WRITE_FOREIGN_SCOPE_CYPHER = """
MERGE (probe:Database {id: $id})
SET probe.source_scope = $source_scope,
    probe.name = 'isolation-probe'
"""
COUNT_FOREIGN_SCOPE_CYPHER = """
MATCH (probe:Database {id: $id, source_scope: $source_scope})
RETURN count(probe) AS probe_count
"""
DELETE_FOREIGN_SCOPE_CYPHER = """
MATCH (probe:Database {id: $id, source_scope: $source_scope})
DETACH DELETE probe
"""


def _compose(*arguments: str) -> None:
    """Run the project-local Compose file with the caller's intact environment."""
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *arguments],
        check=True,
        cwd=PROJECT_DIR,
    )


def _step(message: str) -> None:
    print(f"==> {message}", flush=True)


def _store_write(driver: Any, store: SemanticStore, query: str, **parameters: Any) -> list[Any]:
    records, _, _ = driver.execute_query(
        query_=query,
        parameters_=parameters,
        database_=store.connection.database,
        routing_=RoutingControl.WRITE,
    )
    return list(records)


def _check_endpoints_are_available(context: SemanticContext) -> None:
    """Guard the live behaviour no fixture-driven test can reach.

    ``db.schema.visualization`` hands back virtual relationships whose
    ``startNode`` is a label-less stub, so an endpoint query that dereferences
    the relationship instead of joining the procedure's own ``nodes`` column
    reports every endpoint as unavailable.  Unit tests feed already-shaped
    endpoint rows and cannot see that, so the seeded source asserts it here.
    """
    if not context.endpoints_available:
        raise RuntimeError(
            "The seeded local source has relationships, so endpoint extraction must "
            "succeed. Endpoint labels come from the nodes column of "
            "db.schema.visualization, not from startNode of an unwound relationship."
        )
    endpoint_kinds = {"HAS_SOURCE_NODE", "HAS_TARGET_NODE"}
    missing = sorted(endpoint_kinds - {edge.kind for edge in context.edges})
    if missing:
        raise RuntimeError(f"Persisted map is missing endpoint links: {', '.join(missing)}.")


def _check_scope_isolation(driver: Any, store: SemanticStore, schema_map: SchemaMap) -> None:
    """Prove replacement deletes only the scope it is replacing."""
    parameters = {"id": FOREIGN_SCOPE_ID, "source_scope": FOREIGN_SCOPE}
    _store_write(driver, store, WRITE_FOREIGN_SCOPE_CYPHER, **parameters)
    try:
        store.replace(schema_map)
        records = _store_write(driver, store, COUNT_FOREIGN_SCOPE_CYPHER, **parameters)
        if not records or int(records[0]["probe_count"]) != 1:
            raise RuntimeError(
                "Scoped replacement deleted a node belonging to another source scope."
            )
    finally:
        _store_write(driver, store, DELETE_FOREIGN_SCOPE_CYPHER, **parameters)


def _unstorable_map(schema_map: SchemaMap) -> SchemaMap:
    """Return the same map with one property value Neo4j refuses to store."""
    if not schema_map.properties:
        raise RuntimeError("The seeded source must report at least one property.")
    properties = [dict(row) for row in schema_map.properties]
    properties[0]["type"] = {"unstorable": ["nested", "map"]}
    return replace(schema_map, properties=tuple(properties))


def _check_failed_write_leaves_no_partial_scope(
    store: SemanticStore, schema_map: SchemaMap
) -> None:
    """Prove a rejected replacement rolls back its own scope deletion."""
    try:
        store.replace(_unstorable_map(schema_map))
    except Neo4jError as error:
        print(f"    rejected as expected: {type(error).__name__}", flush=True)
    else:
        raise RuntimeError("A deliberately unstorable property value was accepted.")
    validate_semantic_map(schema_map, store.read_context(schema_map.source_scope))


async def _retrieve_through_mcp(store: SemanticStore, scope: str) -> dict[str, Any]:
    from fastmcp import Client

    server = create_ciphos_mcp_server_for_store(store, scope)
    async with Client(server) as client:
        tool_names = [tool.name for tool in await client.list_tools()]
        if tool_names != [TOOL_NAME]:
            raise RuntimeError(f"The CIPHOS MCP server exposed unexpected tools: {tool_names}.")
        result = await client.call_tool(TOOL_NAME, {})
    return json.loads(result.content[0].text)


def _check_mcp_retrieval(store: SemanticStore, scope: str) -> None:
    """Prove the one read-only tool returns exactly the persisted context."""
    payload = asyncio.run(_retrieve_through_mcp(store, scope))
    if payload != store.read_context(scope).as_dict():
        raise RuntimeError("The MCP tool response differs from the persisted semantic context.")


def _accept() -> None:
    """Run every local acceptance check against the seeded containers."""
    source = load_operational_connection()
    source_driver = open_source_driver(source)
    store_driver, store = open_semantic_store()
    try:
        schema_map = extract_schema_map(source_driver, source.identity)
        scope = resolve_source_scope(store, schema_map.source_scope)
        context = store.read_context(scope)

        _step("Checking that endpoint extraction produced source and target links")
        _check_endpoints_are_available(context)

        # The replacements below deliberately call the store directly.  The
        # target guards already ran during ingestion, and these checks are about
        # transaction behaviour rather than configuration safety.
        _step("Proving scoped replacement leaves a foreign source scope intact")
        _check_scope_isolation(store_driver, store, schema_map)

        _step("Proving a failed write leaves no partial scope behind")
        _check_failed_write_leaves_no_partial_scope(store, schema_map)

        _step("Retrieving the persisted map through the read-only MCP tool")
        _check_mcp_retrieval(store, scope)

        print(
            f"    scope={scope} records={len(context.records)} edges={len(context.edges)} "
            f"endpoints_available={context.endpoints_available}",
            flush=True,
        )
    finally:
        source_driver.close()
        store_driver.close()


def up() -> None:
    """Start and seed local containers, then accept the local semantic store."""
    os.environ[LOCAL_NEO4J_FLAG] = "true"
    _compose("up", "-d")
    _compose("wait", "seed-source")
    load_environment()

    _step("Ingesting the seeded source schema into the local semantic store")
    ingest_main()
    _step("Comparing the persisted map with a fresh extraction")
    validate_main()
    _step("Re-ingesting to prove the replacement is idempotent")
    ingest_main()
    validate_main()
    _accept()
    _step("Persisted structural context")
    context_main([])


def down() -> None:
    """Remove the disposable containers and their Docker volumes."""
    _compose("down", "--volumes")


def main(argv: Sequence[str] | None = None) -> None:
    """Run the local environment lifecycle command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("up", "down"),
        default="up",
        nargs="?",
        help="up starts, seeds, and accepts the local flow; down removes containers and volumes.",
    )
    args = parser.parse_args(argv)
    if args.command == "up":
        up()
    else:
        down()


if __name__ == "__main__":
    main()
