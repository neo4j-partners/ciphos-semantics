"""Extract a metadata-only CIPHOS Neo4j schema map through a fixed allowlist."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from neo4j import RoutingControl
from neo4j.exceptions import Neo4jError

from ciphos_semantics.semantic_map_contract import (
    SchemaMap,
    SemanticEdge,
    SourceIdentity,
    canonical_label_set,
    scoped_id,
    source_scope,
    split_node_labels,
)

PropertySelector = tuple[str, tuple[str, ...], str]
OwnerSelector = tuple[str, tuple[str, ...], tuple[str, ...], str]

LABELS_QUERY = "CALL db.labels() YIELD label RETURN label ORDER BY label"
RELATIONSHIP_TYPES_QUERY = (
    "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType "
    "ORDER BY relationshipType"
)
NODE_PROPERTIES_QUERY = """
CALL db.schema.nodeTypeProperties()
YIELD nodeType, nodeLabels, propertyName, propertyTypes, mandatory
RETURN nodeType, nodeLabels, propertyName, propertyTypes, mandatory
ORDER BY nodeType, propertyName
""".strip()
RELATIONSHIP_PROPERTIES_QUERY = """
CALL db.schema.relTypeProperties()
YIELD relType, propertyName, propertyTypes, mandatory
RETURN relType, propertyName, propertyTypes, mandatory
ORDER BY relType, propertyName
""".strip()
# The virtual relationships yielded by db.schema.visualization() carry endpoint
# element IDs but not endpoint labels: reading startNode() or endNode() off an
# unwound relationship returns a stub with no labels and no name.  The endpoint
# descriptors live in the procedure's own `nodes` column, so resolve each
# endpoint there by element ID instead of dereferencing the relationship.
ENDPOINTS_QUERY = """
CALL db.schema.visualization()
YIELD nodes, relationships
UNWIND relationships AS relationship
WITH head([candidate IN nodes WHERE elementId(candidate) = elementId(startNode(relationship))])
         AS source,
     head([candidate IN nodes WHERE elementId(candidate) = elementId(endNode(relationship))])
         AS target,
     relationship
RETURN type(relationship) AS relationship_type,
       coalesce(source["name"], head(labels(source))) AS source_label,
       coalesce(target["name"], head(labels(target))) AS target_label
