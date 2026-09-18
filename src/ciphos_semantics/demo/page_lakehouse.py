"""Lakehouse page for browsing the CIPHOS Bronze and Silver data products."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ciphos_semantics import contract
from ciphos_semantics.build_lakehouse_tables import snake_case
from ciphos_semantics.demo.services import WarehouseConnection, qualified_table, query_rows

SILVER_TABLES = (
    "silver_snapshots",
    "silver_tag_property_value_snapshots",
    "silver_tag_property_value_source_snapshots",
    "silver_data_quality_results",
    "silver_tag_property_value",
    "silver_tag_property_value_sources",
    "silver_tag_property_value_enriched",
)


def bronze_tables() -> tuple[str, ...]:
    """Derive the complete Bronze surface from the frozen source inventory."""
    nodes = tuple(f"bronze_node_{snake_case(name)}" for name in contract.source_nodes())
    relationships = tuple(
        f"bronze_relationship_{snake_case(name)}" for name in contract.source_relationships()
    )
    return (*nodes, *relationships, "bronze_ingestion_control", "bronze_quarantine")


def render(warehouse: WarehouseConnection) -> None:
    st.title("Lakehouse")
    st.caption("Browse the complete raw source in Bronze or curated, typed CIPHOS data in Silver.")

    if not warehouse.ok or warehouse.workspace is None:
        st.error(f"SQL warehouse unavailable: {warehouse.error}")
        return

    st.caption(f"{warehouse.catalog}.{warehouse.schema} · SQL warehouse")
    layer = st.segmented_control("Layer", ("Bronze", "Silver"), default="Silver")
    tables = bronze_tables() if layer == "Bronze" else SILVER_TABLES
    selected_table = st.selectbox("Table or view", tables)

    st.subheader("THE DATA")
    st.caption("10 sample rows · table names are fixed by the CIPHOS contract, never free text.")
    try:
        table = qualified_table(warehouse.catalog, warehouse.schema, selected_table)
        rows = query_rows(
            warehouse.workspace,
            warehouse.warehouse_id,
            f"SELECT * FROM {table} LIMIT 10",
        )
    except Exception as error:
        st.error(f"Query failed: {error}")
        return

    frame = pd.DataFrame(rows)
    if frame.empty:
        st.info("This table or view exists but has no rows to display.")
    else:
        st.dataframe(frame, use_container_width=True, hide_index=True)

    if layer == "Silver":
        st.info(
            "Silver preserves published snapshots, typed tag-property facts, provenance, and "
            "data-quality results. The enriched view aggregates source documents so values do "
            "not fan out."
        )
