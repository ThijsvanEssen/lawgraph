"""``lawgraph verify cabinets``: does every cabinet meet the rules of its seats and phases?
Reads only.

One row per cabinet (``core.cabinet_checks.cabinet_row``): its posts, seats, the seats with
a gap of more than two weeks and those with an overlap that remained, the stand-ins, the
dates the rules set, the double listings merged, the posts with and without a party, the
holders that are members of their own, the phases and ``demissionary_from``, and whether
``in_functie`` begins on the cabinet's first day. Then the labels of the phases with their
kind, and every rule a cabinet breaks (``core.cabinet_checks.violations``); a broken rule
fails the command.
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from lawgraph.core.cabinet_checks import cabinet_row, violations
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore
from lawgraph.db.queries.cabinets import cabinets_with_posts

_COLUMNS = (
    ("key", 22),
    ("from_date", 11),
    ("source", 13),
    ("posts", 5),
    ("seats", 5),
    ("gaps", 4),
    ("overlaps", 8),
    ("acting", 6),
    ("corrected", 9),
    ("clipped", 7),
    ("double", 6),
    ("party", 5),
    ("no_party", 8),
    ("own", 3),
    ("phases", 6),
    ("demissionary_from", 17),
    ("starts_agree", 12),
)


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("what", choices=["cabinets"], help="What to verify.")
    parser.parse_args(argv)
    result = PipelineResult()
    for problem in verify_cabinets(ArangoStore()):
        result.add_error(problem)
    return result


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if value is True:
        return "yes"
    if value is False:
        return "NO"
    return str(value)


def verify_cabinets(store: ArangoStore) -> list[str]:
    """Print the report; the rules broken."""
    rows = cabinets_with_posts(store)
    problems: list[str] = []
    labels: Counter[tuple[str | None, str]] = Counter()
    print("  ".join(name.ljust(width) for name, width in _COLUMNS))
    for row in rows:
        cabinet = {
            "key": row["key"],
            **row["props"],
            "source": row["props"].get("origin"),
        }
        line = cabinet_row(cabinet, row["posts"])
        print("  ".join(_cell(line[name]).ljust(width) for name, width in _COLUMNS))
        problems += violations(cabinet, row["posts"])
        for phase in cabinet.get("phases") or []:
            label = phase["label"] or ""
            word = label.split(":")[0] if ":" in label[:60] else "(a sentence)"
            labels[(phase["kind"], word)] += 1
    print(f"\n{len(rows)} cabinets.\n\nPhase labels:")
    for (kind, word), n in sorted(
        labels.items(), key=lambda x: (str(x[0][0]), x[0][1])
    ):
        print(f"  {str(kind):<20} {n:>3}  {word}")
    print(f"\n{len(problems)} rules broken.")
    for problem in problems:
        print(f"  {problem}")
    return problems
