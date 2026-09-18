"""Architecture and terminology reference for the CIPHOS explorer."""

from __future__ import annotations

import streamlit as st

from ciphos_semantics import contract
from ciphos_semantics.demo import graph
from ciphos_semantics.demo.services import GraphConnection


def render_contract_summary() -> None:
    """Render the frozen allowlist and exclusions shared by all explorer pages."""
    st.caption(f"Version: `{contract.contract_version()}`")
    st.write(
        f"{len(contract.projected_nodes())} projected node labels · "
        f"{len(contract.projected_relationships())} projected relationship types"
    )
    st.caption(f"Excluded nodes: {', '.join(contract.excluded_nodes())}")
    st.caption(f"Excluded relationships: {', '.join(contract.excluded_relationships())}")


def render_projection_summary(operational_graph: GraphConnection) -> None:
    """Render projection lineage without making the rest of the UI depend on it."""
    if not operational_graph.ok or operational_graph.driver is None:
        st.caption("Unavailable until the operational graph connection succeeds.")
        return
    try:
        projection = graph.active_projection(operational_graph.driver, operational_graph.database)
    except Exception as error:
        st.caption(f"Could not read projection lineage: {error}")
        return
    if projection is None:
        st.caption("No recorded CIPHOS projection was found in this database.")
        return
    st.caption(f"Graph snapshot: `{projection['graph_snapshot_id']}`")
    st.caption(f"Source snapshot: `{projection['source_snapshot_id']}`")
    st.caption(f"Materialization: {projection.get('source_materialization') or 'unrecorded'}")
    st.caption(
        f"{projection.get('node_count') or 0:,} nodes · "
        f"{projection.get('relationship_count') or 0:,} relationships"
    )


def render() -> None:
    st.title("CIPHOS data architecture & glossary")
    st.caption(
        "The CIPHOS lakehouse is the system of record; Neo4j is a rebuildable serving projection."
    )

    st.graphviz_chart(
        """
digraph ciphos {
  rankdir=LR;
  node [shape=box, style="rounded,filled", fillcolor="#f4f7fb", color="#4b6a88"];
  source [label="CIPHOS CSV exports"];
  bronze [label="Bronze Delta\\ncomplete raw history"];
  silver [label="Silver Delta\\ntyped facts, provenance, quality"];
  graph [label="Neo4j operational graph\\ncurrent-state connections"];
  gold [label="Gold Delta\\ngraph results for analytics"];
  semantic [label="NeoCarta semantic store\\nstructure and metadata only"];
  source -> bronze -> silver;
  silver -> graph [label="versioned projection"];
  silver -> gold [label="governed facts"];
  graph -> gold [label="paths and exposure"];
  graph -> semantic [label="schema extraction"];
  silver -> semantic [label="table metadata index"];
}
"""
    )
    st.markdown(
        "The explorer reads the first four layers: Lakehouse shows Bronze and Silver, "
        "Operational graph shows the Neo4j projection, and Traceability brings a tag's "
        "Silver facts together with its graph context."
    )

    st.subheader("Glossary")
    st.table(
        [
            {
                "Term": "CIPHOS",
                "Meaning": (
                    "This project's industrial asset, operational technology, and "
                    "cybersecurity data domain. The repository does not define an "
                    "expansion of the name."
                ),
            },
            {
                "Term": "Bronze",
                "Meaning": (
                    "The complete raw CSV history in Delta, with source-file, row, "
                    "checksum, batch, and ingestion metadata."
                ),
            },
            {
                "Term": "Silver",
                "Meaning": (
                    "Typed, validated, published Delta data for traceability, "
                    "provenance, and analytical queries."
                ),
            },
            {
                "Term": "Gold",
                "Meaning": (
                    "Versioned, row-oriented outputs from graph calculations for "
                    "reporting, BI, and analytics."
                ),
            },
            {
                "Term": "Projection",
                "Meaning": (
                    "The versioned current-state graph built from one published Silver "
                    "snapshot and an allowlisted manifest."
                ),
            },
            {
                "Term": "Snapshot",
                "Meaning": (
                    "An immutable recorded version of source or graph data, used to "
                    "prove cross-system consistency."
                ),
            },
            {
                "Term": "Traceability",
                "Meaning": (
                    "A combined answer: Delta explains a value and its provenance; "
                    "Neo4j explains related hierarchy, OT, and cyber context."
                ),
            },
            {
                "Term": "NeoCarta semantic store",
                "Meaning": (
                    "A separate Neo4j database containing source structure and "
                    "searchable metadata, never operational graph values."
                ),
            },
            {
                "Term": "OT asset",
                "Meaning": (
                    "The cyber-physical representation of a Tag, including details "
                    "such as IP, firmware, vendor, and Purdue level."
                ),
            },
        ]
    )
