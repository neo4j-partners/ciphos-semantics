"""Retrieve CIPHOS metadata, generate grounded queries, and execute SQL."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TextIO

from ciphos_semantics import grounding, query_generation
from ciphos_semantics.mcp_retrieval import (
    DEFAULT_MCP_URL,
    RetrievalTrace,
    SemanticMcpUnavailableError,
    retrieve,
)
from ciphos_semantics.semantic_cli import load_environment
from ciphos_semantics.semantic_index import (
    indexed_table_names,
    lakehouse_catalog,
    lakehouse_schema,
    require_env,
)

RUNNING_STATES = frozenset({"PENDING", "RUNNING"})
FAILURE_STATES = frozenset({"FAILED", "CANCELED", "CLOSED"})
POLL_TIMEOUT_SECONDS = 180
DATABRICKS_CLI_TIMEOUT_SECONDS = 65
RESULT_ROW_LIMIT = 10
DEFAULT_SHOWCASE_QUESTION = (
    "Which tags have the highest recorded property values, and which source documents "
    "support them?"
)
ANSI_RESET = "\033[0m"
ANSI_BOLD_CYAN = "\033[1;36m"
ANSI_BOLD_GREEN = "\033[1;32m"
ANSI_BOLD_RED = "\033[1;31m"
ANSI_YELLOW = "\033[33m"


@dataclass(frozen=True)
class ShowcaseCase:
    """One semantic retrieval behavior demonstrated by the CLI showcase."""

    title: str
    query: str
    demonstrates: str
    expected_table: str
    expected_column: str


SHOWCASE_CASES = (
    ShowcaseCase(
        "Literal identifier retrieval",
        "silver_tag_property_value_enriched tag_number property_name",
        "the full-text signal inside hybrid search",
        "silver_tag_property_value_enriched",
        "tag_number",
    ),
    ShowcaseCase(
        "Conceptual retrieval",
        "approved engineering measurements and source-document traceability for process equipment",
        "the vector similarity signal inside hybrid search",
        "silver_tag_property_value_sources",
        "document_number",
    ),
    ShowcaseCase(
        "Mixed semantic and literal retrieval",
        "high pressure tag assets property values and provenance document",
        "hybrid fusion of conceptual language and an exact field name",
        "silver_tag_property_value_enriched",
        "tag_number",
    ),
)


class Console:
    """Small ANSI renderer for readable CLI sections."""

    def __init__(self, *, stream: TextIO = sys.stdout) -> None:
        self.stream = stream

    def styled(self, text: str, ansi: str) -> str:
        """Apply one ANSI style."""
        return f"{ansi}{text}{ANSI_RESET}"

    def section(self, number: int, title: str) -> None:
        """Print a numbered section heading."""
        print(self.styled(f"\n{number}. {title}", ANSI_BOLD_CYAN), file=self.stream, flush=True)

    def pass_label(self) -> str:
        """Return a colored pass marker."""
        return self.styled("PASS", ANSI_BOLD_GREEN)

    def fail_label(self) -> str:
        """Return a colored fail marker."""
        return self.styled("FAIL", ANSI_BOLD_RED)

    def tool_name(self, name: str) -> str:
        """Return a highlighted MCP tool name."""
        return self.styled(name, ANSI_YELLOW)


def _run_databricks_command(command: list[str]) -> dict[str, Any]:
    """Run a Databricks CLI request and decode its JSON response."""
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=DATABRICKS_CLI_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise RuntimeError("The Databricks CLI is not installed or is not on PATH.") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or str(error)
        raise RuntimeError(f"Databricks CLI request failed: {detail}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Databricks CLI request exceeded {DATABRICKS_CLI_TIMEOUT_SECONDS} seconds."
        ) from error

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Databricks CLI returned a non-JSON response.") from error
    if not isinstance(payload, dict):
        raise TypeError("Databricks CLI returned an unexpected JSON response.")
    return payload


def databricks_api(
    method: str,
    path: str,
    *,
    profile: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a workspace REST API through the authenticated Databricks CLI."""
    command = ["databricks", "api", method, path, "--profile", profile, "--output", "json"]
    if payload is None:
        return _run_databricks_command(command)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as request:
        json.dump(payload, request)
        request.flush()
        return _run_databricks_command([*command, "--json", f"@{request.name}"])


