"""CIPHOS data explorer for the lakehouse, operational graph, and lineage.

The explorer is deliberately read-only. It brings the three-page investigation
shape used by the Finance Genie demo to CIPHOS, then ends with the architecture
and terminology that explain how the systems fit together.
"""

from __future__ import annotations

import streamlit as st

from ciphos_semantics.demo import (
    page_architecture,
    page_lakehouse,
    page_operational_graph,
    page_traceability,
)
from ciphos_semantics.demo.services import operational_graph_connection, warehouse_connection


def _badge(label: str, ok: bool) -> str:
    return f"{'🟢' if ok else '🔴'} {label}"


def _render_sidebar() -> tuple:
    warehouse = warehouse_connection()
    operational_graph = operational_graph_connection()

    st.sidebar.markdown(_badge("SQL warehouse", warehouse.ok))
    st.sidebar.markdown(_badge("Operational graph", operational_graph.ok))

    with st.sidebar.expander("Contract", expanded=False):
        page_architecture.render_contract_summary()

    with st.sidebar.expander("Active projection", expanded=False):
        page_architecture.render_projection_summary(operational_graph)

    with st.sidebar.expander("Connections", expanded=False):
        st.write(f"Catalog.schema: `{warehouse.catalog}.{warehouse.schema}`")
        st.write(f"Warehouse ID: `{warehouse.warehouse_id or '—'}`")
        st.write(
            f"Operational graph: `{operational_graph.host or '—'}` "
            f"/ `{operational_graph.database or '—'}`"
        )

    return warehouse, operational_graph


def main() -> None:
    st.set_page_config(page_title="CIPHOS data explorer", page_icon="🔗", layout="wide")
    warehouse, operational_graph = _render_sidebar()

    pages = st.navigation(
        {
            "DATA": [
                st.Page(lambda: page_lakehouse.render(warehouse), title="Lakehouse", default=True),
                st.Page(
                    lambda: page_operational_graph.render(operational_graph),
                    title="Operational graph",
                ),
            ],
            "BOTH SYSTEMS": [
                st.Page(
                    lambda: page_traceability.render(warehouse, operational_graph),
                    title="Traceability",
                )
            ],
            "REFERENCE": [st.Page(page_architecture.render, title="Architecture & glossary")],
        }
    )
    pages.run()


main()
