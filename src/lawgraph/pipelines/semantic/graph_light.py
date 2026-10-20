"""``lawgraph semantic graph-light``: keep every judgment and document light, without its text.

``lg_judgment_light`` holds per judgment the props the explorer reads of a neighbour, a node
of a neighbourhood or of a path; ``lg_document_light`` per document what the signals of a dossier
read (``normalize tk-dossiers``). Those read them there instead of the props, which hold the
whole text; ``lg_instrument_names`` per instrument its title and short title, which the
laws a dossier title names are found by; ``lg_faction_votes`` every vote of a faction with
its decision's date, which the votes of a member are read from; ``lg_authored`` every document a
member signed with its dossiers and date, which the dossiers of a member and the counts of a
cabinet are read from; ``lg_led`` every activity and case a committee leads with its date
and dossiers, which the pages of a committee are read from; ``lg_judgment_persons`` per
judgment the persons it names, which the search finds it by. Triggers on ``judgments``,
``documents``, ``cases``, ``activities``, ``instruments``, ``edges`` and ``decisions`` keep
them with every write: this step adds the rows written before them (once, after the deploy
that brought a table), and with ``--all`` keeps every row again (after the props kept
changed); ``--only`` names the tables (``--all --only authored,led`` after a release that
changed the date they derive). Writes no node or edge: the data version stays as it is.
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
from lawgraph.db.queries.judgment_persons import fill_judgment_persons
from lawgraph.db.queries.member_authored import fill_authored
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


class _Fill(NamedTuple):
    name: str  # as ``--only`` names it
    fill: Callable[..., int]  # ``fill(store, every=...)``: the rows it kept
    kept: str  # the log line, of the rows kept
    papers: bool = False  # every row again with --papers too


# In the order they are filled.
_FILLS = (
    _Fill("judgment-light", fill_judgment_light, "Kept %d judgments as neighbours."),
    _Fill(
        "document-light",
        fill_document_light,
        "Kept %d papers light for the signals of their dossiers.",
        papers=True,
    ),
    _Fill(
        "instrument-names",
        fill_instrument_names,
        "Kept the names of %d instruments for the titles of dossiers.",
    ),
    _Fill(
        "faction-votes",
        fill_faction_votes,
        "Kept %d votes of factions for the votes of their members.",
    ),
    _Fill(
        "authored",
        fill_authored,
        "Kept %d papers members signed for the dossiers of their members.",
    ),
    _Fill(
        "led",
        fill_led,
        "Kept %d items committees lead for the pages of the committees.",
    ),
    _Fill(
        "judgment-persons",
        fill_judgment_persons,
        "Kept the persons of %d judgments for the search.",
    ),
)


def _names(value: str) -> tuple[str, ...]:
    """The tables ``--only`` names, comma-separated, each one of ``_FILLS``."""
    names = tuple(n.strip() for n in value.split(",") if n.strip())
    known = [f.name for f in _FILLS]
    unknown = [n for n in names if n not in known]
    if unknown or not names:
        raise argparse.ArgumentTypeError(
            f"not a light table: {', '.join(unknown) or value!r} (one of {', '.join(known)})"
        )
    return names


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
        "--only",
        type=_names,
        default=(),
        help="Keep only these tables, comma-separated: "
        + ", ".join(f.name for f in _FILLS)
        + " (default: all).",
    )


def extra_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "every": args.all,
        "papers": args.papers,
        "only": args.only,
    }


class GraphLightSemanticPipeline(PipelineBase):
    store: GraphStore

    def __init__(
        self,
        store: GraphStore,
        *,
        every: bool = False,  # --all
        papers: bool = False,
        only: tuple[str, ...] = (),  # the tables of --only; empty: all
    ) -> None:
        super().__init__(store)
        self.every = every
        self.papers = papers
        self.only = only

    def run(self) -> PipelineResult:
        result = PipelineResult()
        for fill in _FILLS:
            if self.only and fill.name not in self.only:
                continue
            kept = fill.fill(
                self.store, every=self.every or (fill.papers and self.papers)
            )
            logger.info(fill.kept, kept)
            result.updated += kept
        return result
