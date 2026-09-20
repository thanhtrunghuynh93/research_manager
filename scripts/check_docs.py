#!/usr/bin/env python3
"""The documentation claims that a machine can check.

`check_traceability.py` already asserts that every requirement ID appears in the architecture's
traceability table. That catches an unmapped requirement and nothing else — in particular it passes
while a mapped requirement is only half-built, because it compares two documents rather than a
document against the tree.

The drift it missed came in two shapes, and both are mechanical:

  1. A path named in a document does not exist, or exists and is named nowhere. `repo_layout.md`
     listed four API routers that had never been written and omitted the one that had.
  2. A number or a version written into prose. "Fifteen migrations" was wrong by six, and
     `implementation_status.md` called itself a companion to a requirements version two releases old.

Everything here is derived from the tree, in the spirit of `use_cases.md` §9: an inventory that is
recomputed is one that cannot quietly go stale. Nothing here checks prose that a human has to judge,
because a check people learn to force through is worse than no check at all.

Exit code 1 if any check fails.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
REPO_LAYOUT = DOCS / "repo_layout.md"
ADR_INDEX = DOCS / "adr" / "README.md"
OPENAPI = DOCS / "api" / "openapi.json"
STATUS = DOCS / "implementation_status.md"

# A tree line: indentation drawn with box characters, then the name, then an optional annotation
# separated by two or more spaces.
TREE_ENTRY = re.compile(r"^(?P<indent>[\s│├└─|`+\\-]*)(?P<name>[\w.@-]+/?)(?:\s{2,}.*)?$")
# "(optional)" and "(planned)" mark an entry that describes intent rather than the tree.
EXEMPT = re.compile(r"\((optional|planned|generated)\)", re.I)


def _fenced_blocks(text: str) -> list[list[str]]:
    blocks, current, inside = [], [], False
    for line in text.splitlines():
        if line.startswith("```"):
            if inside:
                blocks.append(current)
                current = []
            inside = not inside
            continue
        if inside:
            current.append(line)
    return blocks


def _depth(indent: str) -> int:
    """Four display columns per level, which is how these trees are drawn."""
    return len(indent.expandtabs(4)) // 4


def _paths_in_tree(block: list[str]) -> list[tuple[str, int]]:
    """Rebuild each full path from the indentation, with its line number within the block."""
    found: list[tuple[str, int]] = []
    # A sentinel for the block's own root line, which names the base directory rather than an entry
    # inside it. Without it the first depth-1 entry becomes the parent of its own siblings.
    stack: list[str] = ["<root>"]
    for number, line in enumerate(block[1:], start=2):
        if not line.strip() or EXEMPT.search(line):
            continue
        match = TREE_ENTRY.match(line.rstrip())
        if match is None:
            continue
        name = match["name"]
        if name in {"...", "…"}:
            continue
        level = max(1, _depth(match["indent"]))
        del stack[level:]
        stack.append(name.rstrip("/"))
        parts = stack[1:]
        if not parts:
            continue
        found.append(("/".join(parts), number))
    return found


def check_tree_paths_exist() -> list[str]:
    """Every path a tree block names must be on disk."""
    problems: list[str] = []
    text = REPO_LAYOUT.read_text(encoding="utf-8")
    for block in _fenced_blocks(text):
        if not block or not block[0].rstrip().endswith("/"):
            continue
        root_name = block[0].strip().rstrip("/")
        base = ROOT if root_name == "research_management" else ROOT / root_name
        for relative, _ in _paths_in_tree(block):
            if not (base / relative).exists():
                problems.append(f"repo_layout.md names {root_name}/{relative}, which does not exist")
    return problems


def check_high_churn_paths_are_named() -> list[str]:
    """The reverse: the directories that change most must not gain a file nobody documented."""
    text = REPO_LAYOUT.read_text(encoding="utf-8")
    problems: list[str] = []
    wanted: list[Path] = [
        *(ROOT / "backend/app/api/v1").glob("*.py"),
        *[p for p in (ROOT / "backend/app").iterdir() if p.is_dir() and not p.name.startswith("_")],
        *[p for p in (ROOT / "frontend/src/features").iterdir() if p.is_dir()],
        *(ROOT / "frontend/src/hooks").glob("*.ts"),
        *[p for p in (ROOT / "frontend/src/locales").iterdir() if p.is_dir()],
    ]
    for path in sorted(wanted):
        if path.name == "__init__.py":
            continue
        if path.name not in text and path.stem not in text:
            problems.append(f"{path.relative_to(ROOT)} exists and repo_layout.md never names it")

    index = ADR_INDEX.read_text(encoding="utf-8")
    for adr in sorted((DOCS / "adr").glob("[0-9]*.md")):
        if adr.name not in index:
            problems.append(f"{adr.name} exists and docs/adr/README.md never lists it")
    return problems


def check_cited_api_paths_exist() -> list[str]:
    """An `/api/...` path written into a document must be one the application serves.

    Every one of the four paths architecture.md cited was wrong — three in shape and all four in
    version prefix — and no test could notice, because prose is not called.
    """
    served = set(json.loads(OPENAPI.read_text(encoding="utf-8"))["paths"])
    # Registered with include_in_schema=False, so they are absent from the export by intent.
    served |= {"/api/metrics", "/api/v1/webhooks/github"}
    templated = {re.sub(r"\{[^}]+\}", "{}", path) for path in served}

    problems: list[str] = []
    cited = re.compile(r"`(?:GET|POST|PUT|PATCH|DELETE)\s+(/api/[^`]*)`")
    for document in sorted(DOCS.rglob("*.md")):
        for line_number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
            for path in cited.findall(line):
                path = path.split("?")[0].rstrip("/")
                if re.sub(r"\{[^}]+\}", "{}", path) not in templated:
                    where = document.relative_to(ROOT)
                    problems.append(f"{where}:{line_number} cites {path}, which the API does not serve")
    return problems


def check_counts() -> list[str]:
    """The counts table in implementation_status.md, against the tree it describes."""
    text = STATUS.read_text(encoding="utf-8")
    actual = {
        "Alembic migrations": len(list((ROOT / "backend/alembic/versions").glob("*.py"))),
        "ADRs": len(list((DOCS / "adr").glob("[0-9]*.md"))),
        "Acceptance scenarios with a test": len(
            list((ROOT / "backend/tests/acceptance").glob("test_ac_*.py"))
        ),
        # The row reads "97 (95 in the schema, 2 include_in_schema=False)"; the leading number is
        # the one checked, and the hidden two are counted from the routers rather than the spec,
        # which by definition cannot see them.
        "`/api/v1` endpoints": _api_inventory()[0]
        + len(
            [
                line
                for source in (ROOT / "backend/app/api").rglob("*.py")
                for line in source.read_text(encoding="utf-8").splitlines()
                if "include_in_schema=False" in line
            ]
        ),
    }
    problems: list[str] = []
    for label, count in actual.items():
        row = re.search(rf"^\|\s*{re.escape(label)}\s*\|\s*(\d+)", text, re.M)
        if row is None:
            problems.append(f"implementation_status.md has no counts row for {label!r}")
        elif int(row.group(1)) != count:
            problems.append(
                f"implementation_status.md says {row.group(1)} for {label!r}; the tree has {count}"
            )
    return problems


def check_version_cross_references() -> list[str]:
    """"companion to X.md vN.M" must agree with X.md's own version line."""
    problems: list[str] = []
    reference = re.compile(r"\[([\w.]+\.md)\]\([^)]*\)\s+v(\d+\.\d+)")
    for document in sorted(DOCS.glob("*.md")):
        text = document.read_text(encoding="utf-8")
        for name, claimed in reference.findall(text):
            target = DOCS / name
            if not target.exists():
                continue
            declared = re.search(r"^Version\s+(\d+\.\d+)", target.read_text(encoding="utf-8"), re.M)
            if declared and declared.group(1) != claimed:
                problems.append(
                    f"{document.name} calls {name} v{claimed}; {name} says v{declared.group(1)}"
                )
    return problems


