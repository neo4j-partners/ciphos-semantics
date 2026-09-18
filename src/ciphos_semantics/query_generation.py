"""Generate grounded SQL and Cypher from retrieved CIPHOS semantic-map context.

Query generation calls the configured Databricks Foundation Model serving
endpoint with the retrieved context and the two schemas as the only source of
names, through an OpenAI-compatible client. The prompt lives in this one
module and asks for exactly the structured output the Ask page needs: the
SQL, the Cypher, and the identifiers used, each tagged with the retrieval
tool call it came from. This is separate from `semantic_query.generate_sql`,
which the CLI uses and which deliberately never writes Cypher.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ciphos_semantics.semantic_index import databricks_access_token

if TYPE_CHECKING:
    from ciphos_semantics.mcp_retrieval import RetrievalTrace

SOURCE_TOOLS = ("table_search", "column_search", "graph_context")

SYSTEM_PROMPT = """You write one SQL query over the CIPHOS Databricks lakehouse and one \
Cypher query over the CIPHOS operational Neo4j graph, using only the table, column, \
node-label, and relationship-type names present in the retrieved context you are given. \
Never invent a name that is not in that context.

Rules:
- Qualify every table as `catalog`.`schema`.`table`, using the catalog and schema given.
- Every SQL query carries a LIMIT and never uses DDL or DML.
- Every Cypher query carries a LIMIT and returns scalar property values, never whole \
nodes or relationships.
- List every table, column, node label, and relationship type you used in \
`identifiers`, each tagged with the retrieval tool call it came from: \
"table_search", "column_search", or "graph_context".
- If the retrieved context does not support a joinable query, write your best \
single-table or single-label query instead, and declare exactly the identifiers \
you actually used.
- Every retrieved column carries an `examples` list. Before writing an equality, \
LIKE, or IN filter against a STRING or categorical column, check that list: if the \
literal you want is not present verbatim in it (including when `examples` is empty), \
you have no way to know the real stored values, so do not write that filter at all — \
reference the column only in SELECT or ORDER BY instead. This applies even when the \
question's wording implies a specific value, status, or category. Rely on ORDER BY \
and the LIMIT to surface the most relevant rows instead of guessing a WHERE value. \
Numeric thresholds and boolean equality are exempt from this rule.
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sql": {"type": "string"},
        "cypher": {"type": "string"},
        "identifiers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "source_tool": {"type": "string", "enum": list(SOURCE_TOOLS)},
                },
                "required": ["name", "source_tool"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sql", "cypher", "identifiers"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class GeneratedQueries:
    """Structured output from one Ask click's query-generation call."""

    sql: str
    cypher: str
    identifiers: tuple[tuple[str, str], ...]


def _client() -> Any:
    from openai import OpenAI

    host = os.environ.get("DATABRICKS_HOST", "").strip()
    if not host:
        from databricks.sdk.core import Config

        host = str(Config(profile=os.environ.get("DATABRICKS_PROFILE") or None).host or "")
    if not host:
        raise ValueError("Set DATABRICKS_HOST or configure it in DATABRICKS_PROFILE.")
    return OpenAI(
        base_url=f"{host.rstrip('/')}/serving-endpoints",
        api_key=databricks_access_token(),
    )


def generate_queries(
    question: str, trace: RetrievalTrace, *, catalog: str, schema: str, model: str
) -> GeneratedQueries:
    """Call the configured Foundation Model endpoint for grounded SQL and Cypher."""
    context = {
        "catalog": catalog,
        "schema": schema,
        "question": question,
        "table_search": trace.table_search.result,
        "column_search": trace.column_search.result,
        "graph_context": trace.graph_context.result,
    }
    response = _client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "ciphos_generated_queries",
                "schema": RESPONSE_SCHEMA,
                "strict": True,
            },
        },
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("The configured Foundation Model returned no response.")
    return _parse_generated_queries(content)


def _parse_generated_queries(content: str) -> GeneratedQueries:
    """Validate the source-attributed SQL and Cypher response contract."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "The Foundation Model returned invalid JSON for generated queries."
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("The Foundation Model returned a non-object generated-query response.")

    sql = payload.get("sql")
    cypher = payload.get("cypher")
    identifiers = payload.get("identifiers")
    if not isinstance(sql, str) or not sql.strip():
        raise RuntimeError(
            "The Foundation Model response omitted the required non-empty `sql` field."
        )
    if not isinstance(cypher, str) or not cypher.strip():
        raise RuntimeError(
            "The Foundation Model response omitted the required non-empty `cypher` field."
        )
    if not isinstance(identifiers, list):
        raise RuntimeError("The Foundation Model response omitted the required `identifiers` list.")

    parsed_identifiers: list[tuple[str, str]] = []
    for item in identifiers:
        if not isinstance(item, dict):
            raise RuntimeError("Each Foundation Model identifier must be an object.")
        name = item.get("name")
        source_tool = item.get("source_tool")
        if not isinstance(name, str) or not name:
            raise RuntimeError("Each Foundation Model identifier must have a non-empty `name`.")
        if source_tool not in SOURCE_TOOLS:
            raise RuntimeError(
                "Each Foundation Model identifier must name a valid retrieval `source_tool`."
            )
        parsed_identifiers.append((name, source_tool))
    return GeneratedQueries(sql=sql, cypher=cypher, identifiers=tuple(parsed_identifiers))
