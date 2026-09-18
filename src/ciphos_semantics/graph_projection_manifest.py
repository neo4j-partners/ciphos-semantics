"""The bundled, versioned contract for the CIPHOS current-state graph.

The allowlists are derived from ``contracts/ciphos-v1.json`` rather than
restated, so the manifest and the contract cannot disagree. An external
manifest passed to the importer is still validated against the same rules.
"""

from __future__ import annotations

from typing import Any

from ciphos_semantics import contract


def build_default_manifest(document: dict[str, Any] | None = None) -> dict[str, Any]:
    """Materialize the bundled manifest from the frozen contract."""
    document = document or contract.load_contract()
    settings = contract.projection_settings(document)
    return {
        "manifest_version": settings["manifest_version"],
        "projection_name": settings["projection_name"],
        "source_layer": settings["source_layer"],
        "nodes": {
            "include": list(contract.projected_nodes(document)),
            "exclude": list(contract.excluded_nodes(document)),
        },
        "relationships": {
            "include": list(contract.projected_relationships(document)),
            "exclude": list(contract.excluded_relationships(document)),
        },
    }