ORDER BY relationship_type, source_label, target_label
""".strip()
CONSTRAINTS_QUERY = """
SHOW CONSTRAINTS
YIELD entityType, labelsOrTypes, properties, type
RETURN entityType, labelsOrTypes, properties, type
ORDER BY entityType, labelsOrTypes, properties, type
""".strip()
INDEXES_QUERY = """
SHOW INDEXES
YIELD entityType, labelsOrTypes, properties, type
RETURN entityType, labelsOrTypes, properties, type
ORDER BY entityType, labelsOrTypes, properties, type
""".strip()

REQUIRED_SCHEMA_QUERIES: dict[str, str] = {
    "labels": LABELS_QUERY,
    "relationship_types": RELATIONSHIP_TYPES_QUERY,
    "node_properties": NODE_PROPERTIES_QUERY,
    "relationship_properties": RELATIONSHIP_PROPERTIES_QUERY,
    "constraints": CONSTRAINTS_QUERY,
    "indexes": INDEXES_QUERY,
}
SCHEMA_QUERY_ALLOWLIST = frozenset((*REQUIRED_SCHEMA_QUERIES.values(), ENDPOINTS_QUERY))

# Schema introspection always raises two kinds of server notification that say
# nothing about the source. The node and relationship property procedures warn
# that `propertyTypes` will change output format (GENERIC), and the endpoint
# query's coalesce over `name` warns that no node uses that key on the servers
# that omit it (UNRECOGNIZED). The coalesce stays because servers that do
# populate `name` give a better endpoint label than the first raw label, so the
# notifications are suppressed on the source driver instead. They would
# otherwise bury the real output of every extraction.
SUPPRESSED_SOURCE_NOTIFICATIONS = ("GENERIC", "UNRECOGNIZED")


class SchemaExtractionError(RuntimeError):
    """Raised when required metadata cannot be safely extracted or interpreted."""


def _record_rows(records: Sequence[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, Mapping):
            rows.append(dict(record))
        elif hasattr(record, "data"):
            rows.append(dict(record.data()))
        else:
            raise SchemaExtractionError(
                "Neo4j returned a schema row that cannot be converted to a mapping."
            )
    return rows


def _read_query(driver: Any, query: str, database: str) -> list[dict[str, Any]]:
    records, _, _ = driver.execute_query(
        query_=query,
        database_=database,
        routing_=RoutingControl.READ,
    )
    return _record_rows(records)


def read_required_schema_metadata(driver: Any, database: str) -> dict[str, list[dict[str, Any]]]:
    """Read all non-optional metadata queries, failing closed on access errors."""
    metadata: dict[str, list[dict[str, Any]]] = {}
    try:
        for name, query in REQUIRED_SCHEMA_QUERIES.items():
            metadata[name] = _read_query(driver, query, database)
    except Neo4jError as error:
        raise SchemaExtractionError(
            "Unable to read required Neo4j schema metadata, including constraints and indexes. "
            "Grant the source identity access to every configured schema procedure and SHOW "
            "command."
        ) from error
    return metadata


def read_endpoints(driver: Any, database: str) -> tuple[list[dict[str, Any]], bool]:
    """Read optional statistics-based endpoint metadata without masking malformed data."""
    try:
        rows = _read_query(driver, ENDPOINTS_QUERY, database)
    except Neo4jError:
        return [], False
    endpoint_fields = ("relationship_type", "source_label", "target_label")
    usable_rows = [
        row
        for row in rows
        if all(isinstance(row.get(field), str) and row[field].strip() for field in endpoint_fields)
    ]
    # Some Neo4j versions return virtual schema relationships without endpoint
    # names or labels. That is unavailable endpoint evidence, not a malformed
    # source schema and never a reason to invent endpoint links.
    return usable_rows, bool(usable_rows)


def normalize_relationship_type(value: object) -> str:
    """Return a bare relationship type from Neo4j's procedure formatting."""
    text = str(value).strip().removeprefix(":")
    if text.startswith("`") and text.endswith("`"):
        text = text[1:-1]
    return text


def _required_text(row: Mapping[str, Any], field: str, row_name: str) -> str:
    if field not in row:
        raise SchemaExtractionError(f"Malformed {row_name} row: missing {field}.")
    raw_value = row[field]
    if raw_value is None:
        raise SchemaExtractionError(f"Malformed {row_name} row: {field} must not be empty.")
    value = str(raw_value).strip()
    if not value:
        raise SchemaExtractionError(f"Malformed {row_name} row: {field} must not be empty.")
    return value


def _required_collection(row: Mapping[str, Any], field: str, row_name: str) -> tuple[str, ...]:
    if field not in row:
        raise SchemaExtractionError(f"Malformed {row_name} row: missing {field}.")
    value = row[field]
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set)):
        raise SchemaExtractionError(f"Malformed {row_name} row: {field} must be a collection.")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _property_type(row: Mapping[str, Any], row_name: str) -> str | None:
    values = _required_collection(row, "propertyTypes", row_name)
    return " | ".join(sorted(set(values))) or None


def _is_propertyless_row(row: Mapping[str, Any]) -> bool:
    """Identify Neo4j's sentinel rows for a node or relationship type without properties."""
    return row.get("propertyName") is None and row.get("propertyTypes") is None


def _mandatory(row: Mapping[str, Any], row_name: str) -> bool:
    value = row.get("mandatory")
    if not isinstance(value, bool):
        raise SchemaExtractionError(f"Malformed {row_name} row: mandatory must be a boolean.")
    return value


