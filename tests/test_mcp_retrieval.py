"""Tests for the CIPHOS MCP retrieval boundary."""

from __future__ import annotations

import unittest

from ciphos_semantics.mcp_retrieval import (
    RetrievalTrace,
    ToolCall,
    _graph_context_names,
    mcp_startup_instructions,
)


class McpRetrievalTests(unittest.TestCase):
    def test_retrieved_names_include_catalog_and_graph_context_identifiers(self) -> None:
        trace = RetrievalTrace(
            table_search=ToolCall(
                "get_context_by_table_hybrid_search",
                {},
                [
                    {
                        "table_name": "silver_tag_property_value_enriched",
                        "columns": [{"column_name": "tag_number"}],
                    }
                ],
                ("silver_tag_property_value_enriched",),
            ),
            column_search=ToolCall(
                "get_context_by_column_hybrid_search",
                {},
                [],
                (),
            ),
            graph_context=ToolCall(
                "get_ciphos_lpg_schema_context",
                {},
                {},
                ("Tag", "tagNumber"),
            ),
        )

        self.assertEqual(
            trace.retrieved_names(),
            {"silver_tag_property_value_enriched", "tag_number", "Tag", "tagNumber"},
        )

    def test_graph_context_names_include_labels_relationships_and_properties(self) -> None:
        names = _graph_context_names(
            {
                "records": [
                    {"kind": "Node", "label": "Tag", "additional_labels": ["CiphosEntity"]},
                    {"kind": "Relationship", "type": "REFERENCED_IN"},
                    {"kind": "Property", "name": "tagNumber"},
                ]
            }
        )

        self.assertEqual(names, ("CiphosEntity", "REFERENCED_IN", "Tag", "tagNumber"))

    def test_mcp_startup_instructions_name_the_persistent_server_command(self) -> None:
        message = mcp_startup_instructions("http://127.0.0.1:8010/mcp")

        self.assertIn("CIPHOS semantic MCP is unavailable", message)
        self.assertIn("make semantic-search-mcp", message)
        self.assertIn("separate terminal", message)


if __name__ == "__main__":
    unittest.main()