def _statement_state(response: dict[str, Any]) -> str:
    """Return the required state from a Statement Execution response."""
    state = response.get("status", {}).get("state")
    if not isinstance(state, str) or not state:
        raise RuntimeError("Databricks statement response did not contain a state.")
    return state


def _statement_id(response: dict[str, Any]) -> str:
    """Return the required statement ID from a Statement Execution response."""
    statement_id = response.get("statement_id")
    if not isinstance(statement_id, str) or not statement_id:
        raise RuntimeError("Databricks statement response did not contain a statement ID.")
    return statement_id


def execute_sql(
    sql: str,
    *,
    profile: str,
    warehouse_id: str,
    catalog: str,
    schema: str,
) -> dict[str, Any]:
    """Execute one bounded statement through the Databricks Statement Execution API."""
    response = databricks_api(
        "post",
        "/api/2.0/sql/statements",
        profile=profile,
        payload={
            "warehouse_id": warehouse_id,
            "catalog": catalog,
            "schema": schema,
            "statement": sql,
            "format": "JSON_ARRAY",
            "disposition": "INLINE",
            "row_limit": RESULT_ROW_LIMIT,
            "byte_limit": 1_000_000,
            "wait_timeout": "50s",
            "on_wait_timeout": "CONTINUE",
        },
    )

    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    state = _statement_state(response)
    statement_id = _statement_id(response) if state in RUNNING_STATES else None
    while state in RUNNING_STATES:
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Databricks statement {statement_id} did not finish within "
                f"{POLL_TIMEOUT_SECONDS} seconds."
            )
        time.sleep(2)
        response = databricks_api(
            "get",
            f"/api/2.0/sql/statements/{statement_id}",
            profile=profile,
        )
        state = _statement_state(response)

    if state in FAILURE_STATES:
        error = response.get("status", {}).get("error", {})
        raise RuntimeError(f"Databricks statement {state}: {error}")
    if state != "SUCCEEDED":
        raise RuntimeError(f"Databricks statement returned unexpected state: {state}")
    return response


