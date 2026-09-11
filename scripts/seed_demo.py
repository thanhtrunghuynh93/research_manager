#!/usr/bin/env python3
"""Load the demo dataset: one professor, six students, four projects, eight periods, fake repo events.

Thin wrapper around the application's seed command so the dataset definition lives with the
modules that own the data (identity, projects, reporting, evidence). Usage: python3 scripts/seed_demo.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"

if __name__ == "__main__":
    sys.exit(subprocess.call(["uv", "run", "python", "-m", "app.cli", "seed", "demo"], cwd=BACKEND))