def _owner_selector(
    row: Mapping[str, Any], row_name: str
) -> OwnerSelector | None:
    entity_type = _required_text(row, "entityType", row_name).upper()
    if entity_type not in {"NODE", "RELATIONSHIP"}:
        raise SchemaExtractionError(
            f"Malformed {row_name} row: unsupported entityType {entity_type!r}."
        )
    descriptor_type = _required_text(row, "type", row_name).upper()
    properties_value = row.get("properties")
    if descriptor_type == "LOOKUP":
        if properties_value is None or properties_value in ([], (), set()):
            return None
        raise SchemaExtractionError(
            f"Malformed {row_name} row: LOOKUP descriptors must not declare properties."
        )
    labels_or_types = _required_collection(row, "labelsOrTypes", row_name)
    properties = _required_collection(row, "properties", row_name)
    if not labels_or_types or not properties:
        raise SchemaExtractionError(
            f"Malformed {row_name} row: property-bearing descriptors require labelsOrTypes "
            "and properties."
        )
    return entity_type, labels_or_types, properties, descriptor_type


def _constraint_flags(
    constraints: Sequence[Mapping[str, Any]], indexes: Sequence[Mapping[str, Any]]
) -> tuple[set[PropertySelector], set[PropertySelector], set[PropertySelector]]:
    """Return owner/property selectors carrying unique, indexed, and existence state."""
    unique: set[PropertySelector] = set()
    indexed: set[PropertySelector] = set()
    existence: set[PropertySelector] = set()

    for row in constraints:
        selector = _owner_selector(row, "constraint")
        if selector is None:
            continue
        entity_type, owner, properties, constraint_type = selector
        for property_name in properties:
            key = (entity_type, owner, property_name)
            if "UNIQUENESS" in constraint_type or constraint_type.endswith("_KEY"):
                unique.add(key)
            if "EXISTENCE" in constraint_type or constraint_type.endswith("_KEY"):
                existence.add(key)

    for row in indexes:
        selector = _owner_selector(row, "index")
        if selector is None:
            continue
        entity_type, owner, properties, _ = selector
        for property_name in properties:
            indexed.add((entity_type, owner, property_name))
    return unique, indexed, existence


def _matches_owner(entity_type: str, owner: tuple[str, ...], selector: tuple[str, ...]) -> bool:
    if entity_type == "RELATIONSHIP":
        return owner == selector
    return set(selector).issubset(owner)


def _property_flags(
    entity_type: str,
    owner: tuple[str, ...],
    property_name: str,
    flags: set[PropertySelector],
) -> bool:
    return any(
        flag_entity_type == entity_type
        and flag_property == property_name
        and _matches_owner(entity_type, owner, selector)
        for flag_entity_type, selector, flag_property in flags
    )


def _endpoint_label(row: Mapping[str, Any], field: str) -> str:
    return _required_text(row, field, "endpoint").removeprefix(":").strip("`")


def _resolve_label_sets(
    label_rows: Sequence[Mapping[str, Any]],
    node_property_rows: Sequence[Mapping[str, Any]],
    endpoints: Sequence[Mapping[str, Any]],
) -> set[tuple[str, ...]]:
    """Keep reported label sets, adding a bare label only when none covers it.

    ``db.labels()`` and ``db.schema.visualization()`` report individual labels
    while ``db.schema.nodeTypeProperties()`` reports whole label sets.  Promoting
    every bare label to its own set would claim node types the source does not
    have: every projected CIPHOS node carries ``CiphosEntity``, so a bare
    ``CiphosEntity`` set describes nothing in the graph, and a bare ``Tag`` set
    duplicates the reported ``CiphosEntity`` plus ``Tag`` node.  A bare label is
    still kept when no reported label set contains it, so a label the property
    procedure never reports does not disappear from the map.
    """
    reported: set[tuple[str, ...]] = set()
    for row in node_property_rows:
        if "nodeLabels" not in row:
            raise SchemaExtractionError("Malformed node property row: missing nodeLabels.")
        reported.add(canonical_label_set(row["nodeLabels"]))

    bare_labels = {_required_text(row, "label", "label") for row in label_rows}
    for row in endpoints:
        bare_labels.add(_endpoint_label(row, "source_label"))
        bare_labels.add(_endpoint_label(row, "target_label"))

    covered = {label for labels in reported for label in labels}
    return reported | {(label,) for label in bare_labels if label not in covered}


