"""Focused unit tests for hybrid-data and Gold contract helpers."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

from ciphos_semantics.gold_contract import (
    GoldExposureRow,
    GoldGraphRun,
    GoldPathHop,
    stable_key,
    unique_hops,
    unique_rows,
)
from ciphos_semantics.hybrid_data import (
    DeltaTraceability,
    _statement_rows,
    graph_traceability,
)


class FakeStatementExecution:
    def execute_statement(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            status=SimpleNamespace(state="SUCCEEDED"),
            manifest=SimpleNamespace(
                schema=SimpleNamespace(columns=[SimpleNamespace(name="tag_number")])
            ),
            result=SimpleNamespace(data_array=[["TT-1"]]),
        )


class HybridDataTests(unittest.TestCase):
    def test_statement_rows_reject_failed_query(self) -> None:
        response = SimpleNamespace(
            status=SimpleNamespace(state="FAILED", error="missing table")
        )
        with self.assertRaisesRegex(RuntimeError, "missing table"):
            _statement_rows(response)

    def test_traceability_binds_the_tag_parameter(self) -> None:
        fake = FakeStatementExecution()
        adapter = DeltaTraceability(fake, "warehouse-id", "catalog.schema.values")
        result = adapter.property_traceability("TT-1")
        self.assertTrue(result.available)
        self.assertEqual(result.rows[0]["tag_number"], "TT-1")
        parameter = fake.kwargs["parameters"][0]
        self.assertEqual((parameter.name, parameter.value), ("tag_number", "TT-1"))

    def test_traceability_reads_the_aggregated_view_without_a_provenance_join(self) -> None:
        fake = FakeStatementExecution()
        adapter = DeltaTraceability(fake, "warehouse-id", "catalog.schema.values")
        adapter.property_traceability("TT-1")
        statement = fake.kwargs["statement"]
        self.assertNotIn("JOIN", statement.upper())
        self.assertIn("source_document_numbers", statement)
        self.assertIn("silver_snapshot_id", statement)

    def test_view_identifier_must_be_three_parts(self) -> None:
        with self.assertRaisesRegex(ValueError, "catalog.schema.view"):
            DeltaTraceability(FakeStatementExecution(), "warehouse-id", "schema.values")

    def test_graph_traceability_reads_the_active_projection_snapshot(self) -> None:
        class FakeDriver:
            def execute_query(self, query, **kwargs):
                self.query = query
                self.kwargs = kwargs
                return SimpleNamespace(
                    records=[
                        SimpleNamespace(
                            data=lambda: {
                                "tag_number": "TT-1",
                                "graph_snapshot_id": "graph-1",
                                "source_snapshot_id": "silver-1",
                            }
                        )
                    ]
                )

        fake = FakeDriver()
        result = graph_traceability(fake, "neo4j", "TT-1")
        self.assertEqual(result.snapshot_id, "graph-1")
        self.assertEqual(result.source_snapshot_id, "silver-1")
        self.assertIn("CiphosProjection", fake.query)
        self.assertNotIn("CALL {", fake.query)
        self.assertEqual(fake.kwargs["tag_number"], "TT-1")


class GoldContractTests(unittest.TestCase):
    def test_run_contract_has_compatible_snapshot_fields(self) -> None:
        run = GoldGraphRun(
            "run-1",
            "silver-1",
            "graph-1",
            "reachable_critical_assets",
            "v1",
            datetime.now(UTC),
        )
        self.assertEqual(run.source_snapshot_id, "silver-1")
        self.assertEqual(run.graph_snapshot_id, "graph-1")

    def test_exposure_rows_are_idempotent_at_the_documented_grain(self) -> None:
        row = GoldExposureRow("run-1", "tag-1", "asset-2", "path-3", 7.5)
        self.assertEqual(unique_rows([row, row]), [row])
        self.assertEqual(
            row.idempotency_key, stable_key("run-1", "tag-1", "asset-2", "path-3")
        )

    def test_path_hops_share_the_exposure_idempotency_rule(self) -> None:
        hop = GoldPathHop("run-1", "path-3", 1, "tag-1", "CONNECTED_TO", "asset-2")
        self.assertEqual(unique_hops([hop, hop]), [hop])
        conflicting = GoldPathHop("run-1", "path-3", 1, "tag-1", "LOCATED_AT", "asset-9")
        with self.assertRaisesRegex(ValueError, "Conflicting Gold rows"):
            unique_hops([hop, conflicting])


if __name__ == "__main__":
    unittest.main()
