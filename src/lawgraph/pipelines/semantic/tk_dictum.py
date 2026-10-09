"""``lawgraph semantic tk-dictum``: the dictum of every motion with text, for those normalized
before ``normalize tk-content`` kept it.

``normalize tk-content`` keeps the dictum of a motion (``core/motion_dictum.py``: what it
asks or says, "verzoekt de regering …") when it reads its text; this step adds it to the
motions whose text was read before, a batch at a time, writing ``dictum`` alone. With
``--all`` it reads every motion again (after the rule changed). The trigger on ``documents``
keeps ``lg_document_light`` with it, which the lists of votes read.
"""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_DOCUMENTS
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.core.motion_dictum import read_dictum
from lawgraph.db import GraphStore, NodeWriter
from lawgraph.db.queries.motion_dictum import motions_with_text
from lawgraph.pipelines.command import command_parser

logger = get_logger(__name__)


def run(store: GraphStore, every: bool = False) -> int:
    """Keep the dictum of the motions with text (of every one with *every*); how many were
    read. A motion without the form of one (no closing formula) keeps ``dictum`` null."""
    after, read, found = "", 0, 0
    while True:
        batch = motions_with_text(store, after, every)
        if not batch:
            break
        nodes = []
        for row in batch:
            dictum = read_dictum(row["text"])
            found += dictum is not None
            nodes.append(
                Node(
                    collection=COLLECTION_DOCUMENTS,
                    type=NodeType.DOCUMENT,
                    key=row["key"],
                    labels=[],
                    props={"dictum": dictum},
                    _skip_validation=True,
                )
            )
        with NodeWriter(store) as writer:
            writer.add_all(nodes)
        after, read = batch[-1]["id"], read + len(batch)
        logger.info("Read %d motions: %d with a dictum.", read, found)
    logger.info("Motions read: %d, %d with a dictum.", read, found)
    return read


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description=(
            "Keep the dictum of every motion with text (what it asks or says), for those "
            "normalized before normalize tk-content kept it."
        )
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Every motion with text again, not only those without a dictum.",
    )
    args = parser.parse_args(argv)
    return PipelineResult(updated=run(GraphStore(), every=args.all))
