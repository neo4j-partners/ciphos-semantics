"""Tests for read-only standalone CIPHOS semantic MCP tool registration."""

from __future__ import annotations

import asyncio
import inspect
import unittest

from ciphos_semantics.semantic_map_contract import (
    SemanticContext,
    SemanticEdge,
    SemanticRecord,
    SourceIdentity,
)
from ciphos_semantics.semantic_mcp import (
    TOOL_NAME,
    register_ciphos_context_tool,
    semantic_store_context_reader,
)


class FakeServer:
    """Small FastMCP-compatible registration fake, without a FastMCP dependency."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self, *, name: str):
        def register(function):
            self.tools[name] = function
            return function

        return register


def build_context() -> SemanticContext:
    return SemanticContext(
        source_scope="neo4j:test-scope",
        source_identity=SourceIdentity.from_connection(
            "neo4j+s://semantic-source.example.com", "neo4j"
        ),
        endpoints_available=False,
        records=(SemanticRecord("Database", {"id": "database-id", "name": "neo4j"}),),
        edges=(SemanticEdge("database-id", "HAS_SCHEMA", "schema-id"),),
    )


class SemanticMcpTests(unittest.TestCase):
    def test_registers_the_focused_read_only_tool_and_returns_frozen_context(self) -> None:
        server = FakeServer()
        calls: list[str] = []

        def semantic_store_reader() -> SemanticContext:
            calls.append("semantic-store")
            return build_context()

        tool = register_ciphos_context_tool(server, semantic_store_reader)
        response = asyncio.run(tool())

        self.assertIn(TOOL_NAME, server.tools)
        self.assertEqual(server.tools[TOOL_NAME], tool)
        self.assertEqual(calls, ["semantic-store"])
        self.assertEqual(response, build_context().as_dict())
        self.assertIn("no operational values", response["notice"])

    def test_accepts_an_async_semantic_store_reader(self) -> None:
        server = FakeServer()

        async def semantic_store_reader() -> SemanticContext:
            return build_context()

        tool = register_ciphos_context_tool(server, semantic_store_reader)

        self.assertEqual(asyncio.run(tool())["source_scope"], "neo4j:test-scope")

    def test_store_adapter_uses_only_the_injected_store_read_path(self) -> None:
        class StoreFake:
            def __init__(self) -> None:
                self.scopes: list[str] = []

            def read_context(self, scope: str) -> SemanticContext:
                self.scopes.append(scope)
                return build_context()

        store = StoreFake()
        reader = semantic_store_context_reader(store, "neo4j:test-scope")

        self.assertEqual(reader(), build_context())
        self.assertEqual(store.scopes, ["neo4j:test-scope"])

    def test_module_does_not_resolve_operational_configuration(self) -> None:
        import ciphos_semantics.semantic_mcp as semantic_mcp

        source = inspect.getsource(semantic_mcp)

        self.assertNotIn("OPS_NEO4J", source)
        self.assertNotIn("os.getenv", source)


if __name__ == "__main__":
    unittest.main()
