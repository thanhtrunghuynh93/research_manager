#!/usr/bin/env python3
"""Every requirement and scenario ID in the specification must be covered.

Checks:
  1. docs/architecture.md section 16 lists the ID.
  2. Once the acceptance tests exist (backend/tests/acceptance), every AC-xx has a test file or
     docstring naming it. This check is a warning until the first acceptance test lands.
Exit code 1 on a missing architecture mapping.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "research_management_requirements.md"
ARCH = ROOT / "docs" / "architecture.md"
TESTS = ROOT / "backend" / "tests"

ID_RE = re.compile(r"\b(?:AUTH|PROJ|REP|REPO|ASSESS|QA|UI|AC)-\d{2}\b")


def main() -> int:
    spec_ids = sorted(set(ID_RE.findall(SPEC.read_text(encoding="utf-8"))))
    arch = ARCH.read_text(encoding="utf-8")
    trace = arch.split("## 16 Requirements traceability", 1)[1].split("\n## ", 1)[0]
    missing = [i for i in spec_ids if not re.search(r"\|\s*" + re.escape(i) + r"\s*\|", trace)]

    print(f"spec ids: {len(spec_ids)}; missing in architecture traceability: {missing or 'none'}")

    acceptance = TESTS / "acceptance"
    test_text = "\n".join(p.read_text(encoding="utf-8") for p in acceptance.glob("test_*.py"))
    if test_text.strip():
        untested = [i for i in spec_ids if i.startswith("AC-") and i not in test_text]
        print(f"acceptance scenarios without a test: {untested or 'none'}")
    else:
        print("acceptance tests not present yet; skipping test coverage check")

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
