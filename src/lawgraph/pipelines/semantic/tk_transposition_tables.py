"""Semantic pipeline: ``TRANSPOSED_TO`` from an article of an old law to its place in the new
law of a recodification, read from the transposition tables: the PDFs ``retrieve
tk-transposition-tables`` stored and the tables in the XML of the memoranda
(``_transposition_tables``).

Each row of a table that holds (the old law has the article, the new law the article and
every lid the row names) is a part of the edge of its pair of articles: ``meta.parts``
``[{from, to}]`` as the table writes them, ``meta.source`` the table's source (when two
tables give the pair, the first), ``meta.basis`` ``transposition_table``. A row that does
not hold, and an article of the old law no row of any table between the two laws places in
an article of the new law, is a gap: counted as a note of the run, listed by ``lawgraph
succession-gaps``. Derived in full on every run: an edge of the step no table gives any
more goes.
"""

from __future__ import annotations

from lawgraph.config.constants import RELATION_TRANSPOSED_TO
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.provenance import BASIS_TRANSPOSITION_TABLE
from lawgraph.db import EdgeWriter
from lawgraph.sources.addresses import edge_source

from ._transposition_tables import Succession, read_successions
from .base import SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)
# Read from the official table, each row checked against the text of the new law.
CONFIDENCE = 1.0

# What a gap of each kind is, in the notes of a run.
GAP_NOTES = {
    "unreadable": "a row whose place does not read",
    "no_old_article": "a row of an article the old law does not have",
    "no_new_article": "a row placing an article in one the new law does not have",
    "no_lid": "a row naming a lid the article of the new law does not have",
    "no_row": "an article of the old law no table has a row for",
    "no_article": "an article of the old law the tables place in no article",
    "not_placed": "an article of the old law none of whose rows holds",
}


class TKTranspositionTablesSemanticPipeline(SemanticPipelineBase):
    """Old articles to their place in the new law, from the transposition tables."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        edges = EdgeWriter(self.store, what=None, remembers=True)
        problems, successions = read_successions(self.store)
        for succession in self._track(successions, "pairs of laws"):
            self._write(edges, succession)
        for table in problems:
            self.progress.skip(
                f"a table that places nothing: {table.problem}", table.title
            )
        edges.flush_into(result)
        removed = edges.remove_stale_of_source(RELATION_TRANSPOSED_TO, EDGE_SOURCE)
        logger.info("%d edges no table gives any more removed.", removed)
        self.add_outcomes(result)
        return result

    def _write(self, edges: EdgeWriter, succession: Succession) -> None:
        placed = succession.placed
        for pair, parts in placed.pairs.items():
            old, new = pair
            edges.add(
                old,
                new,
                RELATION_TRANSPOSED_TO,
                source=EDGE_SOURCE,
                confidence=CONFIDENCE,
                meta={
                    "basis": BASIS_TRANSPOSITION_TABLE,
                    "source": placed.sources[pair][0],
                    "parts": parts,
                },
            )
        for gap in placed.gaps:
            self.progress.note(
                GAP_NOTES[gap.kind],
                f"{gap.source} art. {gap.old_article} {gap.part} {gap.text}".strip(),
            )
        logger.info(
            "%s: %d articles of %s placed in %s, %d gaps (lawgraph succession-gaps).",
            ", ".join(dict.fromkeys(t.identifier for t in succession.tables)),
            len({old for old, _ in placed.pairs}),
            succession.old_law,
            succession.new_law,
            len(placed.gaps),
        )
