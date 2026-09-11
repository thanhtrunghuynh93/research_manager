#!/usr/bin/env python3
"""Load the benchmark dataset for the capacity targets in architecture §15:
50 students, 30 projects, 3 years of weekly reports, and 100k evidence chunks.

Usage: python3 scripts/seed_benchmark.py [--scale 1.0]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"

if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(
        subprocess.call(
            ["uv", "run", "python", "-m", "app.cli", "seed", "benchmark", *args], cwd=BACKEND
        )
    )
