"""Retrieve CIPHOS metadata semantically, generate grounded SQL, and run it."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ciphos_semantics.semantic_cli import load_environment
from ciphos_semantics.semantic_index import (
    databricks_access_token,
    indexed_table_names,
    lakehouse_catalog,
    lakehouse_schema,
    require_env,
)

DEFAULT_MCP_URL = "http://127.0.0.1:8010/mcp"
DEFAULT_QUESTION = "Which tags have high pressure readings and which source documents support them?"
RESULT_ROW_LIMIT = 10
POLL_TIMEOUT_SECONDS = 180
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


@dataclass(frozen=True)
class ToolCall:
    """One semantic MCP invocation and the qualified CIPHOS records it returned."""

    tool_name: str
    result: Any
    names: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalTrace:
    """The metadata that is permitted to ground one generated SQL statement."""

    table_search: ToolCall
    column_search: ToolCall
    graph_context: ToolCall

    def retrieved_names(self) -> set[str]:
        """Return every table and column name sent to the SQL generator."""
        return (
            set(self.table_search.names)
            | set(self.column_search.names)
            | set(column_names(self.table_search.result))
            | set(column_names(self.column_search.result))
        )


@dataclass(frozen=True)
class ShowcaseCase:
    title: str
    query: str
    expected_table: str
    expected_column: str


SHOWCASE_CASES = (
    ShowcaseCase(
        "Literal identifier retrieval",
        "silver_tag_property_value_enriched tag_number property_name",
        "silver_tag_property_value_enriched",
        "tag_number",
    ),
    ShowcaseCase(
        "Conceptual retrieval",
        "approved engineering measurements and source-document traceability for process equipment",
        "silver_tag_property_value_sources",
        "document_number",
    ),
    ShowcaseCase(
        "Mixed semantic and literal retrieval",
        "high pressure tag assets property values and provenance document",
        "silver_tag_property_value_enriched",
        "tag_number",
    ),
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


def table_names(records: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(sorted({str(record["table_name"]) for record in records}))


def column_names(records: list[dict[str, Any]]) -> tuple[str, ...]:
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


async def _retrieve(
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
            arguments = {"text_content": question, "max_tables": 5}
            table_result = catalog_records(
                parse_tool_payload(await session.call_tool(table_tool, arguments)),
                catalog=catalog,
                schema=schema,
                allowed_tables=allowed_tables,
            )
            column_result = catalog_records(
                parse_tool_payload(await session.call_tool(column_tool, arguments)),
                catalog=catalog,
                schema=schema,
                allowed_tables=allowed_tables,
            )
            graph_result = parse_tool_payload(
                await session.call_tool("get_ciphos_lpg_schema_context", {})
            )
    except* httpx.HTTPError as error:
        raise RuntimeError(
            f"CIPHOS semantic MCP is unavailable at {mcp_url}. Start it with "
            "`make semantic-search-mcp` and leave it running."
        ) from error
    return RetrievalTrace(
        table_search=ToolCall(table_tool, table_result, table_names(table_result)),
        column_search=ToolCall(column_tool, column_result, column_names(column_result)),
        graph_context=ToolCall("get_ciphos_lpg_schema_context", graph_result, ()),
    )


def retrieve(
    question: str,
    *,
    catalog: str,
    schema: str,
    allowed_tables: tuple[str, ...],
    mcp_url: str,
) -> RetrievalTrace:
    """Run one retrieval in a fresh event loop for a conventional CLI invocation."""
    return asyncio.run(
        _retrieve(
            question,
            catalog=catalog,
            schema=schema,
            allowed_tables=allowed_tables,
            mcp_url=mcp_url,
        )
    )


def generate_sql(
    question: str,
    trace: RetrievalTrace,
    *,
    catalog: str,
    schema: str,
    model: str,
) -> tuple[str, tuple[str, ...]]:
    """Ask the configured Foundation Model for one SQL statement and its used names."""
    from openai import OpenAI

    prompt = {
        "question": question,
        "catalog": catalog,
        "schema": schema,
        "table_metadata": trace.table_search.result,
        "column_metadata": trace.column_search.result,
        "graph_structure": trace.graph_context.result,
    }
    response_schema = {
        "type": "object",
        "properties": {
            "sql": {"type": "string"},
            "identifiers": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["sql", "identifiers"],
        "additionalProperties": False,
    }
    host = os.environ.get("DATABRICKS_HOST", "").strip()
    if not host:
        from databricks.sdk.core import Config

        host = str(Config(profile=os.environ.get("DATABRICKS_PROFILE") or None).host or "")
    if not host:
        raise ValueError("Set DATABRICKS_HOST or configure it in DATABRICKS_PROFILE.")
    client = OpenAI(
        base_url=f"{host.rstrip('/')}/serving-endpoints",
        api_key=databricks_access_token(),
    )
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Write exactly one read-only Databricks SQL query using only table and "
                    "column names in the supplied table_metadata and column_metadata. "
                    "Use only the supplied catalog and schema, qualify every table, include "
                    f"LIMIT {RESULT_ROW_LIMIT} or less, and never use DDL or DML. Return "
                    "JSON with sql and every identifier used. Graph structure is explanatory "
                    "context only: do not write Cypher or invent a graph property."
                ),
            },
            {"role": "user", "content": json.dumps(prompt)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "ciphos_sql", "schema": response_schema, "strict": True},
        },
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("The configured Foundation Model returned no SQL response.")
    payload = json.loads(content)
    identifiers = tuple(str(name) for name in payload["identifiers"])
    return str(payload["sql"]), identifiers


def require_grounded_identifiers(
    identifiers: Sequence[str], trace: RetrievalTrace, *, catalog: str, schema: str
) -> None:
    """Reject declared identifiers that were absent from table or column retrieval.

    The catalog and schema names are static configuration the model is required to
    qualify every table with, not something semantic retrieval returns, so they are
    always grounded.
    """
    retrieved = trace.retrieved_names() | {catalog, schema}
    missing = sorted(
        {
            identifier
            for identifier in identifiers
            if identifier not in retrieved and identifier.rsplit(".", 1)[-1] not in retrieved
        }
    )
    if missing:
        raise RuntimeError(
            "Generated SQL used identifiers not returned by semantic retrieval: "
            + ", ".join(missing)
        )


def _databricks_api(
    method: str,
    path: str,
    *,
    profile: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    command = ["databricks", "api", method, path, "--profile", profile, "--output", "json"]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as request:
        if payload is not None:
            json.dump(payload, request)
            request.flush()
            command.extend(["--json", f"@{request.name}"])
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=65)
    response = json.loads(completed.stdout)
    if not isinstance(response, dict):
        raise TypeError("Databricks CLI returned an unexpected response.")
    return response


def execute_sql(sql: str, *, catalog: str, schema: str) -> list[dict[str, Any]]:
    """Execute one bounded statement through the authenticated Databricks CLI profile."""
    profile = os.environ.get("DATABRICKS_PROFILE") or os.environ.get("DATABRICKS_CONFIG_PROFILE")
    if not profile:
        raise ValueError("Set DATABRICKS_PROFILE before executing a semantic query.")
    response = _databricks_api(
        "post",
        "/api/2.0/sql/statements",
        profile=profile,
        payload={
            "warehouse_id": require_env("DATABRICKS_WAREHOUSE_ID"),
            "catalog": catalog,
            "schema": schema,
            "statement": sql,
            "format": "JSON_ARRAY",
            "disposition": "INLINE",
            "row_limit": RESULT_ROW_LIMIT,
            "wait_timeout": "50s",
        },
    )
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while response.get("status", {}).get("state") in {"PENDING", "RUNNING"}:
        statement_id = response.get("statement_id")
        if not isinstance(statement_id, str) or time.monotonic() >= deadline:
            raise RuntimeError("Databricks SQL statement did not complete within the allowed time.")
        time.sleep(2)
        response = _databricks_api(
            "get", f"/api/2.0/sql/statements/{statement_id}", profile=profile
        )
    if response.get("status", {}).get("state") != "SUCCEEDED":
        raise RuntimeError(f"Databricks SQL failed: {response.get('status', {}).get('error')}")
    columns = response.get("manifest", {}).get("schema", {}).get("columns", [])
    names = [column.get("name") for column in columns if isinstance(column, dict)]
    rows = response.get("result", {}).get("data_array", [])
    if len(names) != len(columns) or not all(isinstance(name, str) for name in names):
        raise RuntimeError("Databricks SQL returned invalid column metadata.")
    return [dict(zip(names, values, strict=True)) for values in rows]


def _showcase(catalog: str, schema: str, tables: tuple[str, ...], mcp_url: str) -> None:
    for case in SHOWCASE_CASES:
        trace = retrieve(
            case.query,
            catalog=catalog,
            schema=schema,
            allowed_tables=tables,
            mcp_url=mcp_url,
        )
        passed = (
            case.expected_table in trace.table_search.names
            and case.expected_column in trace.column_search.names
        )
        print(f"{case.title}: {'PASS' if passed else 'FAIL'}")
        print(f"  tables: {', '.join(trace.table_search.names) or '(none)'}")
        print(f"  columns: {', '.join(trace.column_search.names) or '(none)'}")
        if not passed:
            raise RuntimeError(f"Semantic showcase failed: {case.title}")


def main(argv: Sequence[str] | None = None) -> None:
    """Run the CIPHOS semantic-search showcase or one grounded SQL question."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", help="CIPHOS lakehouse question to answer.")
    parser.add_argument("--mcp-url", default=DEFAULT_MCP_URL)
    parser.add_argument("--showcase", action="store_true")
    args = parser.parse_args(argv)
    load_environment()
    catalog = lakehouse_catalog()
    schema = lakehouse_schema()
    tables = indexed_table_names()
    if args.showcase or args.question is None:
        _showcase(catalog, schema, tables, args.mcp_url)
    question = args.question or DEFAULT_QUESTION
    trace = retrieve(
        question,
        catalog=catalog,
        schema=schema,
        allowed_tables=tables,
        mcp_url=args.mcp_url,
    )
    print(f"Question: {question}")
    print(f"Tables: {', '.join(trace.table_search.names) or '(none)'}")
    print(f"Columns: {', '.join(trace.column_search.names) or '(none)'}")
    sql, identifiers = generate_sql(
        question,
        trace,
        catalog=catalog,
        schema=schema,
        model=require_env("CIPHOS_SEMANTIC_LLM_ENDPOINT"),
    )
    require_grounded_identifiers(identifiers, trace, catalog=catalog, schema=schema)
    print("Grounding: PASS")
    print(sql)
    print(json.dumps(execute_sql(sql, catalog=catalog, schema=schema), indent=2))


if __name__ == "__main__":
    main()
