"""Unit tests for the CIPHOS semantic-query selection and grounding boundary."""

from __future__ import annotations

import unittest
from io import StringIO
from typing import Any
from unittest.mock import patch

from ciphos_semantics import semantic_query
from ciphos_semantics.mcp_retrieval import ToolCall, catalog_records, select_search_tool
from ciphos_semantics.query_generation import GeneratedQueries
from ciphos_semantics.semantic_index import (
    DEFAULT_CATALOG,
    DEFAULT_INDEXED_TABLES,
    DEFAULT_SCHEMA,
    embedding_endpoint_model,
    indexed_table_names,
    remove_unselected_tables,
)
from ciphos_semantics.semantic_query import (
    ANSI_BOLD_CYAN,
    ANSI_RESET,
    Console,
    RetrievalTrace,
    require_grounded_identifiers,
)


def trace() -> RetrievalTrace:
    metadata = [
        {
            "table_name": "silver_tag_property_value_enriched",
            "columns": [{"column_name": "tag_number"}, {"column_name": "numeric_value"}],
        }
    ]
    return RetrievalTrace(
        table_search=ToolCall("table", {}, metadata, ("silver_tag_property_value_enriched",)),
        column_search=ToolCall("column", {}, [], ("tag_number", "numeric_value")),
        graph_context=ToolCall("graph", {}, {}, ()),
    )


