"""Launch the CIPHOS Streamlit explorer on an available local port."""

from __future__ import annotations

import subprocess
import sys
from os import environ
from pathlib import Path
from socket import AF_INET, SOCK_STREAM, socket

APP_PATH = Path(__file__).resolve().parent / "demo" / "app.py"
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DEMO_PORT = 8503
LAST_DEMO_PORT = 8599


def _is_available(port: int) -> bool:
    """Check whether a localhost TCP port can be bound before starting Streamlit."""
    with socket(AF_INET, SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", port))
    return True


def demo_port(environment: dict[str, str] | None = None) -> int:
    """Use DEMO_PORT when requested, otherwise find a free dedicated local port."""
    values = environment if environment is not None else environ
    requested = values.get("DEMO_PORT", "").strip()
    if requested:
        try:
            port = int(requested)
        except ValueError as error:
            raise ValueError("DEMO_PORT must be a TCP port number.") from error
        if not 1 <= port <= 65535:
            raise ValueError("DEMO_PORT must be between 1 and 65535.")
        return port
    for port in range(DEFAULT_DEMO_PORT, LAST_DEMO_PORT + 1):
        try:
            if _is_available(port):
                return port
        except OSError:
            continue
    raise RuntimeError(
        f"No free port found between {DEFAULT_DEMO_PORT} and {LAST_DEMO_PORT}. "
        "Set DEMO_PORT to an available port."
    )


def _has_server_port(arguments: list[str]) -> bool:
    return any(
        argument == "--server.port" or argument.startswith("--server.port=")
        for argument in arguments
    )


def main() -> int:
    """Run the bundled Streamlit explorer, choosing a local port when needed."""
    arguments = list(sys.argv[1:])
    if not _has_server_port(arguments):
        port = demo_port()
        arguments.extend(("--server.port", str(port)))
        print(f"CIPHOS explorer: http://localhost:{port}")
    return subprocess.call(
        [sys.executable, "-m", "streamlit", "run", str(APP_PATH), *arguments],
        cwd=PROJECT_DIR,
    )


if __name__ == "__main__":
    raise SystemExit(main())
