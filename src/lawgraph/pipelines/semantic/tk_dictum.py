"""``lawgraph semantic tk-dictum``: the dictum of every motion and the explanation of every
amendment with text, for those normalized before ``normalize tk-content`` kept them.

``normalize tk-content`` keeps the dictum of a motion (``core/motion_dictum.py``: what it
asks or says, "verzoekt de regering …") and the explanation of an amendment
(``core/amendment_explanation.py``: the opening of its Toelichting) when it reads its text;
this step adds them to the documents whose text was read before, a batch at a time, writing
``dictum`` or ``explanation`` alone. With ``--all`` it reads every motion and amendment again
(after a rule changed). The trigger on ``documents`` keeps ``lg_document_light`` with them,
which the lists of votes and of documents read.
"""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_DOCUMENTS
from lawgraph.core.amendment_explanation import read_explanation
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.motion_dictum import read_dictum
from lawgraph.db import GraphStore, NodeWriter
from lawgraph.db.queries.motion_dictum import documents_with_text
from lawgraph.pipelines.command import command_parser

logger = get_logger(__name__)


def run(store: GraphStore, every: bool = False) -> int:
    """Keep the dictum of the motions and the explanation of the amendments with text (of
    every one with *every*); how many were read. A document without the form of one (no closing
    formula, no Toelichting) keeps it null."""
    after, read, found = "", 0, 0
    while True:
        batch = documents_with_text(store, after, every)
        if not batch:
            break
        nodes = []
        for row in batch:
            props = (
                {"dictum": read_dictum(row["text"])}
                if row["motion"]
                else {"explanation": read_explanation(row["text"], row["sections"])}
            )
            found += any(value is not None for value in props.values())
            nodes.append(Node.skeleton(COLLECTION_DOCUMENTS, row["key"], props))
        with NodeWriter(store) as writer:
            writer.add_all(nodes)
        after, read = batch[-1]["id"], read + len(batch)
        logger.info("Read %d motions and amendments: %d with a line.", read, found)
    logger.info("Motions and amendments read: %d, %d with a line.", read, found)
    return read


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description=(
            "Keep the dictum of every motion (what it asks or says) and the explanation of "
            "every amendment (the opening of its Toelichting) with text, for those "
            "normalized before normalize tk-content kept them."
        )
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Every motion and amendment with text again, not only those without.",
    )
    args = parser.parse_args(argv)
    return PipelineResult(updated=run(GraphStore(), every=args.all))
