"""``lawgraph semantic graph-light``: keep every judgment as a neighbour, without its text.

``lg_judgment_light`` holds per judgment the props the explorer reads of a neighbour, a node
of a neighbourhood or of a path; those routes read them there instead of the props of the
judgment, which hold its whole text. Triggers on ``judgments`` keep it with every write: this
step adds the judgments written before them (once, after the deploy that brought the table),
and with ``--all`` keeps every judgment again (after the props kept changed). Writes no node
or edge: the data version stays as it is.
"""

from __future__ import annotations

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries.judgment_light import fill_judgment_light
from lawgraph.pipelines.command import command_parser

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description=(
            "Keep every judgment as a neighbour without its text, for the judgments written "
            "before the triggers that keep it."
        )
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Keep every judgment again, not only those without (after the props changed).",
    )
    args = parser.parse_args(argv)
    kept = fill_judgment_light(GraphStore(), every=args.all)
    logger.info("Kept %d judgments as neighbours.", kept)
    return PipelineResult(updated=kept)
