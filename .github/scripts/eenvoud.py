"""Measure what makes the code harder than it needs to be and hold it to eenvoud-budget.json.

A ratchet: a measured value may not rise above its budget, and a value that fell must be
written down (``--write``), so the budget follows it. Raising a budget is a hand edit of
eenvoud-budget.json in the pull request, where the diff shows it (``--raised REF`` lists
those raises). Only the standard library: CI runs it without the dependencies.

What it measures:
- the calls of the four cache APIs of ``db/version_cache.py`` (``cached``, ``lasting``,
  ``cached_rows``, ``lasting_rows``), the parts of the warm-up (``Part(...)``) and its hourly
  parts (``_due(...)``) in ``api/warm.py``, and the count functions of ``db/queries`` (a name
  with ``count`` or ``total``): each a second way to make an answer fast or to count;
- the lines of each file of ``src/`` above the line limit.

The length of a function is ruff's (PLR0915, pyproject.toml), its branches C901.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUDGET = ROOT / "eenvoud-budget.json"
SRC = ROOT / "src" / "lawgraph"
CACHE_APIS = ("cached", "lasting", "cached_rows", "lasting_rows")
MAPS = ("lines_per_file",)


def _called(tree: ast.AST, name: str) -> int:
    def name_of(func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        return func.attr if isinstance(func, ast.Attribute) else None

    return sum(
        isinstance(node, ast.Call) and name_of(node.func) == name
        for node in ast.walk(tree)
    )


def _function_names(tree: ast.AST) -> list[str]:
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def measure(limits: dict[str, int]) -> dict:
    counts = dict.fromkeys(
        (*CACHE_APIS, "warm_parts", "warm_hourly", "count_functions"), 0
    )
    lines: dict[str, int] = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text()
        tree = ast.parse(text)
        if rel != "src/lawgraph/db/version_cache.py":
            for api in CACHE_APIS:
                counts[api] += _called(tree, api)
        if rel == "src/lawgraph/api/warm.py":
            counts["warm_parts"] = _called(tree, "Part")
            counts["warm_hourly"] = _called(tree, "_due")
        if rel.startswith("src/lawgraph/db/queries/"):
            counts["count_functions"] += sum(
                "count" in name or "total" in name for name in _function_names(tree)
            )
        if (n := text.count("\n")) > limits["lines_per_file"]:
            lines[rel] = n
    return {"counts": counts, "lines_per_file": lines}


def compare(budget: dict, measured: dict) -> tuple[list[str], list[str]]:
    """What rose above the budget, and what fell below it."""
    rose, fell = [], []
    sections = [("counts", budget["counts"], measured["counts"])]
    sections += [(m, budget[m], measured[m]) for m in MAPS]
    for section, allowed, now in sections:
        for key in sorted(set(allowed) | set(now)):
            old, new = allowed.get(key), now.get(key, 0)
            line = f"{section} {key}: {old if old is not None else '-'} -> {new}"
            if old is None or new > old:
                rose.append(line)
            elif new < old:
                fell.append(line)
    return rose, fell


def raised(ref: str) -> list[str]:
    """The values eenvoud-budget.json raises against its version at *ref*."""
    shown = subprocess.run(
        ["git", "show", f"{ref}:eenvoud-budget.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if shown.returncode != 0:
        return []
    base = json.loads(shown.stdout)
    rose, _ = compare(base, json.loads(BUDGET.read_text()))
    return rose


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="lower the budget")
    parser.add_argument("--raised", metavar="REF", help="list raises of the budget")
    args = parser.parse_args()
    if args.raised:
        for line in raised(args.raised):
            print(f"::warning title=eenvoud-toets::budget omhoog: {line}")
        return 0
    budget = json.loads(BUDGET.read_text())
    measured = measure(budget["limits"])
    rose, fell = compare(budget, measured)
    for line in rose:
        print(f"gestegen: {line}")
    if rose:
        print(
            "eenvoud: boven het budget. Maak het eenvoudiger, of hoog eenvoud-budget.json"
            " met de hand op (zichtbaar in de PR)."
        )
        return 1
    if args.write:
        BUDGET.write_text(json.dumps(budget | measured, indent=2) + "\n")
        print(f"eenvoud: budget bijgewerkt ({len(fell)} omlaag)")
        return 0
    for line in fell:
        print(f"gedaald: {line}")
    if fell:
        print("eenvoud: zet het budget omlaag met .github/scripts/eenvoud.sh --write")
        return 1
    print(f"eenvoud: binnen het budget {json.dumps(measured['counts'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
