"""``lawgraph succession-gaps``: what the transposition tables do not place. Reads only.

Of every stored table (a PDF or a table in the XML of a Kamerstuk, as ``retrieve
tk-transposition-tables`` stores them; the concordance table of an EU act), as ``semantic
tk-transposition-tables`` reads it: why it places nothing, or, per old law and new law, with
the tables between them

- the rows of each table that do not hold: a place that does not read, an article the old
  law does not have, an article or lid the new law does not have;
- the articles of the old law in force without a place in an article of the new law in any
  of the tables: no row for it, a row that places it in no article ("Besluit B2") or in a
  division of the new law only ("B6H3": the graph has no node of a division), or rows none
  of which hold; "no row" only of an old law that goes (as ``semantic
  tk-transposition-tables`` reads it) and that no table to another new law has a row for;
- what the tables say instead of a place ("vervallen", "niet overgenomen", "–", "Blijft in
  Wm"): no gap, counted per outcome.

Nothing is filled in: these are what is left to decide. Each line names where in its table
it is (the page of a PDF, the row of a table in XML), so it can be looked up. A table that
places nothing (an EU implementation table, an EU act the graph does not hold) is a note at
the end, no gap.
"""

from __future__ import annotations

from collections import Counter

from lawgraph.core.models import PipelineResult
from lawgraph.core.succession import GAP, ROW_GAPS, Gap
from lawgraph.db import GraphStore
from lawgraph.pipelines.command import command_parser, docstring_title
from lawgraph.pipelines.semantic._transposition_tables import (
    Succession,
    Table,
    read_successions,
)

LABELS = {
    "unreadable": "does not read",
    "no_old_article": "the old law has no such article",
    "no_new_article": "the new law has no such article",
    "no_lid": "the article of the new law has no such lid",
    "no_law": "no such law in the graph",
    "no_division": "the new law has no such division",
    "no_row": "no row",
    "no_article": "placed in no article",
    "in_division": "placed in a division only",
    "not_placed": "no row of it holds",
}


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(docstring_title(__doc__))
    parser.add_argument(
        "--table",
        metavar="ID",
        help="Only the tables of this source (blg-1081574, kst-34986-3, 32017R1001) and the "
        "laws they are between.",
    )
    args = parser.parse_args(argv)
    problems, successions = read_successions(GraphStore())
    gaps = 0
    for succession in successions:
        if args.table and all(t.identifier != args.table for t in succession.tables):
            continue
        for line in report(succession):
            print(line)
        gaps += len(succession.placed.gaps)
    notes = [t for t in problems if not args.table or t.identifier == args.table]
    if notes:
        print(f"Notes: {len(notes)} tables place nothing (no gaps)")
        for table in notes:
            print(f"  {problem(table)}")
    print(f"{gaps} gaps.")
    return PipelineResult()


def problem(table: Table) -> str:
    """The line of a table that places nothing."""
    return f"{table.heading}: places nothing: {table.problem}."


def report(succession: Succession) -> list[str]:
    """The lines of the report of one old law and new law."""
    placed = succession.placed
    articles = [g for g in placed.gaps if g.kind not in ROW_GAPS]
    lines = [
        f"{succession.old_law} -> {succession.new_law}",
        f"  {len({old for old, _ in placed.pairs})} articles placed in "
        f"{len({new for _, new in placed.pairs})} articles, {len(placed.gaps)} gaps"
        + (
            ""
            if succession.replaced
            else " (the old law is not replaced: no row is no gap)"
        ),
    ]
    for table in succession.tables:
        rows = [
            g
            for g in placed.gaps
            if g.kind in ROW_GAPS and g.source == table.identifier
        ]
        lines.append(f"  {table.heading}: rows that do not hold ({len(rows)})")
        lines += [f"    {_line(g)}" for g in rows]
    lines.append(f"  Articles of the old law without a place ({len(articles)})")
    lines += [f"    {_line(g, source=len(succession.tables) > 1)}" for g in articles]
    said = Counter(
        part["outcome"]
        for unplaced in placed.unplaced.values()
        for part in unplaced.parts
        if part["outcome"] != GAP
    )
    if said:
        lines.append(
            "  What the tables say instead of a place (no gap): "
            + ", ".join(f"{outcome} {count}" for outcome, count in sorted(said.items()))
        )
    return [*lines, ""]


def _line(gap: Gap, *, source: bool = False) -> str:
    where = " ".join(p for p in (gap.source if source else "", gap.where) if p)
    where = f"{where}: " if where else ""
    part = f" {gap.part}" if gap.part else ""
    text = f": {gap.text}" if gap.text else ""
    return f"{where}art. {gap.old_article}{part}{text} [{LABELS[gap.kind]}]"
