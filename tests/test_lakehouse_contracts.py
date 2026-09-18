"""Contract tests for the lakehouse SQL planner.

They intentionally do not require Databricks credentials: external writes are
only exercised by the CLI in an integration environment.
"""

from __future__ import annotations

import csv
import re
import tempfile
import unittest
from pathlib import Path

from ciphos_semantics import contract
from ciphos_semantics.build_lakehouse_tables import (
    SOURCE_ROW_COLUMN,
    build_plan,
    create_bronze_table_statement,
    default_batch_id,
    discover_source_tables,
    load_bronze_statement,
    quarantine_statement,
    remote_source_path,
    silver_statements,
    write_stamped_csv,
)

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "ciphos_data" / "csv"
CONTROL_TABLES = {"bronze_ingestion_control", "bronze_quarantine"}


def split_conform_cte(statement: str) -> tuple[str, str]:
    """Split a Bronze statement into its conform CTE and everything after it."""
    marker = "WITH conformed AS (\n"
    start = statement.index(marker) + len(marker)
    end = statement.index("\n)\n", start)
    return statement[start:end], statement[end:]


def unresolved_columns(statement: str, table) -> set[str]:
    """Return backticked references that are not in scope where they appear.

    Grepping generated SQL cannot catch a column that does not exist, so this
    resolves every reference instead. The conform CTE may use the CSV's own
    spelling; past it, only the conformed snake_case names are in scope, so a
    leaked source spelling shows up here as unresolved.
    """
    cte, body = split_conform_cte(statement)
    cte = re.sub(r"schema => '[^']*'", "", cte)
    objects = {"catalog", "schema", table.bronze_name} | CONTROL_TABLES
    conformed = {column.name for column in table.columns}
    source = {column.source_name for column in table.columns} | {SOURCE_ROW_COLUMN}
    in_cte = set(re.findall(r"`([^`]+)`", cte)) - conformed - source - objects
    in_body = set(re.findall(r"`([^`]+)`", body)) - conformed - objects
    return in_cte | in_body


class LakehouseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tables = discover_source_tables(DATA_DIR)
        cls.batch_id = default_batch_id(cls.tables)

    def test_discovers_complete_export_and_stable_batch(self) -> None:
        self.assertEqual(74, len(self.tables))
        self.assertEqual(27, sum(table.source_kind == "node" for table in self.tables))
        self.assertEqual(47, sum(table.source_kind == "relationship" for table in self.tables))
        self.assertEqual(
            default_batch_id(self.tables), default_batch_id(list(reversed(self.tables)))
        )

    def test_bronze_contract_preserves_raw_values_and_metadata(self) -> None:
        table = next(t for t in self.tables if t.source_file == "TagPropertyValue.csv")
        statement = create_bronze_table_statement("catalog", "schema", table)
        self.assertIn("`value` STRING", statement)
        self.assertIn("source_row_number BIGINT NOT NULL", statement)
        self.assertIn("source_checksum STRING", statement)
        self.assertIn("source_batch_id STRING", statement)

    def test_every_bronze_statement_only_references_real_source_columns(self) -> None:
        for table in self.tables:
            remote = remote_source_path("/Volumes/catalog/schema/volume", table)
            for statement in (
                quarantine_statement("catalog", "schema", remote, table, self.batch_id),
                load_bronze_statement("catalog", "schema", remote, table, self.batch_id),
            ):
                with self.subTest(source_file=table.source_file):
                    self.assertEqual(set(), unresolved_columns(statement, table))

    def test_the_header_is_conformed_once_then_only_snake_case_is_used(self) -> None:
        table = next(t for t in self.tables if t.source_file == "TagPropertyValue.csv")
        self.assertEqual(("tpv_id",), table.required_columns)
        remote = remote_source_path("/Volumes/catalog/schema/volume", table)
        statement = quarantine_statement("catalog", "schema", remote, table, self.batch_id)
        cte, body = split_conform_cte(statement)
        self.assertIn("`tpvId` AS `tpv_id`", cte)
        self.assertIn("trim(coalesce(`tpv_id`, '')) = ''", body)
        self.assertNotIn("tpvId", body)

    def test_multi_term_predicates_cannot_swallow_the_replay_guard(self) -> None:
        """AND binds tighter than OR, so the predicate must arrive parenthesized."""
        table = next(t for t in self.tables if t.source_kind == "relationship")
        remote = remote_source_path("/Volumes/catalog/schema/volume", table)
        quarantine = quarantine_statement("catalog", "schema", remote, table, self.batch_id)
        self.assertIn(
            "WHERE (trim(coalesce(`from`, '')) = '' OR trim(coalesce(`to`, '')) = '')\n"
            "  AND (SELECT count(*)",
            quarantine,
        )
        load = load_bronze_statement("catalog", "schema", remote, table, self.batch_id)
        self.assertIn(
            "WHERE NOT (trim(coalesce(`from`, '')) = '' OR trim(coalesce(`to`, '')) = '')\n"
            "  AND (SELECT count(*)",
            load,
        )

    def test_no_source_spelling_survives_the_conform_boundary(self) -> None:
        for table in self.tables:
            remote = remote_source_path("/Volumes/catalog/schema/volume", table)
            for statement in (
                quarantine_statement("catalog", "schema", remote, table, self.batch_id),
                load_bronze_statement("catalog", "schema", remote, table, self.batch_id),
            ):
                _, body = split_conform_cte(statement)
                leaked = sorted(
                    column.source_name
                    for column in table.columns
                    if column.source_name != column.name
                    and f"`{column.source_name}`" in body
                )
                with self.subTest(source_file=table.source_file):
                    self.assertEqual([], leaked)

    def test_every_bronze_column_records_its_original_header(self) -> None:
        table = next(t for t in self.tables if t.source_file == "TagPropertyValue.csv")
        statement = create_bronze_table_statement("catalog", "schema", table)
        self.assertIn("`tpv_id` STRING COMMENT 'tpvId'", statement)

    def test_source_row_number_comes_from_the_file_not_a_window(self) -> None:
        plan = "\n".join(
            build_plan("catalog", "schema", "volume", self.tables, self.batch_id)
        )
        self.assertNotIn("row_number() OVER", plan)
        self.assertIn(f"`{SOURCE_ROW_COLUMN}` AS source_row_number", plan)

    def test_stamped_upload_numbers_every_data_row_from_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "in.csv"
            target = Path(directory) / "out.csv"
            source.write_text('a,b\n1,"x,y"\n2,"line\nbreak"\n', encoding="utf-8")
            self.assertEqual(2, write_stamped_csv(source, target))
            with target.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
        self.assertEqual(["a", "b", SOURCE_ROW_COLUMN], rows[0])
        self.assertEqual([["1", "x,y", "1"], ["2", "line\nbreak", "2"]], rows[1:])

    def test_plan_has_quarantine_and_snapshot_contracts(self) -> None:
        plan = "\n".join(
            build_plan("catalog", "schema", "volume", self.tables, self.batch_id)
        )
        self.assertIn("bronze_quarantine", plan)
        self.assertIn("schema drift", plan.lower())
        statements = "\n".join(silver_statements("catalog", "schema", self.batch_id))
        self.assertIn("silver_tag_property_value_sources", statements)
        self.assertIn("silver_tag_property_value_enriched", statements)
        self.assertIn("silver_data_quality_results", statements)
        self.assertIn("silver_tag_property_value_snapshots", statements)

    def test_silver_snapshot_tables_are_append_only_with_explicit_ddl(self) -> None:
        statements = silver_statements("catalog", "schema", self.batch_id)
        for name in (
            "silver_tag_property_value_snapshots",
            "silver_tag_property_value_source_snapshots",
        ):
            prefix = f"CREATE TABLE IF NOT EXISTS `catalog`.`schema`.`{name}`"
            ddl = next(s for s in statements if s.startswith(prefix))
            self.assertIn("silver_snapshot_id STRING NOT NULL", ddl)
            self.assertNotIn("SELECT", ddl)
        joined = "\n".join(statements)
        self.assertNotIn("CREATE OR REPLACE TABLE", joined)

    def test_enriched_view_aggregates_provenance_instead_of_fanning_out(self) -> None:
        enriched = next(
            s
            for s in silver_statements("catalog", "schema", self.batch_id)
            if "silver_tag_property_value_enriched" in s and s.startswith("CREATE OR REPLACE VIEW")
        )
        self.assertIn("collect_set(s.document_number)", enriched)
        self.assertIn("GROUP BY s.tpv_id", enriched)
        self.assertIn("uom_symbol", enriched)
        self.assertEqual(1, enriched.count("u.uom_symbol"))

    def test_silver_emits_exactly_the_contract_quality_rules(self) -> None:
        statements = "\n".join(silver_statements("catalog", "schema", self.batch_id))
        for rule in contract.quality_rules():
            self.assertIn(f"'{rule}' AS rule_name", statements)
        self.assertEqual(
            len(contract.quality_rules()), statements.count(" AS rule_name")
        )


if __name__ == "__main__":
    unittest.main()
