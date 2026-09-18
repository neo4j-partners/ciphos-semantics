"""Start, seed, and verify the disposable local CIPHOS Neo4j environment."""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from ciphos_semantics.local_neo4j import LOCAL_NEO4J_FLAG, configure_local_neo4j
from ciphos_semantics.semantic_cli import context_main, ingest_main, validate_main

PROJECT_DIR = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_DIR / "docker-compose.semantic-test.yml"


def _compose(*arguments: str) -> None:
    """Run the project-local Compose file with the caller's intact environment."""
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *arguments],
        check=True,
        cwd=PROJECT_DIR,
    )


def up() -> None:
    """Start and seed local containers, then populate the local semantic store."""
    os.environ[LOCAL_NEO4J_FLAG] = "true"
    _compose("up", "-d")
    _compose("wait", "seed-source")
    configure_local_neo4j()
    ingest_main()
    validate_main()
    context_main([])


def down() -> None:
    """Remove the disposable containers and their Docker volumes."""
    _compose("down", "--volumes")


def main(argv: Sequence[str] | None = None) -> None:
    """Run the local environment lifecycle command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("up", "down"),
        default="up",
        nargs="?",
        help="up starts, seeds, and populates Neo4j; down removes containers and volumes.",
    )
    args = parser.parse_args(argv)
    if args.command == "up":
        up()
    else:
        down()


if __name__ == "__main__":
    main()
