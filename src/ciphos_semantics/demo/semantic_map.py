"""Shared neo4j-viz rendering for THE MAP half of the operational graph page.

Renders the NeoCarta semantic store's structural map (Database/Schema/Node/
Relationship/Property) for one source scope: nodes and relationships
belonging to the traced label stay full-size and coloured by caption,
everything else in the map dims.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from neo4j import Driver, RoutingControl
from neo4j_viz import VisualizationGraph
from neo4j_viz.neo4j import from_neo4j
from neo4j_viz.streamlit import display_widget

TRACED_SIZE = 42
DIMMED_SIZE = 14
DIMMED_COLOR = "#C7C7C7"
DEFAULT_HEIGHT = 480

# Each query below is scoped to exactly one HAS_* branch. Chaining
# independent OPTIONAL MATCH branches off the same anchor (node-property
# fan-out alongside relationship-property/endpoint fan-out, as one combined
# query would) makes Cypher compute their full cross product row-by-row. On a
# schema with as many relationship types and properties as CIPHOS's, that
# cartesian product overwhelms the driver before `from_neo4j` ever gets a
# chance to deduplicate it into a graph. Splitting into one correlated query
# per branch and merging the resulting graphs (see `_visualization_graph`)
# keeps every row correlated only to what it actually describes.
DATABASE_SCHEMA_QUERY = """
MATCH (d:Database {source_scope: $scope})-[hs:HAS_SCHEMA]->(s:Schema {source_scope: $scope})
RETURN d, s, hs
"""

NODE_PROPERTY_QUERY = """
MATCH (s:Schema {source_scope: $scope})-[hn:HAS_NODE]->(n:Node)
OPTIONAL MATCH (n)-[hp:HAS_PROPERTY]->(p:Property)
RETURN n, p, hn, hp
"""

RELATIONSHIP_PROPERTY_QUERY = """
MATCH (s:Schema {source_scope: $scope})-[hr:HAS_RELATIONSHIP]->(rel:Relationship)
OPTIONAL MATCH (rel)-[hrp:HAS_PROPERTY]->(rp:Property)
RETURN rel, rp, hr, hrp
"""

RELATIONSHIP_SOURCE_QUERY = """
MATCH (:Schema {source_scope: $scope})-[:HAS_RELATIONSHIP]->(rel:Relationship)
      -[hsn:HAS_SOURCE_NODE]->(src:Node)
RETURN rel, src, hsn
"""

RELATIONSHIP_TARGET_QUERY = """
MATCH (:Schema {source_scope: $scope})-[:HAS_RELATIONSHIP]->(rel:Relationship)
      -[htn:HAS_TARGET_NODE]->(tgt:Node)
RETURN rel, tgt, htn
"""

MAP_QUERIES = (
    DATABASE_SCHEMA_QUERY,
    NODE_PROPERTY_QUERY,
    RELATIONSHIP_PROPERTY_QUERY,
    RELATIONSHIP_SOURCE_QUERY,
    RELATIONSHIP_TARGET_QUERY,
)

GRAPH_TRACE_STATS_QUERY = """
MATCH (n:Node {source_scope: $scope, label: $label})
OPTIONAL MATCH (n)-[:HAS_PROPERTY]->(p:Property)
OPTIONAL MATCH (rel:Relationship {source_scope: $scope})-[:HAS_SOURCE_NODE]->(n)
RETURN count(DISTINCT p) AS property_count,
       count(DISTINCT rel) AS relationship_type_count
"""


def _node_caption(properties: Mapping[str, Any], fallback: str) -> str:
    """Prefer `label`, then `name`, then `type`; fall back to neo4j_viz's own caption."""
    return properties.get("label") or properties.get("name") or properties.get("type") or fallback


def _visualization_graph(driver: Driver, database: str, scope: str) -> VisualizationGraph:
    """Merge each narrowly-scoped query's graph into one, deduplicated by element id."""
    nodes: dict[str, Any] = {}
    relationships: dict[str, Any] = {}
    for query in MAP_QUERIES:
        result = driver.execute_query(
            query,
            parameters_={"scope": scope},
            database_=database,
            routing_=RoutingControl.READ,
        )
        partial = from_neo4j(result)
        for node in partial.nodes:
            nodes.setdefault(node.id, node)
        for rel in partial.relationships:
            relationships.setdefault(rel.id, rel)
    return VisualizationGraph(list(nodes.values()), list(relationships.values()))


def render_map(
    driver: Driver,
    database: str,
    scope: str,
    *,
    key: str,
    hidden_labels: Iterable[str] = (),
    hidden_relationship_types: Iterable[str] = (),
    is_traced_node: Callable[[dict[str, Any]], bool] = lambda properties: False,
    height: int = DEFAULT_HEIGHT,
) -> tuple[int, int]:
    """Render the NeoCarta semantic map for one source scope, dimmed except the traced label.

    `key` must be a stable, unique Streamlit key so the widget's layout choice
    survives reruns. Returns the rendered (node_count, relationship_count).
    """
    vg = _visualization_graph(driver, database, scope)

    hidden_labels = set(hidden_labels)
    hidden_relationship_types = set(hidden_relationship_types)

    kept_nodes = [
        node
        for node in vg.nodes
        if not hidden_labels.intersection(node.properties.get("labels", ()))
    ]
    kept_ids = {node.id for node in kept_nodes}

    kept_relationships = [
        rel
        for rel in vg.relationships
        if rel.properties.get("type") not in hidden_relationship_types
        and rel.source in kept_ids
        and rel.target in kept_ids
    ]

    vg.nodes = kept_nodes
    vg.relationships = kept_relationships
    vg.color_nodes(field="caption")

    # Database/Schema are the map's singleton root context, not part of the
    # traced-vs-everything-else distinction; dimming them made the store's
    # own root indistinguishable from the grey background.
    always_traced_labels = {"Database", "Schema"}
    traced_ids: set[str] = {
        node.id
        for node in vg.nodes
        if is_traced_node(node.properties)
        or always_traced_labels.intersection(node.properties.get("labels", ()))
    }
    for rel in vg.relationships:
        if rel.source in traced_ids or rel.target in traced_ids:
            traced_ids.add(rel.source)
            traced_ids.add(rel.target)

    for node in vg.nodes:
        node.caption = _node_caption(node.properties, node.caption)
        if node.id in traced_ids:
            node.size = TRACED_SIZE
        else:
            node.size = DIMMED_SIZE
            node.color = DIMMED_COLOR

    for rel in vg.relationships:
        if rel.source in traced_ids and rel.target in traced_ids:
            rel.width = 3
        else:
            rel.color = DIMMED_COLOR

    widget = vg.render_widget(height=f"{height}px")
    display_widget(widget, key=key)
    return len(vg.nodes), len(vg.relationships)
