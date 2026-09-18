"""Unit tests for the CIPHOS semantic-query selection and grounding boundary."""

from __future__ import annotations

import unittest

from ciphos_semantics.semantic_index import (
    DEFAULT_CATALOG,
    DEFAULT_INDEXED_TABLES,
    DEFAULT_SCHEMA,
    embedding_endpoint_model,
    indexed_table_names,
    remove_unselected_tables,
)
from ciphos_semantics.semantic_query import (
    RetrievalTrace,
    ToolCall,
    catalog_records,
    require_grounded_identifiers,
    select_search_tool,
)


def trace() -> RetrievalTrace:
    metadata = [
        {
            "table_name": "silver_tag_property_value_enriched",
            "columns": [{"column_name": "tag_number"}, {"column_name": "numeric_value"}],
        }
    ]
    return RetrievalTrace(
        table_search=ToolCall("table", metadata, ("silver_tag_property_value_enriched",)),
        column_search=ToolCall("column", [], ("tag_number", "numeric_value")),
        graph_context=ToolCall("graph", {}, ()),
    )


class SemanticQueryTests(unittest.TestCase):
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
        require_grounded_identifiers(
            ("silver_tag_property_value_enriched", "catalog.ciphos.numeric_value"), trace()
        )
        with self.assertRaisesRegex(RuntimeError, "not returned"):
            require_grounded_identifiers(("invented_column",), trace())

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