def result_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert an inline JSON_ARRAY result into named row objects."""
    columns = response.get("manifest", {}).get("schema", {}).get("columns", [])
    if not isinstance(columns, list):
        raise TypeError("Databricks result columns must be a list.")
    column_names = [column.get("name") for column in columns if isinstance(column, dict)]
    if len(column_names) != len(columns) or not all(
        isinstance(name, str) and name for name in column_names
    ):
        raise TypeError("Databricks result contained an invalid column definition.")

    data = response.get("result", {}).get("data_array", [])
    if not isinstance(data, list):
        raise TypeError("Databricks result data must be a list.")
    try:
        return [dict(zip(column_names, row, strict=True)) for row in data]
    except (TypeError, ValueError) as error:
        raise RuntimeError("Databricks result row did not match the result schema.") from error


def result_is_truncated(response: dict[str, Any]) -> bool:
    """Return whether Statement Execution applied a row or byte limit."""
    return response.get("manifest", {}).get("truncated") is True


def configure_databricks_profile(profile_override: str | None) -> str:
    """Select one profile for both model generation and CLI SQL execution."""
    profile = profile_override or require_env("DATABRICKS_PROFILE")
    os.environ["DATABRICKS_PROFILE"] = profile
    os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
    os.environ.pop("DATABRICKS_TOKEN", None)
    return profile


def search_strategy(tool_name: str) -> str:
    """Return a human-readable strategy name from an MCP tool name."""
    if "business_term_hybrid" in tool_name:
        return "business-term hybrid"
    if "hybrid" in tool_name:
        return "hybrid (vector + full-text)"
    if "vector" in tool_name:
        return "vector similarity"
    if "full_text" in tool_name:
        return "full-text"
    return "unknown"


def showcase_case_passes(case: ShowcaseCase, trace: RetrievalTrace) -> bool:
    """Return whether a showcase retrieval met its declared expectations."""
    table_names = set(trace.table_search.names)
    column_names = set(trace.column_search.names)
    if not table_names and not column_names:
        return False
    return case.expected_table in table_names and case.expected_column in column_names


def require_grounded_identifiers(
    identifiers: Sequence[tuple[str, str]], retrieved_names: set[str]
) -> list[grounding.GroundingRow]:
    """Return grounding rows or reject identifiers absent from retrieved context."""
    rows = grounding.ground(
        [
            grounding.DeclaredIdentifier(name=name, source_tool=source_tool)
            for name, source_tool in identifiers
        ],
        retrieved_names,
    )
    missing = sorted({row.name for row in rows if not row.retrieved})
    if missing:
        raise RuntimeError(
            "Generated query used identifiers that NeoCarta did not retrieve: " + ", ".join(missing)
        )
    return rows


def run_semantic_showcase(
    *,
    catalog: str,
    schema: str,
    tables: tuple[str, ...],
    mcp_url: str,
    console: Console,
    section_number: int,
) -> int:
    """Exercise literal, conceptual, and hybrid CIPHOS retrieval."""
    traces = [
        (
            case,
            retrieve(
                case.query,
                catalog=catalog,
                schema=schema,
                allowed_tables=tables,
                mcp_url=mcp_url,
            ),
        )
        for case in SHOWCASE_CASES
    ]
    first_trace = traces[0][1]
    console.section(section_number, "Discovering NeoCarta capabilities")
    print(
        "Table retrieval: "
        f"{search_strategy(first_trace.table_search.tool_name)} via "
        f"{console.tool_name(first_trace.table_search.tool_name)}",
        file=console.stream,
    )
    print(
        "Column retrieval: "
        f"{search_strategy(first_trace.column_search.tool_name)} via "
        f"{console.tool_name(first_trace.column_search.tool_name)}",
        file=console.stream,
    )
    print(
        "NeoCarta registers the strongest available strategy per metadata label. "
        "With vector and full-text indexes present, one hybrid tool exercises both signals.",
        file=console.stream,
    )

    section_number += 1
    console.section(section_number, "Running semantic retrieval tests")
    failed_cases: list[str] = []
    for index, (case, trace) in enumerate(traces, start=1):
        passed = showcase_case_passes(case, trace)
        status = console.pass_label() if passed else console.fail_label()
        print(f"\n  Test {index}: {case.title} [{status}]", file=console.stream)
        print(f"  Demonstrates: {case.demonstrates}", file=console.stream)
        print(f"  Query: {case.query}", file=console.stream)
        print(f"  Tables: {', '.join(trace.table_search.names) or '(none)'}", file=console.stream)
        print(f"  Columns: {', '.join(trace.column_search.names) or '(none)'}", file=console.stream)
        if not passed:
            failed_cases.append(case.title)

    print(
        f"\n  Graph schema context: {len(first_trace.graph_context.names)} "
        "labels, relationship types, and properties retrieved",
        file=console.stream,
    )
    print(f"  Source boundary: {catalog}.{schema}", file=console.stream)
    if failed_cases:
        raise RuntimeError("Semantic showcase failed: " + ", ".join(failed_cases))
    return section_number + 1


def run_query_workflow(
    question: str,
    *,
    profile: str,
    catalog: str,
    schema: str,
    tables: tuple[str, ...],
    mcp_url: str,
    console: Console,
    section_number: int,
) -> None:
    """Run retrieval, source-attributed generation, grounding, and SQL execution."""
    console.section(section_number, "Retrieving the SQL shape from NeoCarta MCP")
    trace = retrieve(
        question,
        catalog=catalog,
        schema=schema,
        allowed_tables=tables,
        mcp_url=mcp_url,
    )
    print(f"Question: {question}", file=console.stream)
    print(
        f"Table tool:  {console.tool_name(trace.table_search.tool_name)}", file=console.stream
    )
    print(
        f"Column tool: {console.tool_name(trace.column_search.tool_name)}", file=console.stream
    )
    print(f"Tables:  {', '.join(trace.table_search.names) or '(none)'}", file=console.stream)
    print(f"Columns: {', '.join(trace.column_search.names) or '(none)'}", file=console.stream)

    section_number += 1
    console.section(section_number, "Generating SQL from retrieved context")
    model = require_env("CIPHOS_SEMANTIC_LLM_ENDPOINT")
    print(f"Model: {model}", file=console.stream)
    generated = query_generation.generate_queries(
        question,
        trace,
        catalog=catalog,
        schema=schema,
        model=model,
    )
    print(generated.sql, file=console.stream)

    grounding_rows = require_grounded_identifiers(generated.identifiers, trace.retrieved_names())
    section_number += 1
    console.section(section_number, "Grounding validation")
    print(
        console.styled("All generated identifiers came from NeoCarta.", ANSI_BOLD_GREEN),
        file=console.stream,
    )
    for row in grounding_rows:
        print(f"  [ok] {row.name} <- {row.source_tool}", file=console.stream)

    section_number += 1
    console.section(section_number, "Executing SQL through the Databricks CLI")
    response = execute_sql(
        generated.sql,
        profile=profile,
        warehouse_id=require_env("DATABRICKS_WAREHOUSE_ID"),
        catalog=catalog,
        schema=schema,
    )

    rows = result_rows(response)
    section_number += 1
    console.section(section_number, f"Lakehouse results: {len(rows)} row(s)")
    print(json.dumps(rows, indent=2), file=console.stream)
    if result_is_truncated(response):
        print(
            f"\nResult was truncated to the first {RESULT_ROW_LIMIT} rows "
            "or by the 1 MB response limit.",
            file=console.stream,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Use CIPHOS NeoCarta MCP context to generate and run a grounded SQL query."
    )
    parser.add_argument("question", nargs="?", help="Natural-language CIPHOS lakehouse question.")
    parser.add_argument("--profile", help="Databricks CLI profile; defaults to DATABRICKS_PROFILE.")
    parser.add_argument(
        "--mcp-url",
        default=DEFAULT_MCP_URL,
        help=f"Persistent CIPHOS NeoCarta MCP URL (default: {DEFAULT_MCP_URL})",
    )
    parser.add_argument(
        "--showcase",
        action="store_true",
        help="Run literal, conceptual, and hybrid retrieval tests before the SQL workflow.",
    )
    return parser


def _run(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    load_environment()
    profile = configure_databricks_profile(args.profile)
    catalog = lakehouse_catalog()
    schema = lakehouse_schema()
    tables = indexed_table_names()
    question = args.question or DEFAULT_SHOWCASE_QUESTION
    console = Console()

    section_number = 1
    if args.showcase or args.question is None:
        section_number = run_semantic_showcase(
            catalog=catalog,
            schema=schema,
            tables=tables,
            mcp_url=args.mcp_url,
            console=console,
            section_number=section_number,
        )
    run_query_workflow(
        question,
        profile=profile,
        catalog=catalog,
        schema=schema,
        tables=tables,
        mcp_url=args.mcp_url,
        console=console,
        section_number=section_number,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Run the CIPHOS semantic-query workflow with concise expected failures."""
    try:
        _run(argv)
    except SemanticMcpUnavailableError as error:
        print(f"\n{error}", file=sys.stderr)
        raise SystemExit(2) from error
    except (RuntimeError, ValueError) as error:
        console = Console(stream=sys.stderr)
        print(console.styled(f"\nError: {error}", ANSI_BOLD_RED), file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
