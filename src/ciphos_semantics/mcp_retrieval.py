"""One-shot retrieval from the separately running CIPHOS NeoCarta MCP server."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

DEFAULT_MCP_URL = "http://127.0.0.1:8010/mcp"
SEARCH_TOOL_PRIORITIES = {
    "table": (
        "get_context_by_table_business_term_hybrid_search",
        "get_context_by_table_hybrid_search",
        "get_context_by_table_vector_search",
        "get_context_by_table_full_text_search",
    ),
    "column": (
        "get_context_by_column_business_term_hybrid_search",
        "get_context_by_column_hybrid_search",
        "get_context_by_column_vector_search",
        "get_context_by_column_full_text_search",
    ),
}


class SemanticMcpUnavailableError(RuntimeError):
    """Raised when the persistent CIPHOS MCP server cannot be reached."""


def mcp_startup_instructions(mcp_url: str) -> str:
    """Return actionable recovery text for an unavailable MCP endpoint."""
    return (
        f"CIPHOS semantic MCP is unavailable at {mcp_url}. Start it in a separate terminal:\n"
        "  make semantic-search-mcp\n"
        "Leave that terminal running, then run this query again."
    )


@dataclass(frozen=True)
class ToolCall:
    """One MCP tool invocation, its response, and its retrieved names."""

    tool_name: str
    arguments: dict[str, Any]
    result: Any
    names: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalTrace:
    """The CIPHOS table, column, and LPG-context retrieval calls."""

    table_search: ToolCall
    column_search: ToolCall
    graph_context: ToolCall

    def retrieved_names(self) -> set[str]:
        """Flatten all identifiers returned by the three retrieval calls."""
        return (
            _catalog_identifiers(self.table_search.result)
            | _catalog_identifiers(self.column_search.result)
            | set(self.graph_context.names)
        )


def select_search_tool(tool_names: set[str], entity: str) -> str:
    """Choose NeoCarta's strongest installed search mode for one metadata entity."""
    try:
        candidates = SEARCH_TOOL_PRIORITIES[entity]
    except KeyError as error:
        raise ValueError(f"Unsupported semantic search entity: {entity}") from error
    for candidate in candidates:
        if candidate in tool_names:
            return candidate
    raise RuntimeError(f"NeoCarta did not register a {entity} semantic-search tool.")


def parse_tool_payload(result: Any) -> Any:
    """Decode the first JSON text response from an MCP tool invocation."""
    for content in result.content:
        text = getattr(content, "text", None)
        if text:
            return json.loads(text)
    return None


def catalog_records(
    records: Any, *, catalog: str, schema: str, allowed_tables: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Keep only the configured CIPHOS Silver query surface from a tool payload."""
    if not isinstance(records, list):
        raise TypeError("NeoCarta catalog search returned a non-list payload.")
    return [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("database_name") == catalog
        and record.get("schema_name") == schema
        and record.get("table_name") in allowed_tables
    ]


def _table_names(records: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(sorted({str(record["table_name"]) for record in records}))


def _column_names(records: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(column["column_name"])
                for record in records
                for column in record.get("columns", [])
                if isinstance(column, dict) and column.get("column_name")
            }
        )
    )


def _catalog_identifiers(result: Any) -> set[str]:
    """Return every table and column identifier in a catalog search result."""
    if not isinstance(result, list):
        return set()

    names: set[str] = set()
    for record in result:
        if not isinstance(record, dict):
            continue
        table_name = record.get("table_name")
        if isinstance(table_name, str) and table_name:
            names.add(table_name)
        for column in record.get("columns", []):
            if isinstance(column, dict) and isinstance(column.get("column_name"), str):
                names.add(column["column_name"])
    return names


def _graph_context_names(context: Any) -> tuple[str, ...]:
    """Return CIPHOS node labels, relationship types, and property names."""
    if not isinstance(context, dict):
        return ()

    names: set[str] = set()
    for record in context.get("records", []):
        if not isinstance(record, dict):
            continue
        for field in ("label", "type", "name"):
            value = record.get(field)
            if isinstance(value, str) and value:
                names.add(value)
        additional_labels = record.get("additional_labels", [])
        if isinstance(additional_labels, list):
            names.update(
                label for label in additional_labels if isinstance(label, str) and label
            )
    return tuple(sorted(names))


async def _run_retrieval(
    question: str,
    *,
    catalog: str,
    schema: str,
    allowed_tables: tuple[str, ...],
    mcp_url: str,
) -> RetrievalTrace:
    try:
        async with (
            streamable_http_client(mcp_url) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            table_tool = select_search_tool(tools, "table")
            column_tool = select_search_tool(tools, "column")
            table_arguments = {"text_content": question, "max_tables": 5}
            table_result = catalog_records(
                parse_tool_payload(await session.call_tool(table_tool, table_arguments)),
                catalog=catalog,
                schema=schema,
                allowed_tables=allowed_tables,
            )
            column_arguments = {"text_content": question, "max_tables": 5}
            column_result = catalog_records(
                parse_tool_payload(await session.call_tool(column_tool, column_arguments)),
                catalog=catalog,
                schema=schema,
                allowed_tables=allowed_tables,
            )
            graph_arguments: dict[str, Any] = {}
            graph_result = parse_tool_payload(
                await session.call_tool("get_ciphos_lpg_schema_context", graph_arguments)
            )
    except* httpx.HTTPError as error:
        raise SemanticMcpUnavailableError(mcp_startup_instructions(mcp_url)) from error

    return RetrievalTrace(
        table_search=ToolCall(
            table_tool,
            table_arguments,
            table_result,
            _table_names(table_result),
        ),
        column_search=ToolCall(
            column_tool,
            column_arguments,
            column_result,
            _column_names(column_result),
        ),
        graph_context=ToolCall(
            "get_ciphos_lpg_schema_context",
            graph_arguments,
            graph_result,
            _graph_context_names(graph_result),
        ),
    )


def retrieve(
    question: str,
    *,
    catalog: str,
    schema: str,
    allowed_tables: tuple[str, ...],
    mcp_url: str = DEFAULT_MCP_URL,
) -> RetrievalTrace:
    """Run one retrieval against the persistent MCP server in a fresh event loop."""
    return asyncio.run(
        _run_retrieval(
            question,
            catalog=catalog,
            schema=schema,
            allowed_tables=allowed_tables,
            mcp_url=mcp_url,
        )
    )
