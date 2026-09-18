"""Configuration and safety checks for the CIPHOS semantic-map store.

The operational projection and semantic store are intentionally represented by
different types.  This makes it harder for a caller to accidentally pass an
operational connection to a write-oriented semantic-store operation.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from neo4j import RoutingControl

from .semantic_map_contract import SourceIdentity

OPERATIONAL_ENV_NAMES = (
    "OPS_NEO4J_URI",
    "OPS_NEO4J_USERNAME",
    "OPS_NEO4J_PASSWORD",
    "OPS_NEO4J_DATABASE",
)
SEMANTIC_STORE_ENV_NAMES = (
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
)

OPERATIONAL_LABEL_CHECK_CYPHER = """
MATCH (node)
WHERE any(node_label IN labels(node) WHERE node_label IN $operational_labels)
RETURN count(node) AS operational_node_count
"""
OPERATIONAL_GRAPH_LABELS = ("CiphosEntity", "CiphosProjection")


@dataclass(frozen=True)
class OperationalNeo4jConnection:
    """Connection configuration for the serving CIPHOS projection."""

    uri: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)
    database: str

    @property
    def identity(self) -> SourceIdentity:
        """Return a normalized, credential-free source identity."""
        return SourceIdentity.from_connection(self.uri, self.database)


@dataclass(frozen=True)
class SemanticStoreNeo4jConnection:
    """Connection configuration for the dedicated NeoCarta metadata store."""

    uri: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)
    database: str

    @property
    def identity(self) -> SourceIdentity:
        """Return a normalized, credential-free target identity."""
        return SourceIdentity.from_connection(self.uri, self.database)


def _value(environment: Mapping[str, str], name: str) -> str:
    return environment.get(name, "").strip()


def _require(environment: Mapping[str, str], name: str) -> str:
    value = _value(environment, name)
    if not value or value.startswith("<"):
        raise ValueError(f"Set {name} before running the semantic-map operation.")
    return value


def _reject_stale_operational_environment(environment: Mapping[str, str]) -> None:
    """Reject every partially migrated operational variable, without guessing."""
    for operational_name, legacy_name in zip(
        OPERATIONAL_ENV_NAMES, SEMANTIC_STORE_ENV_NAMES, strict=True
    ):
        if not _value(environment, operational_name) and _value(environment, legacy_name):
            raise ValueError(
                f"{operational_name} is unset while {legacy_name} is set. "
                "Bare NEO4J_* now selects the semantic store; rename operational settings "
                "to OPS_NEO4J_*."
            )


def load_operational_connection(
    environment: Mapping[str, str] | None = None,
) -> OperationalNeo4jConnection:
    """Load the operational graph configuration and reject a stale `.env`."""
    values = environment if environment is not None else os.environ
    _reject_stale_operational_environment(values)
    return OperationalNeo4jConnection(
        uri=_require(values, "OPS_NEO4J_URI"),
        username=_require(values, "OPS_NEO4J_USERNAME"),
        password=_require(values, "OPS_NEO4J_PASSWORD"),
        database=_require(values, "OPS_NEO4J_DATABASE"),
    )


def load_semantic_store_connection(
    environment: Mapping[str, str] | None = None,
) -> SemanticStoreNeo4jConnection:
    """Load the dedicated semantic-store connection from bare ``NEO4J_*`` names."""
    values = environment if environment is not None else os.environ
    return SemanticStoreNeo4jConnection(
        uri=_require(values, "NEO4J_URI"),
        username=_require(values, "NEO4J_USERNAME"),
        password=_require(values, "NEO4J_PASSWORD"),
        database=_require(values, "NEO4J_DATABASE"),
    )


def assert_safe_semantic_store_target(
    source: OperationalNeo4jConnection,
    store: SemanticStoreNeo4jConnection,
    *,
    candidate_database: str | None = None,
) -> None:
    """Ensure the target is neither the serving nor configured candidate graph."""
    if source.identity == store.identity:
        raise ValueError("Semantic-store target must differ from the operational source identity.")
    if candidate_database and candidate_database.strip():
        candidate_identity = SourceIdentity.from_connection(source.uri, candidate_database)
        if candidate_identity == store.identity:
            raise ValueError(
                "Semantic-store target must differ from the CIPHOS candidate identity."
            )


def assert_no_operational_graph_nodes(
    target_driver: Any, target: SemanticStoreNeo4jConnection
) -> None:
    """Reject a store target that already contains known CIPHOS operational labels."""
    records, _, _ = target_driver.execute_query(
        query_=OPERATIONAL_LABEL_CHECK_CYPHER,
        parameters_={"operational_labels": list(OPERATIONAL_GRAPH_LABELS)},
        database_=target.database,
        routing_=RoutingControl.READ,
    )
    if records:
        first = records[0]
        count = first["operational_node_count"] if hasattr(first, "__getitem__") else 0
        if int(count) > 0:
            raise ValueError("Semantic-store target contains CIPHOS operational graph nodes.")
