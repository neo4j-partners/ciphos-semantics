"""Tests for source-attributed CIPHOS SQL and Cypher generation."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ciphos_semantics import query_generation
from ciphos_semantics.mcp_retrieval import RetrievalTrace, ToolCall


def retrieval_trace() -> RetrievalTrace:
    """Build a compact CIPHOS retrieval trace for generation tests."""
    return RetrievalTrace(
        table_search=ToolCall(
            "get_context_by_table_hybrid_search",
            {},
            [{"table_name": "silver_tag_property_value_enriched", "columns": []}],
            ("silver_tag_property_value_enriched",),
        ),
        column_search=ToolCall(
            "get_context_by_column_hybrid_search",
            {},
            [
                {
                    "table_name": "silver_tag_property_value_enriched",
                    "columns": [{"column_name": "tag_number"}],
                }
            ],
            ("tag_number",),
        ),
        graph_context=ToolCall(
            "get_ciphos_lpg_schema_context",
            {},
            {"records": [{"kind": "Node", "label": "Tag"}]},
            ("Tag",),
        ),
    )


class QueryGenerationTests(unittest.TestCase):
    def test_generate_queries_uses_source_attributed_response_schema(self) -> None:
        payload = {
            "sql": (
                "SELECT tag_number FROM "
                "`catalog`.`ciphos`.`silver_tag_property_value_enriched` LIMIT 10"
            ),
            "cypher": "MATCH (tag:Tag) RETURN tag.tagNumber LIMIT 10",
            "identifiers": [
                {"name": "silver_tag_property_value_enriched", "source_tool": "table_search"},
                {"name": "tag_number", "source_tool": "column_search"},
                {"name": "Tag", "source_tool": "graph_context"},
            ],
        }
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: completion))
        )

        with patch.object(query_generation, "_client", return_value=client):
            generated = query_generation.generate_queries(
                "Which tags have high pressure readings?",
                retrieval_trace(),
                catalog="catalog",
                schema="ciphos",
                model="databricks-claude-sonnet-5",
            )

        self.assertEqual(generated.sql, payload["sql"])
        self.assertEqual(generated.cypher, payload["cypher"])
        self.assertEqual(
            generated.identifiers,
            (
                ("silver_tag_property_value_enriched", "table_search"),
                ("tag_number", "column_search"),
                ("Tag", "graph_context"),
            ),
        )

    def test_generated_queries_reject_missing_identifier_provenance(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "required `identifiers` list"):
            query_generation._parse_generated_queries(
                json.dumps({"sql": "SELECT 1", "cypher": "RETURN 1"})
            )


if __name__ == "__main__":
    unittest.main()
