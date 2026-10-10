"""``lawgraph semantic graph-light``: keep every judgment and paper light, without its text.

``lg_judgment_light`` holds per judgment the props the explorer reads of a neighbour, a node
of a neighbourhood or of a path; ``lg_document_light`` per paper what the signals of a dossier
read (``normalize tk-dossiers``). Those read them there instead of the props, which hold the
whole text; ``lg_instrument_names`` per instrument its title and short title, which the
laws a dossier title names are found by; ``lg_faction_votes`` every vote of a faction with
its decision's date, which the votes of a member are read from; ``lg_authored`` every paper a
member signed with its dossiers and date, which the dossiers of a member and the counts of a
cabinet are read from. Triggers on ``judgments``, ``documents``, ``cases``, ``instruments``,
``edges`` and ``decisions`` keep them with every write: this step adds the rows written before
them (once, after the deploy that brought a table), and with ``--all`` keeps every row again
(after the props kept changed); ``--authored-dates`` keeps the dates of the signatures kept
before them, a slice of members at a time. Writes no node or edge: the data version stays as
it is.
"""

from __future__ import annotations

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries.document_light import fill_document_light
from lawgraph.db.queries.faction_votes import fill_faction_votes
from lawgraph.db.queries.instrument_names import fill_instrument_names
from lawgraph.db.queries.judgment_light import fill_judgment_light
from lawgraph.db.queries.member_authored import date_authored, fill_authored
from lawgraph.pipelines.command import command_parser

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description=(
            "Keep every judgment, paper and instrument light, without its text, for those written "
            "before the triggers that keep them."
        )
    )
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
    args = parser.parse_args(argv)
    store = GraphStore()
    if args.authored_dates:
        return _authored_dates(store, args.after, args.limit)
    judgments = fill_judgment_light(store, every=args.all)
    logger.info("Kept %d judgments as neighbours.", judgments)
    documents = fill_document_light(store, every=args.all or args.papers)
    logger.info("Kept %d papers light for the signals of their dossiers.", documents)
    instruments = fill_instrument_names(store, every=args.all)
    logger.info(
        "Kept the names of %d instruments for the titles of dossiers.", instruments
    )
    votes = fill_faction_votes(store, every=args.all)
    logger.info("Kept %d votes of factions for the votes of their members.", votes)
    signed = fill_authored(store, every=args.all)
    logger.info(
        "Kept %d papers members signed for the dossiers of their members.", signed
    )
    return PipelineResult(updated=judgments + documents + instruments + votes + signed)


def _authored_dates(store: GraphStore, after: str, limit: int) -> PipelineResult:
    last, dated = date_authored(store, after=after, limit=limit)
    logger.info("Kept the dates of %d papers members signed.", dated)
    if last is None:
        logger.info("Every paper members signed has its date.")
    else:
        logger.info("The last read was %s (go on with --after %s).", last, last)
    return PipelineResult(updated=dated)
