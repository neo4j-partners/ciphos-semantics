"""Launch the CIPHOS hybrid traceability Streamlit application."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP_PATH = Path(__file__).resolve().parent / "demo" / "app.py"
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent


def main() -> int:
    """Run the bundled Streamlit demo."""
    return subprocess.call(
        [sys.executable, "-m", "streamlit", "run", str(APP_PATH), *sys.argv[1:]],
        cwd=PROJECT_DIR,
    )


if __name__ == "__main__":
    raise SystemExit(main())