class SemanticQueryTests(unittest.TestCase):
    def test_execute_sql_polls_until_success(self) -> None:
        responses: list[dict[str, Any]] = [
            {"statement_id": "statement-1", "status": {"state": "PENDING"}},
            {
                "statement_id": "statement-1",
                "status": {"state": "SUCCEEDED"},
                "manifest": {"schema": {"columns": []}},
                "result": {"data_array": []},
            },
        ]
        calls: list[tuple[str, str, str, dict[str, Any] | None]] = []

        def fake_api(
            method: str,
            path: str,
            *,
            profile: str,
            payload: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            calls.append((method, path, profile, payload))
            return responses.pop(0)

        with (
            patch.object(semantic_query, "databricks_api", side_effect=fake_api),
            patch.object(semantic_query.time, "sleep"),
        ):
            response = semantic_query.execute_sql(
                "SELECT 1",
                profile="demo",
                warehouse_id="warehouse-1",
                catalog="catalog",
                schema="ciphos",
            )

        self.assertEqual(response["status"]["state"], "SUCCEEDED")
        self.assertEqual(calls[0][0:3], ("post", "/api/2.0/sql/statements", "demo"))
        self.assertEqual(calls[0][3]["row_limit"], 10)
        self.assertEqual(calls[1], ("get", "/api/2.0/sql/statements/statement-1", "demo", None))

    def test_result_rows_rejects_schema_mismatch(self) -> None:
        response = {
            "manifest": {"schema": {"columns": [{"name": "tag_number"}]}},
            "result": {"data_array": [["PT-100", "unexpected"]]},
        }

        with self.assertRaisesRegex(RuntimeError, "did not match"):
            semantic_query.result_rows(response)

    def test_configure_databricks_profile_uses_one_authentication_source(self) -> None:
        with patch.dict(semantic_query.os.environ, {"DATABRICKS_TOKEN": "token"}, clear=True):
            profile = semantic_query.configure_databricks_profile("demo-profile")

            self.assertEqual(profile, "demo-profile")
            self.assertEqual(semantic_query.os.environ["DATABRICKS_PROFILE"], "demo-profile")
            self.assertEqual(
                semantic_query.os.environ["DATABRICKS_CONFIG_PROFILE"], "demo-profile"
            )
            self.assertNotIn("DATABRICKS_TOKEN", semantic_query.os.environ)

    def test_console_renders_numbered_colored_sections_and_statuses(self) -> None:
        stream = StringIO()
        console = Console(stream=stream)

        console.section(2, "Running semantic retrieval tests")

        self.assertEqual(
            stream.getvalue(),
            f"{ANSI_BOLD_CYAN}\n2. Running semantic retrieval tests{ANSI_RESET}\n",
        )
        self.assertEqual(console.pass_label(), "\033[1;32mPASS\033[0m")
        self.assertEqual(console.fail_label(), "\033[1;31mFAIL\033[0m")

    def test_query_workflow_prints_each_numbered_section(self) -> None:
        stream = StringIO()
        generated_sql = "SELECT tag_number FROM catalog.ciphos.silver_tag_property_value_enriched"
        with (
            patch.object(semantic_query, "Console", side_effect=lambda: Console(stream=stream)),
            patch.object(semantic_query, "load_environment"),
            patch.object(semantic_query, "configure_databricks_profile", return_value="demo"),
            patch.object(semantic_query, "lakehouse_catalog", return_value="catalog"),
            patch.object(semantic_query, "lakehouse_schema", return_value="ciphos"),
            patch.object(semantic_query, "require_env", return_value="endpoint"),
            patch.object(
                semantic_query,
                "indexed_table_names",
                return_value=("silver_tag_property_value_enriched",),
            ),
            patch.object(semantic_query, "retrieve", return_value=trace()),
            patch.object(
                semantic_query.query_generation,
                "generate_queries",
                return_value=GeneratedQueries(
                    sql=generated_sql,
                    cypher="MATCH (tag:Tag) RETURN tag LIMIT 10",
                    identifiers=(("silver_tag_property_value_enriched", "table_search"),),
                ),
            ),
            patch.object(
                semantic_query,
                "execute_sql",
                return_value={
                    "status": {"state": "SUCCEEDED"},
                    "manifest": {"schema": {"columns": [{"name": "tag_number"}]}},
                    "result": {"data_array": [["PT-1"]]},
                },
            ),
            patch("sys.stdout", stream),
        ):
            semantic_query.main(["Which tags have high pressure readings?"])

        output = stream.getvalue()
        for section in (
            "1. Retrieving the SQL shape from NeoCarta MCP",
            "2. Generating SQL from retrieved context",
            "3. Grounding validation",
            "4. Executing SQL through the Databricks CLI",
            "5. Lakehouse results: 1 row(s)",
        ):
            self.assertIn(section, output)
        self.assertIn("All generated identifiers came from NeoCarta.", output)
        self.assertIn('"tag_number": "PT-1"', output)

    def test_default_query_surface_is_the_curated_enriched_silver_view(self) -> None:
        self.assertEqual(indexed_table_names(""), DEFAULT_INDEXED_TABLES)
        self.assertEqual(
            indexed_table_names("silver_tag_property_value_enriched,silver_tag_property_value"),
            ("silver_tag_property_value", "silver_tag_property_value_enriched"),
        )
        with self.assertRaisesRegex(ValueError, "invalid table"):
            indexed_table_names("bronze-node")

    def test_lakehouse_defaults_match_the_publisher_contract(self) -> None:
        self.assertEqual(DEFAULT_CATALOG, "graph-on-databricks")
        self.assertEqual(DEFAULT_SCHEMA, "ciphos-semantics")

    def test_unity_gateway_embedding_name_resolves_to_the_serving_endpoint(self) -> None:
        self.assertEqual(
            embedding_endpoint_model("databricks/system.ai.gte-large-en"),
            "databricks/databricks-gte-large-en",
        )

    def test_catalog_records_excludes_other_schemas_and_unapproved_tables(self) -> None:
        records = catalog_records(
            [
                {
                    "database_name": "catalog",
                    "schema_name": "ciphos",
                    "table_name": "silver_tag_property_value_enriched",
                },
                {
                    "database_name": "catalog",
                    "schema_name": "ciphos",
                    "table_name": "bronze_node_tag",
                },
                {
                    "database_name": "catalog",
                    "schema_name": "other",
                    "table_name": "silver_tag_property_value_enriched",
                },
            ],
            catalog="catalog",
            schema="ciphos",
            allowed_tables=DEFAULT_INDEXED_TABLES,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["table_name"], "silver_tag_property_value_enriched")

    def test_schema_trimming_removes_columns_with_unapproved_tables(self) -> None:
        class Driver:
            def __init__(self) -> None:
                self.kwargs = None

            def execute_query(self, **kwargs):
                self.kwargs = kwargs

        driver = Driver()
        remove_unselected_tables(
            driver,
            database="semantic",
            catalog="catalog",
            schema="ciphos",
            allowed_tables=DEFAULT_INDEXED_TABLES,
        )

        self.assertIn("(table)-[:HAS_COLUMN]->(column:Column)", driver.kwargs["query_"])
        self.assertIn("DETACH DELETE entity", driver.kwargs["query_"])
        self.assertEqual(
            driver.kwargs["parameters_"]["allowed_tables"], list(DEFAULT_INDEXED_TABLES)
        )

    def test_grounding_accepts_qualified_retrieved_names_and_rejects_inventions(self) -> None:
        rows = require_grounded_identifiers(
            (
                ("silver_tag_property_value_enriched", "table_search"),
                ("catalog.ciphos.numeric_value", "column_search"),
            ),
            trace().retrieved_names(),
        )
        self.assertEqual([row.retrieved for row in rows], [True, True])
        with self.assertRaisesRegex(RuntimeError, "not retrieve"):
            require_grounded_identifiers(
                (("invented_column", "column_search"),), trace().retrieved_names()
            )

    def test_search_tool_prefers_hybrid(self) -> None:
        self.assertEqual(
            select_search_tool(
                {
                    "get_context_by_table_full_text_search",
                    "get_context_by_table_hybrid_search",
                },
                "table",
            ),
            "get_context_by_table_hybrid_search",
        )


if __name__ == "__main__":
    unittest.main()
