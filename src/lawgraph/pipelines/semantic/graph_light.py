"""``lawgraph semantic graph-light``: keep every judgment and paper light, without its text.

``lg_judgment_light`` holds per judgment the props the explorer reads of a neighbour, a node
of a neighbourhood or of a path; ``lg_document_light`` per paper what the signals of a dossier
read (``normalize tk-dossiers``). Those read them there instead of the props, which hold the
whole text; ``lg_instrument_names`` per instrument its title and short title, which the
laws a dossier title names are found by; ``lg_faction_votes`` every vote of a faction with
its decision's date, which the votes of a member are read from; ``lg_authored`` every paper a
member signed with its dossiers and date, which the dossiers of a member and the counts of a
cabinet are read from; ``lg_led`` every activity and case a committee leads with its date
and dossiers, which the pages of a committee are read from. Triggers on ``judgments``,
``documents``, ``cases``, ``activities``, ``instruments``, ``edges`` and ``decisions`` keep
them with every write: this step adds the rows written before them (once, after the deploy
that brought a table), and with ``--all`` keeps every row again
(after the props kept changed); ``--authored-dates`` keeps the dates of the signatures kept
before them, a slice of members at a time. Writes no node or edge: the data version stays as
it is.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any, NamedTuple

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries.committee_led import fill_led
from lawgraph.db.queries.document_light import fill_document_light
from lawgraph.db.queries.faction_votes import fill_faction_votes
from lawgraph.db.queries.instrument_names import fill_instrument_names
from lawgraph.db.queries.judgment_light import fill_judgment_light
from lawgraph.db.queries.member_authored import date_authored, fill_authored
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


class _Fill(NamedTuple):
    fill: Callable[..., int]  # ``fill(store, every=...)``: the rows it kept
    kept: str  # the log line, of the rows kept
    papers: bool = False  # every row again with --papers too


# In the order they are filled.
_FILLS = (
    _Fill(fill_judgment_light, "Kept %d judgments as neighbours."),
    _Fill(
        fill_document_light,
        "Kept %d papers light for the signals of their dossiers.",
        papers=True,
    ),
    _Fill(
        fill_instrument_names,
        "Kept the names of %d instruments for the titles of dossiers.",
    ),
    _Fill(
        fill_faction_votes, "Kept %d votes of factions for the votes of their members."
    ),
    _Fill(
        fill_authored,
        "Kept %d papers members signed for the dossiers of their members.",
    ),
    _Fill(fill_led, "Kept %d items committees lead for the pages of the committees."),
)


def add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--all",
        action="store_true",
        help="Keep every row again, not only those without (after the props kept changed).",
    )
    parser.add_argument(
        "--papers",
        action="store_true",
        help="Keep every paper again (after what is kept of a paper changed), the rest "
        "only where a row is missing.",
    )
    parser.add_argument(
        "--authored-dates",
        action="store_true",
        help="Only keep the date and capacity of the papers members signed, a slice of "
        "members (after the deploy that brought them); the last slice notes them whole.",
    )
    parser.add_argument(
        "--after", default="", help="With --authored-dates: start past this member id."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="With --authored-dates: the members of the slice (default 500).",
    )


def extra_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "every": args.all,
        "papers": args.papers,
        "authored_dates": args.authored_dates,
        "after": args.after,
        "limit": args.limit,
    }


class GraphLightSemanticPipeline(PipelineBase):
    store: GraphStore

    def __init__(
        self,
        store: GraphStore,
        *,
        every: bool = False,  # --all
        papers: bool = False,
        authored_dates: bool = False,
        after: str = "",
        limit: int = 500,
    ) -> None:
        super().__init__(store)
        self.every = every
        self.papers = papers
        self.authored_dates = authored_dates
        self.after = after
        self.limit = limit

    def run(self) -> PipelineResult:
        if self.authored_dates:
            return self._authored_dates()
        result = PipelineResult()
        for fill in _FILLS:
            kept = fill.fill(
                self.store, every=self.every or (fill.papers and self.papers)
            )
            logger.info(fill.kept, kept)
            result.updated += kept
        return result

    def _authored_dates(self) -> PipelineResult:
        last, dated = date_authored(self.store, after=self.after, limit=self.limit)
        logger.info("Kept the dates of %d papers members signed.", dated)
        if last is None:
            logger.info("Every paper members signed has its date.")
        else:
            logger.info("The last read was %s (go on with --after %s).", last, last)
        return PipelineResult(updated=dated)
