"""What a retrieve pipeline chooses its work from in the graph, and a warning when it is not there.

Most retrieve pipelines ask their source what there is. A few choose from what a normalize
pipeline wrote: ``retrieve tk-content`` fetches the XML of the documents of ``normalize
tk-dossiers``, ``retrieve eerstekamer-bills`` the pages of the bills ``normalize
eerstekamer-votes`` names, ``retrieve eurlex`` the acts ``normalize eurlex`` holds. On a graph
without those rows such a pipeline finds nothing to do and ends ``ok``, which looks like done.

``Reads`` names those rows in the registry; ``reading`` makes the command say, before it runs,
that they are not there: in the log, and in a note of its result that the table of
``retrieve all`` shows.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from dataclasses import dataclass

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries import gaps as gap_queries
from lawgraph.pipelines.command import Command

logger = get_logger(__name__)

# What a retrieve command does without ``--mode``.
DEFAULT_MODE = "incremental"


@dataclass(frozen=True)
class Reads:
    """The nodes a retrieve pipeline chooses its work from, and the pipeline that writes them."""

    pipeline: str  # the normalize pipeline: tk-dossiers
    collection: str  # documents
    label: str  # TK
    # The modes of the command that choose from them; empty: every mode.
    modes: tuple[str, ...] = ()

    def applies(self, argv: Sequence[str]) -> bool:
        return not self.modes or _mode(argv) in self.modes

    @property
    def note(self) -> str:
        return f"no {self.label} {self.collection} yet: run normalize {self.pipeline} first"


def _mode(argv: Sequence[str]) -> str:
    """The ``--mode`` of *argv*, as argparse reads it."""
    for i, arg in enumerate(argv):
        if arg == "--mode" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--mode="):
            return arg.partition("=")[2]
    return DEFAULT_MODE


def _asks_for_help(argv: Sequence[str]) -> bool:
    """``-h``/``--help``: the command prints its options and runs nothing."""
    return any(arg in ("-h", "--help") for arg in argv)


def missing(reads: Sequence[Reads], argv: Sequence[str]) -> list[Reads]:
    """Those of *reads* this run chooses from and the graph does not hold; none for a
    request for help, which needs no database."""
    if _asks_for_help(argv):
        return []
    wanted = [r for r in reads if r.applies(argv)]
    if not wanted:
        return []
    store = GraphStore()
    return [
        r for r in wanted if not gap_queries.holds_label(store, r.collection, r.label)
    ]


def reading(command: Command, reads: Sequence[Reads]) -> Command:
    """*command*, warning first when the graph does not hold what it chooses its work from."""

    @functools.wraps(command)
    def checked(argv: list[str] | None = None) -> PipelineResult:
        absent = missing(reads, argv or [])
        for r in absent:
            logger.warning(
                "This run chooses from the %s %s of normalize %s, and the graph holds none: "
                "what it would fetch for them is not fetched now. Run normalize %s first.",
                r.label,
                r.collection,
                r.pipeline,
                r.pipeline,
            )
        result = command(argv)
        result.notes += [r.note for r in absent]
        return result

    return checked
