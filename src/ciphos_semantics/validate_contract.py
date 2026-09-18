"""Validate the local CIPHOS source inventory against the frozen v1 contract."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections.abc import Sequence
from pathlib import Path

from ciphos_semantics import contract

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = PROJECT_DIR / "ciphos_data" / "csv"


def count_data_rows(path: Path) -> int:
    """Count CSV records without making assumptions about line endings."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def source_files(data_dir: Path, names: Sequence[str], directory: str) -> list[Path]:
    """Return the exact contract-listed files, failing on inventory drift."""
    expected = {f"{name}.csv" for name in names}
    actual = {path.name for path in (data_dir / directory).glob("*.csv")}
    if expected != actual:
        raise ValueError(
            f"{directory} inventory drift: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )
    return [data_dir / directory / name for name in sorted(expected)]


def validate(data_dir: Path, document: dict | None = None) -> dict[str, int | str]:
    """Validate files, baseline counts, and the graph-projection delta."""
    document = document or contract.load_contract()
    node_files = source_files(data_dir, contract.source_nodes(document), "nodes")
    relationship_files = source_files(
        data_dir, contract.source_relationships(document), "rels"
    )
    nodes = sum(count_data_rows(path) for path in node_files)
    relationships = sum(count_data_rows(path) for path in relationship_files)
    baseline = contract.baseline(document)
    for name, actual in (("node_count", nodes), ("relationship_count", relationships)):
        if actual != baseline[name]:
            raise ValueError(f"{name}: expected {baseline[name]:,}, found {actual:,}")

    removed_nodes = sum(
        count_data_rows(data_dir / "nodes" / f"{name}.csv")
        for name in contract.excluded_nodes(document)
    )
    removed_relationships = sum(
        count_data_rows(data_dir / "rels" / f"{name}.csv")
        for name in contract.excluded_relationships(document)
    )
    projected_nodes = nodes - removed_nodes
    projected_relationships = relationships - removed_relationships
    for name, actual in (
        ("projected_node_count", projected_nodes),
        ("projected_relationship_count", projected_relationships),
    ):
        if actual != baseline[name]:
            raise ValueError(f"{name}: expected {baseline[name]:,}, found {actual:,}")
    return {
        "contract_version": contract.contract_version(document),
        "nodes": nodes,
        "relationships": relationships,
        "projected_nodes": projected_nodes,
        "projected_relationships": projected_relationships,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.getenv("CIPHOS_DATA_DIR", DEFAULT_DATA_DIR)),
        help="Directory containing nodes/ and rels/ (default: CIPHOS_DATA_DIR).",
    )
    parser.add_argument(
        "--contract", type=Path, default=None, help="Contract JSON to validate against."
    )
    parser.add_argument("--json", action="store_true", help="Print a JSON report.")
    args = parser.parse_args(argv)

    report = validate(args.data_dir, contract.load_contract(args.contract))
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(
            f"Split contract {report['contract_version']} passed: "
            f"{report['nodes']:,} source nodes, {report['relationships']:,} source "
            f"relationships; {report['projected_nodes']:,} projected nodes, "
            f"{report['projected_relationships']:,} projected relationships."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
