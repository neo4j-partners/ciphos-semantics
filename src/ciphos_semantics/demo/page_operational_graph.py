"""Operational graph page for bounded CIPHOS relationship exploration."""

from __future__ import annotations

from collections.abc import Iterable

import streamlit as st
from neo4j import Driver, RoutingControl
from neo4j_viz import ColorSpace
from neo4j_viz.neo4j import from_neo4j
from neo4j_viz.streamlit import display_widget

from ciphos_semantics import contract
from ciphos_semantics.demo.services import GraphConnection

NODE_BUDGET = 150
DEPTH_OPTIONS = (1, 2, 3)


def _cypher_identifier(value: str) -> str:
    """Quote a label/type drawn exclusively from the checked-in contract."""
    return f"`{value.replace('`', '``')}`"


@st.cache_data(show_spinner=False)
def list_instances(_driver: Driver, database: str, label: str) -> list[dict[str, str]]:
    """Return a bounded, human-readable list of graph entities for one label."""
    query = f"""
MATCH (node:CiphosEntity:{_cypher_identifier(label)})
WHERE node.externalId IS NOT NULL
RETURN node.externalId AS external_id,
       coalesce(node.tagNumber, node.documentNumber, node.cveId, node.otAssetId,
                node.name, node.externalId) AS display
ORDER BY display, external_id
LIMIT 200
"""
    records, _, _ = _driver.execute_query(query, database_=database, routing_=RoutingControl.READ)
    return [
        {"external_id": str(record["external_id"]), "display": str(record["display"])}
        for record in records
    ]


def _relationship_pattern(selected_types: Iterable[str], depth: int) -> str:
    selected = tuple(selected_types)
    if not selected:
        return f"[*0..{depth}]"
    types = "|".join(_cypher_identifier(value) for value in selected)
    return f"[:{types}*0..{depth}]"


@st.cache_data(show_spinner=False)
def reachable_node_count(
    _driver: Driver,
    database: str,
    label: str,
    external_id: str,
    selected_types: tuple[str, ...],
    depth: int,
) -> int:
    """Count the full reachable set so the graph cap is always visible."""
    pattern = _relationship_pattern(selected_types, depth)
    query = (
        f"MATCH (root:CiphosEntity:{_cypher_identifier(label)} {{externalId: $external_id}})"
        f"-{pattern}-(other:CiphosEntity) RETURN count(DISTINCT other) AS node_count"
    )
    records, _, _ = _driver.execute_query(
        query,
        external_id=external_id,
        database_=database,
        routing_=RoutingControl.READ,
    )
    return int(records[0]["node_count"]) if records else 0


def bounded_subgraph(
    driver: Driver,
    database: str,
    label: str,
    external_id: str,
    selected_types: tuple[str, ...],
    depth: int,
):
    """Fetch a read-only, node-budget-capped graph rooted at the selected entity."""
    pattern = _relationship_pattern(selected_types, depth)
    query = f"""
MATCH (root:CiphosEntity:{_cypher_identifier(label)} {{externalId: $external_id}})
CALL {{
  WITH root
  MATCH (root)-{pattern}-(other:CiphosEntity)
  RETURN DISTINCT other
  ORDER BY elementId(other)
  LIMIT $node_limit
}}
WITH collect(DISTINCT other) + [root] AS kept
UNWIND kept AS node
OPTIONAL MATCH (node)-[relationship]-(other)
WHERE other IN kept
RETURN DISTINCT node, relationship, other
"""
    return driver.execute_query(
        query,
        external_id=external_id,
        node_limit=NODE_BUDGET,
        database_=database,
        routing_=RoutingControl.READ,
    )


def render_subgraph(result) -> int:
    """Render the returned graph with a categorical caption fallback."""
    visual_graph = from_neo4j(result)
    if not visual_graph.nodes:
        return 0
    if any("riskScore" in node.properties for node in visual_graph.nodes):
        visual_graph.color_nodes(property="riskScore", color_space=ColorSpace.CONTINUOUS)
    else:
        visual_graph.color_nodes(field="caption")
    display_widget(
        visual_graph.render_widget(height="500px"), key="ciphos-operational-data-subgraph"
    )
    return len(visual_graph.nodes)


def render(operational_graph: GraphConnection) -> None:
    st.title("Operational graph")
    st.caption("Explore current-state CIPHOS relationships. The display is bounded and read-only.")

    if not operational_graph.ok or operational_graph.driver is None:
        st.error(f"Operational graph unavailable: {operational_graph.error}")
        return

    labels = contract.projected_nodes()
    default_index = labels.index("Tag") if "Tag" in labels else 0
    label_column, entity_column, depth_column = st.columns((1, 2, 1))
    with label_column:
        selected_label = st.selectbox("Label", labels, index=default_index)
    try:
        instances = list_instances(
            operational_graph.driver, operational_graph.database, selected_label
        )
    except Exception as error:
        st.error(f"Could not list {selected_label} entities: {error}")
        return
    if not instances:
        st.info(f"No {selected_label} entities are present in the active projection.")
        return

    with entity_column:
        selected_instance = st.selectbox(
            "Entity", instances, format_func=lambda item: item["display"]
        )
    with depth_column:
        depth = st.selectbox("Depth", DEPTH_OPTIONS, index=1)

    selected_types = tuple(st.multiselect("Relationship types", contract.projected_relationships()))
    try:
        total_nodes = reachable_node_count(
            operational_graph.driver,
            operational_graph.database,
            selected_label,
            selected_instance["external_id"],
            selected_types,
            depth,
        )
        result = bounded_subgraph(
            operational_graph.driver,
            operational_graph.database,
            selected_label,
            selected_instance["external_id"],
            selected_types,
            depth,
        )
        shown_nodes = render_subgraph(result)
    except Exception as error:
        st.error(f"Graph query failed: {error}")
        return

    relationship_caption = (
        "All retained relationship types are included."
        if not selected_types
        else "Filtered to the selected relationship types."
    )
    st.caption(
        f"Showing {shown_nodes} of {total_nodes} nodes within depth {depth}. "
        f"Capped at {NODE_BUDGET} nodes. "
        f"{relationship_caption}"
    )
