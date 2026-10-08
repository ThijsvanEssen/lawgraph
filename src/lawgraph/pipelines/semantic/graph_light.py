"""``lawgraph semantic graph-light``: keep every judgment and paper light, without its text.

``lg_judgment_light`` holds per judgment the props the explorer reads of a neighbour, a node
of a neighbourhood or of a path; ``lg_document_light`` per paper what the signals of a dossier
read (``normalize tk-dossiers``). Those read them there instead of the props, which hold the
whole text. Triggers on ``judgments`` and ``documents`` keep them with every write: this step
adds the rows written before them (once, after the deploy that brought a table), and with
``--all`` keeps every row again (after the props kept changed). Writes no node or edge: the
data version stays as it is.
"""

from __future__ import annotations

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries.document_light import fill_document_light
from lawgraph.db.queries.judgment_light import fill_judgment_light
from lawgraph.pipelines.command import command_parser

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description=(
            "Keep every judgment and paper light, without its text, for those written "
            "before the triggers that keep them."
        )
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Keep every row again, not only those without (after the props kept changed).",
    )
    args = parser.parse_args(argv)
    store = GraphStore()
    judgments = fill_judgment_light(store, every=args.all)
    logger.info("Kept %d judgments as neighbours.", judgments)
    documents = fill_document_light(store, every=args.all)
    logger.info("Kept %d papers light for the signals of their dossiers.", documents)
    return PipelineResult(updated=judgments + documents)
