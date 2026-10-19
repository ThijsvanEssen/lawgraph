"""``lawgraph succession-gaps``: what the transposition tables do not place. Reads only.

Of every stored table (``retrieve tk-transposition-tables``), as ``semantic
tk-transposition-tables`` reads it: why it places nothing, or

- the rows that do not hold: a place that does not read, an article the old law does not
  have, an article or lid the new law does not have;
- the articles of the old law in force without a place in an article of the new law: no row
  for it, a row that places it in no article ("vervallen", "Besluit B2"), or rows none of
  which hold.

Nothing is filled in: these are what is left to decide. Each line names the page of the
table, so it can be looked up.
"""

from __future__ import annotations

from lawgraph.core.models import PipelineResult
from lawgraph.core.succession import ROW_GAPS, Gap
from lawgraph.db import GraphStore
from lawgraph.pipelines.command import command_parser, docstring_title
from lawgraph.pipelines.semantic._transposition_tables import TableResult, read_tables

LABELS = {
    "unreadable": "does not read",
    "no_old_article": "the old law has no such article",
    "no_new_article": "the new law has no such article",
    "no_lid": "the article of the new law has no such lid",
    "no_row": "no row",
    "no_article": "placed in no article",
    "not_placed": "no row of it holds",
}


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(docstring_title(__doc__))
    parser.add_argument(
        "--table",
        metavar="ID",
        help="Only this table (its identifier: blg-1081574).",
    )
    args = parser.parse_args(argv)
    gaps = 0
    for table in read_tables(GraphStore()):
        if args.table and table.identifier != args.table:
            continue
        for line in report(table):
            print(line)
        gaps += len(table.placed.gaps) if table.placed else 0
    print(f"{gaps} gaps.")
    return PipelineResult()


def report(table: TableResult) -> list[str]:
    """The lines of the report of one table."""
    head = f"{table.identifier} (dossier {table.dossier})"
    if table.placed is None:
        return [f"{head}: places nothing: {table.problem}.", ""]
    placed = table.placed
    rows = [g for g in placed.gaps if g.kind in ROW_GAPS]
    articles = [g for g in placed.gaps if g.kind not in ROW_GAPS]
    lines = [
        f"{head}: {table.old_law} -> {table.new_law}",
        f"  {len({old for old, _ in placed.pairs})} articles placed in "
        f"{len({new for _, new in placed.pairs})} articles, {len(placed.gaps)} gaps",
        f"  Rows that do not hold ({len(rows)})",
    ]
    lines += [f"    {_line(g)}" for g in rows]
    lines.append(f"  Articles of the old law without a place ({len(articles)})")
    lines += [f"    {_line(g)}" for g in articles]
    return [*lines, ""]


def _line(gap: Gap) -> str:
    where = f"{gap.where}: " if gap.where else ""
    part = f" {gap.part}" if gap.part else ""
    text = f": {gap.text}" if gap.text else ""
    return f"{where}art. {gap.old_article}{part}{text} [{LABELS[gap.kind]}]"
