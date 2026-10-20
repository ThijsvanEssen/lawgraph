"""``lawgraph semantic graph-derive``: the derived columns of a table derived again from its props.

A trigger of each node table derives its columns from ``props`` on every write
(``schema._derive``). A release that changes how (an expression, a column, a function it
calls) replaces the trigger, but rows written before keep what the old one derived; the
digest kept per table says which tables that is (``queries/derive``), and the API logs them
at its start. ``graph-derive <table>`` writes every row of the table again, ``BATCH`` rows a
transaction, which fires the trigger. ``--after ID`` starts past that row and ``--limit N``
stops after N rows, so a large table goes in slices, each under the lock on its own (the log
names the last row: go on with ``--after``); a series of slices from the start that reaches the
end records the table as derived by this version. Without a table it rewrites nothing and
names the tables that need it: so ``semantic all`` passes it in a moment.
"""

from __future__ import annotations

import argparse
from typing import Any

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries import derive
from lawgraph.db.schema import derived_collections
from lawgraph.pipelines.base import PipelineBase
from lawgraph.pipelines.command import add_limit_argument

logger = get_logger(__name__)


def add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "collection",
        nargs="?",
        choices=derived_collections(),
        help="The table to derive again; without it, the tables that need it are named.",
    )
    parser.add_argument(
        "--after", help="Start past this row id: the next slice of a run over all."
    )
    add_limit_argument(parser, "Stop after this many rows (a slice).")


def extra_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {"collection": args.collection, "after": args.after, "limit": args.limit}


class GraphDeriveSemanticPipeline(PipelineBase):
    store: GraphStore

    def __init__(
        self,
        store: GraphStore,
        *,
        collection: str | None = None,
        after: str | None = None,
        limit: int | None = None,
    ) -> None:
        super().__init__(store)
        self.collection = collection
        self.after = after
        self.limit = limit

    def run(self) -> PipelineResult:
        if self.collection is None:
            for stale in derive.stale_collections(self.store):
                logger.warning(
                    "The derivation of %s changed: run `lawgraph semantic graph-derive "
                    "%s` (in slices: --limit, --after).",
                    stale,
                    stale,
                )
            return PipelineResult()
        return self._derive(self.collection)

    def _derive(self, collection: str) -> PipelineResult:
        result = PipelineResult()
        last, done = self.after, False
        while not done:
            size = derive.BATCH
            if self.limit is not None:
                size = min(size, self.limit - result.updated)
            batch = derive.derive_batch(self.store, collection, last, size)
            result.updated += batch["count"]
            last = batch["last"] or last
            done = batch["count"] < size
            if self.limit is not None and result.updated >= self.limit:
                break
        derived = derive.record_progress(
            self.store, collection, after=self.after, last=last, done=done
        )
        logger.info(
            "Derived %d rows of %s again; the last read was %s (go on with --after %s)%s.",
            result.updated,
            collection,
            last,
            None if done else last,
            "; the table is derived by this version" if derived else "",
        )
        return result
