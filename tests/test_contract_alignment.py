"""The frozen contract is the only place the projection allowlists are written."""

from __future__ import annotations

import unittest

from ciphos_semantics import contract
from ciphos_semantics.graph_projection_manifest import build_default_manifest
from ciphos_semantics.import_ciphos_graph import (
    EXCLUDED_NODE_TYPES,
    EXCLUDED_RELATIONSHIP_TYPES,
    load_projection_manifest,
)


class ContractAlignmentTests(unittest.TestCase):
    def test_bundled_manifest_is_derived_from_the_contract(self) -> None:
        manifest = build_default_manifest()
        settings = contract.projection_settings()
        self.assertEqual(settings["manifest_version"], manifest["manifest_version"])
        self.assertEqual(settings["projection_name"], manifest["projection_name"])
        self.assertEqual(settings["source_layer"], manifest["source_layer"])
        self.assertEqual(list(contract.projected_nodes()), manifest["nodes"]["include"])
        self.assertEqual(list(contract.excluded_nodes()), manifest["nodes"]["exclude"])
        self.assertEqual(
            list(contract.projected_relationships()), manifest["relationships"]["include"]
        )
        self.assertEqual(
            list(contract.excluded_relationships()), manifest["relationships"]["exclude"]
        )

    def test_bundled_manifest_passes_its_own_loader(self) -> None:
        manifest = load_projection_manifest()
        self.assertEqual(manifest.node_types, frozenset(contract.projected_nodes()))
        self.assertEqual(
            manifest.relationship_types, frozenset(contract.projected_relationships())
        )
        self.assertEqual("silver", manifest.source_layer)

    def test_importer_exclusions_come_from_the_contract(self) -> None:
        self.assertEqual(EXCLUDED_NODE_TYPES, frozenset(contract.excluded_nodes()))
        self.assertEqual(
            EXCLUDED_RELATIONSHIP_TYPES, frozenset(contract.excluded_relationships())
        )

    def test_projected_sets_are_the_source_inventory_minus_exclusions(self) -> None:
        self.assertEqual(
            set(contract.source_nodes()) - set(contract.excluded_nodes()),
            set(contract.projected_nodes()),
        )
        self.assertEqual(
            set(contract.source_relationships()) - set(contract.excluded_relationships()),
            set(contract.projected_relationships()),
        )
        self.assertEqual(27, len(contract.source_nodes()))
        self.assertEqual(47, len(contract.source_relationships()))


if __name__ == "__main__":
    unittest.main()
