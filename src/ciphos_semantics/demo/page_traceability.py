"""The existing hybrid traceability experience as one explorer page."""

from __future__ import annotations

import json
import os

import pandas as pd
import streamlit as st

from ciphos_semantics import hybrid_data
from ciphos_semantics.demo import graph
from ciphos_semantics.demo.services import GraphConnection, WarehouseConnection


def _lakehouse_traceability(
    warehouse: WarehouseConnection, tag_number: str
) -> hybrid_data.ServiceResult:
    if not warehouse.ok or warehouse.workspace is None:
        return hybrid_data.ServiceResult(
            (), None, warehouse.error or "SQL warehouse is unavailable."
        )
    property_view = os.getenv(
        "CIPHOS_SILVER_PROPERTY_VIEW",
        f"{warehouse.catalog}.{warehouse.schema}.silver_tag_property_value_enriched",
    )
    adapter = hybrid_data.DeltaTraceability(
        warehouse.workspace.statement_execution, warehouse.warehouse_id, property_view
    )
    return adapter.property_traceability(tag_number)


def _snapshot_caption(name: str, result: hybrid_data.ServiceResult) -> None:
    if result.error:
        st.error(f"{name} unavailable: {result.error}")
    elif result.snapshot_id:
        st.caption(f"{name} snapshot: `{result.snapshot_id}`")
    else:
        st.warning(f"{name} returned no recorded snapshot identifier.")


def _graph_context_frame(result: hybrid_data.ServiceResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "tag": row.get("tag_number"),
                "hierarchy": json.dumps(row.get("hierarchy", [])),
                "classification and applicable properties": json.dumps(row.get("ontology", [])),
                "OT and vulnerability context": json.dumps(row.get("ot_context", [])),
            }
            for row in result.rows
        ]
    )


def _render_comparison(
    lakehouse: hybrid_data.ServiceResult, graph_result: hybrid_data.ServiceResult
) -> None:
    if not (lakehouse.available and graph_result.available):
        return
    if not lakehouse.snapshot_id or not graph_result.source_snapshot_id:
        st.warning("Snapshot compatibility cannot be verified for this answer.")
    elif lakehouse.snapshot_id != graph_result.source_snapshot_id:
        st.error(
            "Snapshot mismatch: the facts and graph projection are not from the same snapshot."
        )
    else:
        st.success("Lakehouse and graph results reference the same source snapshot.")


def render(warehouse: WarehouseConnection, operational_graph: GraphConnection) -> None:
    st.title("Traceability")
    st.caption(
        "Databricks supplies typed property facts and provenance. Neo4j supplies connected "
        "hierarchy, classification, OT, and cyber context."
    )
    if not operational_graph.ok or operational_graph.driver is None:
        st.error(f"Neo4j is unavailable: {operational_graph.error}")
        return

    try:
        tags = graph.sample_tags(operational_graph.driver, operational_graph.database)
    except Exception as error:
        st.error(f"Could not list tags: {error}")
        return
    tag_number = st.text_input("Tag number") if not tags else st.selectbox("Tag number", tags)
    if not tag_number:
        st.info("Choose a tag number to compose a traceability answer.")
        return

    graph_result = hybrid_data.graph_traceability(
        operational_graph.driver, operational_graph.database, tag_number
    )
    lakehouse_result = _lakehouse_traceability(warehouse, tag_number)

    facts_column, context_column = st.columns(2)
    with facts_column:
        st.subheader("LAKEHOUSE FACTS AND PROVENANCE")
        _snapshot_caption("Source", lakehouse_result)
        if lakehouse_result.available:
            values = pd.DataFrame(lakehouse_result.rows)
            if values.empty:
                st.info("No property facts were returned for this tag and snapshot.")
            else:
                st.dataframe(values, use_container_width=True, hide_index=True)
    with context_column:
        st.subheader("GRAPH CONTEXT")
        _snapshot_caption("Graph", graph_result)
        if graph_result.available:
            context = _graph_context_frame(graph_result)
            if context.empty:
                st.info("No graph context was returned for this tag.")
            else:
                st.dataframe(context, use_container_width=True, hide_index=True)

    _render_comparison(lakehouse_result, graph_result)
    with st.expander("Cypher behind the graph context"):
        st.code(hybrid_data.GRAPH_TRACEABILITY_CYPHER.strip(), language="cypher")
