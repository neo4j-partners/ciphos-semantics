"""Runtime-only configuration for the disposable local Neo4j environment."""

from __future__ import annotations

import os
from collections.abc import MutableMapping

LOCAL_NEO4J_FLAG = "NEO4J_LOCAL"
LOCAL_NEO4J_PASSWORD = "CIPHOS_TEST_NEO4J_PASSWORD"
LOCAL_NEO4J_DEFAULT_PASSWORD = "ciphos-test-password"


def local_neo4j_enabled(environment: MutableMapping[str, str] | None = None) -> bool:
    """Return whether local Docker Compose Neo4j endpoints were explicitly selected."""
    values = environment if environment is not None else os.environ
    return values.get(LOCAL_NEO4J_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def configure_local_neo4j(environment: MutableMapping[str, str] | None = None) -> bool:
    """Select Compose endpoints for this process without changing ``.env``.

    The source and semantic-store containers deliberately use separate local
    Bolt ports. Applying these values only after an explicit opt-in prevents
    a developer's normal Aura or shared-environment settings from being lost.
    """
    values = environment if environment is not None else os.environ
    if not local_neo4j_enabled(values):
        return False

    password = values.get(LOCAL_NEO4J_PASSWORD, LOCAL_NEO4J_DEFAULT_PASSWORD)
    values.update(
        {
            "OPS_NEO4J_URI": "bolt://127.0.0.1:17688",
            "OPS_NEO4J_USERNAME": "neo4j",
            "OPS_NEO4J_PASSWORD": password,
            "OPS_NEO4J_DATABASE": "neo4j",
            "NEO4J_URI": "bolt://127.0.0.1:17689",
            "NEO4J_USERNAME": "neo4j",
            "NEO4J_PASSWORD": password,
            "NEO4J_DATABASE": "neo4j",
        }
    )
    return True
