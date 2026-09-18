"""Read-only MCP exposure for an already persisted CIPHOS semantic context.

The module accepts a context reader as an explicit dependency.  It intentionally
does not import configuration or Neo4j driver creation code, ensuring that an
MCP process can be composed solely with the semantic-store connection and never
needs operational-source credentials.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ciphos_semantics.semantic_map_contract import SemanticContext

TOOL_NAME = "get_ciphos_lpg_schema_context"
_ContextResult = SemanticContext | Mapping[str, Any]
ContextReader = Callable[[], _ContextResult | Awaitable[_ContextResult]]


def _response_context(context: _ContextResult) -> dict[str, Any]:
    """Render the frozen response shape without adding mutable operational data."""
    if isinstance(context, SemanticContext):
        return context.as_dict()
    if isinstance(context, Mapping):
        response = dict(context)
        required = {
            "source_scope",
            "source_identity",
            "endpoints_available",
            "records",
            "edges",
            "notice",
        }
        missing = sorted(required - response.keys())
        if missing:
            raise ValueError(f"Stored semantic context is missing required fields: {missing}")
        return response
    raise TypeError("Semantic context reader must return SemanticContext or a context mapping.")


def register_ciphos_context_tool(server: Any, context_reader: ContextReader) -> Callable[[], Any]:
    """Register the one focused, read-only CIPHOS LPG retrieval tool.

    ``context_reader`` is injected by the application composition layer.  It
    may call a semantic-store driver, but this module has no source connection,
    environment lookup, or write capability.
    """
    if not callable(context_reader):
        raise TypeError("context_reader must be callable.")

    @server.tool(name=TOOL_NAME)
    async def get_ciphos_lpg_schema_context() -> dict[str, Any]:
        """Return structural CIPHOS LPG metadata, never operational values."""
        result = context_reader()
        if inspect.isawaitable(result):
            result = await result
        return _response_context(result)

    return get_ciphos_lpg_schema_context


def semantic_store_context_reader(store: Any, source_scope: str) -> ContextReader:
    """Adapt a semantic store's read API to the MCP tool's reader seam.

    The supplied object needs only ``read_context``.  In particular, the
    adapter does not receive an operational connection, so it cannot resolve
    source credentials or route a retrieval request to the source graph.
    """
    if not isinstance(source_scope, str) or not source_scope.strip():
        raise ValueError("source_scope must be a non-empty string.")
    read_context = getattr(store, "read_context", None)
    if not callable(read_context):
        raise TypeError("semantic store must provide a callable read_context method.")

    def read() -> _ContextResult | Awaitable[_ContextResult]:
        return read_context(source_scope)

    return read


def create_ciphos_mcp_server(context_reader: ContextReader) -> Any:
    """Create the standalone CIPHOS server, importing FastMCP only when needed."""
    try:
        from fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError(
            "FastMCP is required to run the CIPHOS semantic MCP server. "
            "Install the project MCP runtime dependency before starting it."
        ) from error

    server = FastMCP("CIPHOS LPG Semantic Context")
    register_ciphos_context_tool(server, context_reader)
    return server


def create_ciphos_mcp_server_for_store(store: Any, source_scope: str) -> Any:
    """Create a server composed solely from an already-configured semantic store."""
    return create_ciphos_mcp_server(semantic_store_context_reader(store, source_scope))
