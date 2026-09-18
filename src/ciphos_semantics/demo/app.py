"""CIPHOS hybrid traceability demo.

Delta answers "what is the value and where did it come from". Neo4j answers
"what is this connected to". Each half renders on its own, so one unavailable
service degrades the answer instead of blanking the page.

Run:   uv run ciphos-demo
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from ciphos_semantics import contract, hybrid_data
from ciphos_semantics.demo import graph

st.set_page_config(page_title="CIPHOS hybrid traceability", page_icon="🔗", layout="wide")


@st.cache_resource(show_spinner="Connecting to Neo4j…")
def get_connection():
    return graph.connect()


@st.cache_resource(show_spinner="Connecting to Databricks SQL…")
def get_delta():
    return hybrid_data.get_delta_traceability()


def lakehouse_traceability(tag_number: str) -> hybrid_data.ServiceResult:
    """Call Delta lazily so a missing warehouse does not hide graph context."""
    try:
        return get_delta().property_traceability(tag_number)
    except Exception as exc:
        return hybrid_data.ServiceResult((), None, str(exc))


def snapshot_caption(name: str, result: hybrid_data.ServiceResult) -> None:
    if result.error:
        st.error(f"{name} unavailable: {result.error}")
    elif result.snapshot_id:
        st.caption(f"{name} snapshot: `{result.snapshot_id}`")
    else:
        st.warning(f"{name} returned no recorded snapshot identifier.")


def graph_context_frame(result: hybrid_data.ServiceResult) -> pd.DataFrame:
    """Flatten nested graph context enough for a readable Streamlit table."""
    return pd.DataFrame(
        [
            {
                "tag": row.get("tag_number"),
                "hierarchy": json.dumps(row.get("hierarchy", [])),
                "classification and applicable properties": json.dumps(
                    row.get("ontology", [])
                ),
                "OT and vulnerability context": json.dumps(row.get("ot_context", [])),
            }
            for row in result.rows
        ]
    )


def render_sidebar(driver, database: str) -> str | None:
    st.sidebar.header("Projection")
    projection = graph.active_projection(driver, database)
    if projection is None:
        st.sidebar.warning("No active CiphosProjection is recorded in this database.")
    else:
        st.sidebar.caption(f"graph snapshot: `{projection['graph_snapshot_id']}`")
        st.sidebar.caption(f"source snapshot: `{projection['source_snapshot_id']}`")
        st.sidebar.caption(
            f"materialized from: {projection.get('source_materialization') or 'unrecorded'}"
        )
        digest = projection.get("source_content_digest")
        if digest:
            st.sidebar.caption(f"content digest: `{digest[:16]}…`")
        st.sidebar.caption(
            f"{projection.get('node_count') or 0:,} nodes, "
            f"{projection.get('relationship_count') or 0:,} relationships"
        )
    st.sidebar.caption(f"contract: `{contract.contract_version()}`")

    st.sidebar.header("Tag")
    tags = graph.sample_tags(driver, database)
    if not tags:
        return st.sidebar.text_input("Tag number", value="")
    selected = st.sidebar.selectbox("Tag number", tags)
    typed = st.sidebar.text_input("…or enter another tag number", value="")
    return typed.strip() or selected


def render_comparison(
    lakehouse: hybrid_data.ServiceResult, graph_result: hybrid_data.ServiceResult
) -> None:
    if not (lakehouse.available and graph_result.available):
        return
    if not lakehouse.snapshot_id or not graph_result.source_snapshot_id:
        st.warning("Snapshot compatibility cannot be verified for this answer.")
    elif lakehouse.snapshot_id != graph_result.source_snapshot_id:
        st.error(
            "Snapshot mismatch: the displayed facts and the graph projection are not "
            "from the same recorded snapshot. Do not treat this as a fully "
            "consistent answer."
        )
    else:
        st.success("Lakehouse and graph results reference the same snapshot.")


def main() -> None:
    st.title("Hybrid asset traceability")
    st.caption(
        "Delta supplies typed property facts and provenance. Neo4j supplies "
        "connected hierarchy, classification, OT, and cyber context."
    )
    try:
        driver, database = get_connection()
    except Exception as exc:
        st.error(f"Neo4j is unavailable: {exc}")
        return

    tag_number = render_sidebar(driver, database)
    if not tag_number:
        st.info("Choose a tag number to compose a traceability answer.")
        return

    graph_result = hybrid_data.graph_traceability(driver, database, tag_number)
    lakehouse_result = lakehouse_traceability(tag_number)

    facts_column, context_column = st.columns(2)
    with facts_column:
        st.subheader("Lakehouse facts and provenance")
        snapshot_caption("Source", lakehouse_result)
        if lakehouse_result.available:
            values = pd.DataFrame(lakehouse_result.rows)
            if values.empty:
                st.info("No property facts were returned for this tag and snapshot.")
            else:
                st.dataframe(values, use_container_width=True, hide_index=True)

    with context_column:
        st.subheader("Graph context")
        snapshot_caption("Graph", graph_result)
        if graph_result.available:
            context = graph_context_frame(graph_result)
            if context.empty:
                st.info("No graph context was returned for this tag.")
            else:
                st.dataframe(context, use_container_width=True, hide_index=True)

    render_comparison(lakehouse_result, graph_result)

    with st.expander("Gold publication contract"):
        st.markdown(
            "Graph-derived exposure output has one row per **run, source entity, "
            "impacted entity, and path or score**. Path hops have one row per "
            "**run, path, and hop number**. A deterministic key makes a repeated "
            "publication for the same run ID idempotent."
        )
    with st.expander("Cypher behind the graph half"):
        st.code(hybrid_data.GRAPH_TRACEABILITY_CYPHER.strip(), language="cypher")


main()
