"""``lawgraph feed-events``: the events of the feed into ``lg_feed_events``, which ``GET
/api/feed/periods`` counts.

    lawgraph feed-events [--days N]

Without ``--days`` every event, into a new table that then takes the place of the old one
(``scripts/daily.sh``, after the semantic phase); with it the events of the last *N* days
again, in place (``scripts/poll.sh``, after each poll).
"""

from __future__ import annotations

import datetime as dt

from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries import feed_events
from lawgraph.pipelines.command import command_parser, docstring_title


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(docstring_title(__doc__))
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Write again only the events of the last N days (default: all).",
    )
    args = parser.parse_args(argv)
    store = GraphStore()
    if args.days is None:
        written = feed_events.write_all(store)
        print(f"Wrote {written} events of the feed.")
    else:
        since = (dt.date.today() - dt.timedelta(days=args.days)).isoformat()
        written = feed_events.write_since(store, since)
        print(f"Wrote {written} events of the feed since {since}.")
    return PipelineResult(updated=written)