USE_CASES = DOCS / "use_cases.md"
# `POST /users/{id}/{action}` is written as one call site standing for three routes.
DYNAMIC_CALLS = {
    ("/api/v1/users/{x}/{x}", "post"): (
        ("/api/v1/users/{user_id}/deactivate", "post"),
        ("/api/v1/users/{user_id}/reactivate", "post"),
        ("/api/v1/users/{user_id}/remove", "post"),
    )
}


def _api_inventory() -> tuple[int, int, list[str]]:
    """How many `/api/v1` endpoints there are, and how many a screen calls.

    Both counts are path-and-method pairs, which use_cases.md v0.12 did not do: it counted routes
    with one command and callers with another, so "98 endpoints, 50 of them called by a screen"
    compared two units and could not be checked against anything.

    The two exclusions carry the argument. The generated OpenAPI types name every route whether or
    not a screen calls it, and the test files mock endpoints the app has no screen for — counting
    either reports coverage the product does not have.
    """
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    methods = ("get", "post", "put", "patch", "delete")
    served = {
        (re.sub(r"\{[^}]*\}", "{x}", path), method): (path, method)
        for path, item in spec["paths"].items()
        for method in item
        if method in methods and path.startswith("/api/v1")
    }

    hits: set[tuple[str, str]] = set()
    unresolved: list[str] = []
    call = re.compile(r"api\.(get|post|put|patch|delete)\s*(?:<[^>]*>)?\s*\(\s*[`\"']([^`\"']*)")
    for source in sorted((ROOT / "frontend/src").rglob("*.ts*")):
        text = str(source)
        if "generated" in text or ".test." in text:
            continue
        for method, raw in call.findall(source.read_text(encoding="utf-8")):
            # Substitute simple `${id}` params first; anything left is an expression (a ternary
            # building a query string), and the path ends where it begins.
            path = re.sub(r"\$\{[^{}]*\}", "{x}", raw)
            path = path.split("${")[0].split("?")[0].rstrip("/")
            if not path.startswith("/api/v1"):
                continue
            key = (path, method)
            if key in DYNAMIC_CALLS:
                hits.update(DYNAMIC_CALLS[key])
            elif key in served:
                hits.add(served[key])
            else:
                unresolved.append(
                    f"{source.relative_to(ROOT)} calls {method.upper()} {path}, "
                    "which the API does not serve"
                )
    return len(served), len(hits), unresolved


def check_api_inventory() -> list[str]:
    """use_cases.md's headline count, against the spec and the screens that call it."""
    served, called, problems = _api_inventory()
    text = USE_CASES.read_text(encoding="utf-8")
    claim = re.search(
        r"\*\*As of this version: (\d+) endpoints, (\d+) of them called by a screen", text
    )
    if claim is None:
        return [*problems, "use_cases.md has no 'As of this version: N endpoints' line"]
    if int(claim.group(1)) != served:
        problems.append(f"use_cases.md says {claim.group(1)} endpoints; the spec serves {served}")
    if int(claim.group(2)) != called:
        problems.append(
            f"use_cases.md says {claim.group(2)} called by a screen; the tree calls {called}"
        )
    return problems


CHECKS = (
    ("tree paths exist", check_tree_paths_exist),
    ("high-churn paths are documented", check_high_churn_paths_are_named),
    ("cited API paths are served", check_cited_api_paths_exist),
    ("counted values match the tree", check_counts),
    ("the API inventory matches the tree", check_api_inventory),
    ("version cross-references agree", check_version_cross_references),
)


def main() -> int:
    failed = 0
    for label, check in CHECKS:
        problems = check()
        if problems:
            failed += 1
            print(f"FAIL {label}:")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"ok   {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
