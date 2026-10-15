"""``lawgraph built-beforehand``: the SQL that builds the indexes of the large tables a
release adds, before its deploy. Reads nothing.

``ensure_schema`` creates what is missing at the start of the API, in one transaction that
blocks the table; an index of a large table is built beforehand by hand with the same name,
and the start then finds it (``schema.built_beforehand_sql``). A CONCURRENTLY that failed
leaves an invalid index of that name, which ``IF NOT EXISTS`` then skips: drop it with ``DROP
INDEX CONCURRENTLY`` and build it again. An index on an expression has statistics of its own
that only ``ANALYZE`` gathers; until then the planner guesses the values of the expression
and may not use it.
"""

from __future__ import annotations

from lawgraph.core.models import PipelineResult
from lawgraph.db.schema import built_beforehand_sql
from lawgraph.pipelines.command import command_parser, docstring_title


def main(argv: list[str] | None = None) -> PipelineResult:
    command_parser(docstring_title(__doc__)).parse_args(argv)
    for line in built_beforehand_sql():
        print(line)
    return PipelineResult()