def _endpoint_candidates(
    label: str, label_sets: set[tuple[str, ...]]
) -> tuple[tuple[str, ...], ...]:
    candidates = tuple(sorted(labels for labels in label_sets if label in labels))
    if not candidates:
        raise SchemaExtractionError(
            f"Malformed endpoint row: {label!r} does not identify a source-reported label set."
        )
    return candidates


def build_schema_map(
    identity: SourceIdentity,
    metadata: Mapping[str, Sequence[Mapping[str, Any]]],
    endpoints: Sequence[Mapping[str, Any]],
    *,
    endpoints_available: bool,
) -> SchemaMap:
    """Transform validated source metadata into deterministic NeoCarta-shaped records."""
    required_names = frozenset(REQUIRED_SCHEMA_QUERIES)
    missing = sorted(required_names.difference(metadata))
    if missing:
        raise SchemaExtractionError(
            f"Missing required schema metadata groups: {', '.join(missing)}."
        )

    scope = source_scope(identity)
    database_id = scoped_id(scope, "database", identity.database)
    schema_id = scoped_id(scope, "schema", "default")
    label_sets = _resolve_label_sets(
        metadata["labels"], metadata["node_properties"], endpoints
    )

    node_ids = {labels: scoped_id(scope, "node", *labels) for labels in sorted(label_sets)}
    nodes = []
    for labels in sorted(node_ids):
        primary, additional = split_node_labels(labels)
        row: dict[str, Any] = {"id": node_ids[labels], "label": primary}
        if additional:
            row["additional_labels"] = list(additional)
        nodes.append(row)

    relationship_types = {
        normalize_relationship_type(_required_text(row, "relationshipType", "relationship type"))
        for row in metadata["relationship_types"]
    }
    relationship_types.update(
        normalize_relationship_type(_required_text(row, "relType", "relationship property"))
        for row in metadata["relationship_properties"]
    )
    relationship_types.update(
        normalize_relationship_type(_required_text(row, "relationship_type", "endpoint"))
        for row in endpoints
    )
    if "" in relationship_types:
        raise SchemaExtractionError(
            "Malformed relationship type row: relationship type must not be empty."
        )
    relationship_ids = {
        relationship_type: scoped_id(scope, "relationship", relationship_type)
        for relationship_type in sorted(relationship_types)
    }
    relationships = [
        {"id": relationship_ids[relationship_type], "type": relationship_type}
        for relationship_type in sorted(relationship_ids)
    ]

    unique_flags, indexed_flags, existence_flags = _constraint_flags(
        metadata["constraints"], metadata["indexes"]
    )
    properties: list[dict[str, Any]] = []
    property_keys: set[tuple[str, str]] = set()
    edges: set[SemanticEdge] = {SemanticEdge(database_id, "HAS_SCHEMA", schema_id)}
    edges.update(SemanticEdge(schema_id, "HAS_NODE", node_id) for node_id in node_ids.values())
    edges.update(
        SemanticEdge(schema_id, "HAS_RELATIONSHIP", relationship_id)
        for relationship_id in relationship_ids.values()
    )

    for source_row in metadata["node_properties"]:
        owner = canonical_label_set(source_row["nodeLabels"])
        if _is_propertyless_row(source_row):
            continue
        property_name = _required_text(source_row, "propertyName", "node property")
        key = (node_ids[owner], property_name)
        if key in property_keys:
            raise SchemaExtractionError(
                f"Malformed node property row: duplicate property {property_name!r} for {owner!r}."
            )
        property_keys.add(key)
        property_id = scoped_id(scope, "node-property", node_ids[owner], property_name)
        property_row: dict[str, Any] = {
            "id": property_id,
            "name": property_name,
            "nullable": not _mandatory(source_row, "node property"),
            "unique": _property_flags("NODE", owner, property_name, unique_flags),
            "indexed": _property_flags("NODE", owner, property_name, indexed_flags),
            "existence": _property_flags("NODE", owner, property_name, existence_flags),
        }
        reported_type = _property_type(source_row, "node property")
        if reported_type is not None:
            property_row["type"] = reported_type
        properties.append(property_row)
        edges.add(SemanticEdge(node_ids[owner], "HAS_PROPERTY", property_id))

    for source_row in metadata["relationship_properties"]:
        relationship_type = normalize_relationship_type(
            _required_text(source_row, "relType", "relationship property")
        )
        if not relationship_type:
            raise SchemaExtractionError(
                "Malformed relationship property row: relType must not be empty."
            )
        if _is_propertyless_row(source_row):
            continue
        owner_id = relationship_ids[relationship_type]
        property_name = _required_text(source_row, "propertyName", "relationship property")
        key = (owner_id, property_name)
        if key in property_keys:
            raise SchemaExtractionError(
                "Malformed relationship property row: "
                f"duplicate property {property_name!r} for {relationship_type!r}."
            )
        property_keys.add(key)
        property_id = scoped_id(scope, "relationship-property", owner_id, property_name)
        property_row = {
            "id": property_id,
            "name": property_name,
            "nullable": not _mandatory(source_row, "relationship property"),
            "unique": _property_flags(
                "RELATIONSHIP", (relationship_type,), property_name, unique_flags
            ),
            "indexed": _property_flags(
                "RELATIONSHIP", (relationship_type,), property_name, indexed_flags
            ),
            "existence": _property_flags(
                "RELATIONSHIP", (relationship_type,), property_name, existence_flags
            ),
        }
        reported_type = _property_type(source_row, "relationship property")
        if reported_type is not None:
            property_row["type"] = reported_type
        properties.append(property_row)
        edges.add(SemanticEdge(owner_id, "HAS_PROPERTY", property_id))

    for endpoint in endpoints:
        relationship_type = normalize_relationship_type(
            _required_text(endpoint, "relationship_type", "endpoint")
        )
        relationship_id = relationship_ids[relationship_type]
        source_candidates = _endpoint_candidates(
            _endpoint_label(endpoint, "source_label"), label_sets
        )
        target_candidates = _endpoint_candidates(
            _endpoint_label(endpoint, "target_label"), label_sets
        )
        for source_labels in source_candidates:
            for target_labels in target_candidates:
                edges.add(SemanticEdge(relationship_id, "HAS_SOURCE_NODE", node_ids[source_labels]))
                edges.add(SemanticEdge(relationship_id, "HAS_TARGET_NODE", node_ids[target_labels]))

    return SchemaMap(
        source_identity=identity,
        source_scope=scope,
        database={"id": database_id, "name": identity.database, "service": "NEO4J"},
        schema={"id": schema_id, "name": "default"},
        nodes=tuple(nodes),
        relationships=tuple(relationships),
        properties=tuple(sorted(properties, key=lambda row: str(row["id"]))),
        edges=tuple(sorted(edges)),
        endpoints_available=endpoints_available,
    )


def extract_schema_map(driver: Any, identity: SourceIdentity) -> SchemaMap:
    """Extract the configured source map without reading operational graph values."""
    metadata = read_required_schema_metadata(driver, identity.database)
    endpoints, endpoints_available = read_endpoints(driver, identity.database)
    return build_schema_map(identity, metadata, endpoints, endpoints_available=endpoints_available)
