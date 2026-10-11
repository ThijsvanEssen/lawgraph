"""``lawgraph search-candidates``: the hits of the words searched most, ready to rank
(``queries/search_candidates.py``).

    lawgraph search-candidates [--all]

Reads the hits of each word again where its table changed since they were read (or the
search they were read for); ``--all`` every word again. ``scripts/poll.sh`` runs it after
each poll, ``scripts/daily.sh`` and ``scripts/weekly.sh`` at their end.
"""

from __future__ import annotations

import datetime as dt

from lawgraph.config.settings import SEARCH_STATS_DIR
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries import search_candidates
from lawgraph.pipelines.command import command_parser, docstring_title


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(docstring_title(__doc__))
    parser.add_argument(
        "--all",
        action="store_true",
        help="Read the hits of every word again, also where they are current.",
    )
    args = parser.parse_args(argv)
    words = search_candidates.searched_words(SEARCH_STATS_DIR, dt.date.today())
    store = GraphStore()
    result = search_candidates.write(store, words, every=args.all)
    for table, written in result.written.items():
        hits = ", ".join(f"{word} {n}" for word, n in written.items())
        print(
            f"{table}: {len(written)} words read again{f' ({hits})' if hits else ''},"
            f" {result.current[table]} current."
        )
    print(f"{len(words)} words searched most; {result.dropped} no longer kept.")
    return PipelineResult(updated=sum(len(w) for w in result.written.values()))
