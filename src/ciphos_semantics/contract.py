"""Load the frozen CIPHOS contract.

``contracts/ciphos-v1.json`` is the single source of truth for source
inventory, identity, snapshot semantics, the graph allowlist, and reconciliation
baselines. Nothing in this package may restate those facts: derive them here so
a contract change cannot silently disagree with the implementation.
"""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent.parent
DEFAULT_CONTRACT_PATH = PROJECT_DIR / "contracts" / "ciphos-v1.json"


def contract_path() -> Path:
    """Resolve the contract location, allowing an explicit override."""
    override = os.getenv("CIPHOS_CONTRACT_PATH", "").strip()
    return Path(override) if override else DEFAULT_CONTRACT_PATH


@cache
def _load(path: str) -> dict[str, Any]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Unable to read the CIPHOS contract {path}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError(f"The CIPHOS contract {path} must contain a JSON object.")
    return document


def load_contract(path: Path | None = None) -> dict[str, Any]:
    """Return the parsed contract document."""
    return _load(str(path or contract_path()))


def _section(document: dict[str, Any], *keys: str) -> Any:
    value: Any = document
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"The CIPHOS contract is missing {'.'.join(keys)}.")
        value = value[key]
    return value


def _string_tuple(document: dict[str, Any], *keys: str) -> tuple[str, ...]:
    value = _section(document, *keys)
    if not isinstance(value, list) or not value:
        raise ValueError(f"The CIPHOS contract needs a non-empty list at {'.'.join(keys)}.")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"The CIPHOS contract has a non-string entry at {'.'.join(keys)}.")
    if len(set(value)) != len(value):
        raise ValueError(f"The CIPHOS contract has duplicates at {'.'.join(keys)}.")
    return tuple(value)


def contract_version(document: dict[str, Any] | None = None) -> str:
    return str(_section(document or load_contract(), "contract_version"))


def source_nodes(document: dict[str, Any] | None = None) -> tuple[str, ...]:
    return _string_tuple(document or load_contract(), "bronze", "source_nodes")


def source_relationships(document: dict[str, Any] | None = None) -> tuple[str, ...]:
    return _string_tuple(document or load_contract(), "bronze", "source_relationships")


def excluded_nodes(document: dict[str, Any] | None = None) -> tuple[str, ...]:
    return _string_tuple(document or load_contract(), "graph_projection", "excluded_nodes")


def excluded_relationships(document: dict[str, Any] | None = None) -> tuple[str, ...]:
    return _string_tuple(
        document or load_contract(), "graph_projection", "excluded_relationships"
    )


def projected_nodes(document: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Derive the node allowlist so it can never drift from the source inventory."""
    document = document or load_contract()
    excluded = set(excluded_nodes(document))
    unknown = excluded - set(source_nodes(document))
    if unknown:
        raise ValueError(f"Excluded nodes are not source nodes: {sorted(unknown)}")
    return tuple(name for name in source_nodes(document) if name not in excluded)


def projected_relationships(document: dict[str, Any] | None = None) -> tuple[str, ...]:
    document = document or load_contract()
    excluded = set(excluded_relationships(document))
    unknown = excluded - set(source_relationships(document))
    if unknown:
        raise ValueError(f"Excluded relationships are not source relationships: {sorted(unknown)}")
    return tuple(name for name in source_relationships(document) if name not in excluded)


def quality_rules(document: dict[str, Any] | None = None) -> tuple[str, ...]:
    return _string_tuple(document or load_contract(), "silver", "quality_rules")


def tag_property_value_columns(document: dict[str, Any] | None = None) -> tuple[str, ...]:
    return _string_tuple(
        document or load_contract(), "silver", "tag_property_value_columns"
    )


def baseline(document: dict[str, Any] | None = None) -> dict[str, int]:
    values = _section(document or load_contract(), "baseline")
    if not isinstance(values, dict) or not all(
        isinstance(count, int) for count in values.values()
    ):
        raise ValueError("The CIPHOS contract baseline must map names to integers.")
    return dict(values)


def projection_settings(document: dict[str, Any] | None = None) -> dict[str, str]:
    """Return the manifest version, name, and required source layer."""
    projection = _section(document or load_contract(), "graph_projection")
    return {
        key: str(projection[key])
        for key in ("manifest_version", "projection_name", "source_layer")
        if key in projection
    }
