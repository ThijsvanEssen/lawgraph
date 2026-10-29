"""``lawgraph prewarm``: what the search reads, read into memory (``queries/search/prewarm.py``).

    lawgraph prewarm [--heaps articles ...] [--heap-mb 2048]

The search indexes into the buffers of PostgreSQL, the heap and TOAST of ``--heaps`` into
the cache of the operating system. ``scripts/daily.sh`` runs it last, after it gave the
lock up: it only reads.
"""

from __future__ import annotations

import logging

from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries.search import prewarm as search_prewarm
from lawgraph.pipelines.command import command_parser, docstring_title

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(docstring_title(__doc__))
    parser.add_argument(
        "--heaps",
        nargs="*",
        default=list(search_prewarm.HEAPS),
        help="The tables whose heap and TOAST are read too (default: %(default)s).",
    )
    parser.add_argument(
        "--heap-mb",
        type=int,
        default=search_prewarm.HEAP_MB,
        help="The most of those heaps read, in MB (default: %(default)s).",
    )
    args = parser.parse_args(argv)
    warmed = search_prewarm.prewarm(GraphStore(), tuple(args.heaps), args.heap_mb)
    for w in warmed:
        if w.skipped:
            logger.info("%s (%s): skipped, it does not fit.", w.relation, w.mode)
        else:
            logger.info(
                "%s (%s): %d MB in %.1f s.",
                w.relation,
                w.mode,
                w.blocks * 8 // 1024,
                w.seconds,
            )
    read = [w for w in warmed if not w.skipped]
    mb = sum(w.blocks for w in read) * 8 // 1024
    print(
        f"Read {len(read)} relations ({mb} MB) in {sum(w.seconds for w in read):.1f} s;"
        f" {len(warmed) - len(read)} skipped."
    )
    return PipelineResult(updated=len(read))
