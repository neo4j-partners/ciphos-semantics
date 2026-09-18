"""Live-service tests for the Ask page's backend flow: retrieve, generate, ground, run.

These exercise the real functions behind the Ask button in
`ciphos_semantics.demo.page_ask` -- `semantic_query.retrieve`,
`query_generation.generate_queries`, `grounding.ground`, and the `_run_sql` /
`_run_cypher` helpers -- against the actual external services, using the same
configuration path the app itself uses (`demo.services`, `semantic_index`).
Nothing here mocks the MCP client, the Foundation Model endpoint, the
Databricks SDK, or the Neo4j driver.

The NeoCarta semantic-search MCP server is expected to already be running at
`semantic_query.DEFAULT_MCP_URL` (see `make semantic-search-mcp`), so the
retrieval and grounding tests below always run. The Foundation Model,
Databricks SQL warehouse, and operational Neo4j graph steps each skip
themselves with a specific reason when this environment has none of
`CIPHOS_SEMANTIC_LLM_ENDPOINT`, `DATABRICKS_WAREHOUSE_ID`, or
`OPS_NEO4J_URI` configured (via `.env` or the environment), rather than
mocking those services.
"""

from __future__ import annotations

import unittest

from openai import APIError

from ciphos_semantics import grounding, query_generation
from ciphos_semantics.demo.page_ask import _run_cypher, _run_sql
from ciphos_semantics.demo.services import operational_graph_connection, warehouse_connection
from ciphos_semantics.semantic_index import (
    DEFAULT_CATALOG,
    DEFAULT_INDEXED_TABLES,
    DEFAULT_SCHEMA,
    require_env,
)
from ciphos_semantics.semantic_query import DEFAULT_MCP_URL, SHOWCASE_CASES, retrieve

UNREACHABLE_MCP_URL = "http://127.0.0.1:1/mcp"


def _llm_model() -> str | None:
    """Return the configured Foundation Model endpoint, or None if unset."""
    try:
        return require_env("CIPHOS_SEMANTIC_LLM_ENDPOINT")
    except ValueError:
        return None


def _retrieve(case) -> object:
    return retrieve(
        case.query,
        catalog=DEFAULT_CATALOG,
        schema=DEFAULT_SCHEMA,
        allowed_tables=DEFAULT_INDEXED_TABLES,
        mcp_url=DEFAULT_MCP_URL,
    )


class RetrieveShowcaseTests(unittest.TestCase):
    """`semantic_query.retrieve` against the live NeoCarta MCP server."""

    def test_each_showcase_case_retrieves_its_expected_table_and_column(self) -> None:
        for case in SHOWCASE_CASES:
            with self.subTest(case=case.title):
                trace = _retrieve(case)
                self.assertIn(case.expected_table, trace.table_search.names)
                self.assertIn(case.expected_column, trace.column_search.names)

    def test_an_unreachable_mcp_server_surfaces_as_a_clean_runtime_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "CIPHOS semantic MCP is unavailable"):
            retrieve(
                SHOWCASE_CASES[0].query,
                catalog=DEFAULT_CATALOG,
                schema=DEFAULT_SCHEMA,
                allowed_tables=DEFAULT_INDEXED_TABLES,
                mcp_url=UNREACHABLE_MCP_URL,
            )


class GroundingTests(unittest.TestCase):
    """`grounding.ground` is pure, so it is exercised directly against a trace
    retrieved from the live MCP server -- there is no service to mock here."""

    def test_grounding_marks_retrieved_and_invented_identifiers_from_a_live_trace(self) -> None:
        case = SHOWCASE_CASES[0]
        trace = _retrieve(case)
        qualified_table = f"{DEFAULT_CATALOG}.{DEFAULT_SCHEMA}.{case.expected_table}"
        declared = [
            grounding.DeclaredIdentifier(case.expected_table, "table_search"),
            grounding.DeclaredIdentifier(qualified_table, "table_search"),
            grounding.DeclaredIdentifier(case.expected_column, "column_search"),
            grounding.DeclaredIdentifier("not_a_real_column", "column_search"),
        ]
        rows = {
            row.name: row.retrieved for row in grounding.ground(declared, trace.retrieved_names())
        }
        self.assertTrue(rows[case.expected_table])
        self.assertTrue(rows[qualified_table])
        self.assertTrue(rows[case.expected_column])
        self.assertFalse(rows["not_a_real_column"])


