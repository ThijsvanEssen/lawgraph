"""``lawgraph search-stats``: the terms searched on ``/api/search``.

Counted without who asked (``core/search_stats.py``, ``LAWGRAPH_SEARCH_STATS_DIR``).

    lawgraph search-stats [--days 7] [--top 50]     the terms asked most in those days
    lawgraph search-stats prune [--keep-days 7] [--min-count 5]

``prune`` moves every day file older than ``--keep-days`` into the file of its month, with
only the terms asked at least ``--min-count`` times in that day and the days kept after it.
``scripts/daily.sh`` runs it.
"""

from __future__ import annotations

import datetime as dt

from lawgraph.config.settings import SEARCH_STATS_DIR
from lawgraph.core import search_stats
from lawgraph.core.models import PipelineResult
from lawgraph.pipelines.command import command_parser, docstring_title

# The terms listed when no --top is given.
TOP_TERMS = 50


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(docstring_title(__doc__))
    sub = parser.add_subparsers(dest="action")
    parser.add_argument(
        "--days",
        type=int,
        default=search_stats.KEEP_DAYS,
        metavar="N",
        help="The last N days. Default: %(default)s.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=TOP_TERMS,
        metavar="N",
        help="The N terms asked most. Default: %(default)s.",
    )
    pruned = sub.add_parser("prune", help="Fold the old days into their month.")
    pruned.add_argument(
        "--keep-days",
        type=int,
        default=search_stats.KEEP_DAYS,
        metavar="N",
        help="The days kept as they are. Default: %(default)s.",
    )
    pruned.add_argument(
        "--min-count",
        type=int,
        default=search_stats.MIN_COUNT,
        metavar="N",
        help="A term of a folded day is kept when asked this often. Default: %(default)s.",
    )
    args = parser.parse_args(argv)

    today = dt.date.today()
    if args.action == "prune":
        moved = search_stats.prune(
            SEARCH_STATS_DIR, today, keep_days=args.keep_days, min_count=args.min_count
        )
        print(f"{len(moved)} days folded into their month ({SEARCH_STATS_DIR}).")
        return PipelineResult(updated=len(moved))
    counts = search_stats.totals(SEARCH_STATS_DIR, today, args.days)
    for term, n in counts.most_common(args.top):
        print(f"{n:6d}  {term}")
    if not counts:
        print(f"No terms counted in the last {args.days} days ({SEARCH_STATS_DIR}).")
    return PipelineResult()
