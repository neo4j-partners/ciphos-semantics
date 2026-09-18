"""Small, offline checks for the Streamlit explorer's contract-derived helpers."""

from __future__ import annotations

import unittest

from ciphos_semantics import contract
from ciphos_semantics.demo.page_lakehouse import bronze_tables
from ciphos_semantics.demo.page_operational_graph import _relationship_pattern
from ciphos_semantics.demo.services import qualified_table


class DemoPageTests(unittest.TestCase):
    def test_bronze_selector_is_derived_from_the_frozen_source_inventory(self) -> None:
        tables = bronze_tables()

        self.assertEqual(
            len(tables), len(contract.source_nodes()) + len(contract.source_relationships()) + 2
        )
        self.assertIn("bronze_node_tag", tables)
        self.assertIn("bronze_relationship_contains_tag", tables)
        self.assertIn("bronze_ingestion_control", tables)

    def test_table_identifier_rejects_untrusted_config_values(self) -> None:
        self.assertEqual(
            qualified_table("catalog", "ciphos-semantics", "silver_tag_property_value"),
            "`catalog`.`ciphos-semantics`.`silver_tag_property_value`",
        )
        with self.assertRaisesRegex(ValueError, "Invalid Unity Catalog identifier"):
            qualified_table("catalog; DROP SCHEMA", "schema", "table")

    def test_relationship_filter_comes_from_selected_contract_types(self) -> None:
        self.assertEqual(_relationship_pattern((), 2), "[*0..2]")
        self.assertEqual(
            _relationship_pattern(("CONTAINS_TAG", "CLASSIFIED_AS"), 1),
            "[:`CONTAINS_TAG`|`CLASSIFIED_AS`*0..1]",
        )


if __name__ == "__main__":
    unittest.main()