class QueryGenerationLiveTests(unittest.TestCase):
    """`query_generation.generate_queries` against the live Foundation Model endpoint."""

    def setUp(self) -> None:
        self.model = _llm_model()
        if not self.model:
            self.skipTest(
                "CIPHOS_SEMANTIC_LLM_ENDPOINT is not configured in this environment. "
                "Set it, plus Databricks auth (DATABRICKS_HOST/DATABRICKS_PROFILE or "
                "DATABRICKS_TOKEN), in .env to exercise the live Foundation Model endpoint."
            )

    def test_generates_grounded_sql_and_cypher_for_each_showcase_case(self) -> None:
        for case in SHOWCASE_CASES:
            with self.subTest(case=case.title):
                trace = _retrieve(case)
                generated = query_generation.generate_queries(
                    case.query,
                    trace,
                    catalog=DEFAULT_CATALOG,
                    schema=DEFAULT_SCHEMA,
                    model=self.model,
                )
                self.assertTrue(generated.sql.strip())
                self.assertTrue(generated.cypher.strip())
                self.assertTrue(generated.identifiers)

    def test_an_unknown_model_endpoint_surfaces_as_a_clean_error(self) -> None:
        trace = _retrieve(SHOWCASE_CASES[0])
        with self.assertRaises(APIError):
            query_generation.generate_queries(
                SHOWCASE_CASES[0].query,
                trace,
                catalog=DEFAULT_CATALOG,
                schema=DEFAULT_SCHEMA,
                model="this-model-endpoint-does-not-exist",
            )


class RunSqlLiveTests(unittest.TestCase):
    """`_run_sql` against the live Databricks SQL warehouse."""

    def setUp(self) -> None:
        self.warehouse = warehouse_connection()
        if not self.warehouse.ok:
            self.skipTest(f"Databricks SQL warehouse is not configured: {self.warehouse.error}")

    def test_runs_a_trivial_read_only_statement(self) -> None:
        result = _run_sql(self.warehouse, "SELECT 1 AS one")
        self.assertIn("dataframe", result)
        self.assertEqual(result["dataframe"]["one"].tolist(), [1])

    def test_an_invalid_statement_surfaces_as_a_clean_error(self) -> None:
        result = _run_sql(self.warehouse, "SELECT * FROM does_not_exist_table_ciphos_test")
        self.assertIn("error", result)


class RunCypherLiveTests(unittest.TestCase):
    """`_run_cypher` against the live operational Neo4j graph."""

    def setUp(self) -> None:
        self.graph = operational_graph_connection()
        if not self.graph.ok:
            self.skipTest(f"Operational Neo4j graph is not configured: {self.graph.error}")

    def test_runs_a_trivial_read_only_statement(self) -> None:
        result = _run_cypher(self.graph, "RETURN 1 AS one")
        self.assertIn("dataframe", result)
        self.assertEqual(result["dataframe"]["one"].tolist(), [1])

    def test_invalid_cypher_surfaces_as_a_clean_error(self) -> None:
        result = _run_cypher(self.graph, "RETURN not valid cypher (((")
        self.assertIn("error", result)


class FullAskFlowLiveTests(unittest.TestCase):
    """The complete retrieve -> generate -> ground -> run flow, end to end.

    Requires the Foundation Model endpoint, the Databricks warehouse, and the
    operational Neo4j graph to all be configured, since it runs the generated
    SQL and Cypher for real. Skips with a specific reason otherwise.
    """

    def setUp(self) -> None:
        self.model = _llm_model()
        self.warehouse = warehouse_connection()
        self.graph = operational_graph_connection()
        missing = []
        if not self.model:
            missing.append("CIPHOS_SEMANTIC_LLM_ENDPOINT")
        if not self.warehouse.ok:
            missing.append(f"the Databricks warehouse ({self.warehouse.error})")
        if not self.graph.ok:
            missing.append(f"the operational Neo4j graph ({self.graph.error})")
        if missing:
            self.skipTest("Not configured in this environment: " + "; ".join(missing))

    def test_each_showcase_case_runs_end_to_end_without_crashing(self) -> None:
        for case in SHOWCASE_CASES:
            with self.subTest(case=case.title):
                trace = _retrieve(case)
                self.assertIn(case.expected_table, trace.table_search.names)
                self.assertIn(case.expected_column, trace.column_search.names)

                generated = query_generation.generate_queries(
                    case.query,
                    trace,
                    catalog=DEFAULT_CATALOG,
                    schema=DEFAULT_SCHEMA,
                    model=self.model,
                )
                declared = [
                    grounding.DeclaredIdentifier(name, source_tool)
                    for name, source_tool in generated.identifiers
                ]
                grounding.ground(declared, trace.retrieved_names())

                sql_result = _run_sql(self.warehouse, generated.sql)
                self.assertTrue("dataframe" in sql_result or "error" in sql_result)

                cypher_result = _run_cypher(self.graph, generated.cypher)
                self.assertTrue("dataframe" in cypher_result or "error" in cypher_result)


if __name__ == "__main__":
    unittest.main()
