"""``lawgraph semantic graph-list-stats``: precompute list-endpoint sort and filter keys on nodes.

Persists the keys onto each document so ``/api/instruments``, ``/api/judgments``
and friends can sort and filter by an index instead of deriving the
value per row.

Fields written:

instruments
    props.jurisdiction   — 'nl' (bwb_id present) | 'eu' (celex present) | null
    props.article_count  — its articles in force, without stubs: the total of /articles
    props.kind           — lower-cased copy of props.kind when present
    props.inbound_citation_count — of an instrument: REFERS_TO to it and to its articles
    props.amending       — a BWB regulation that changes others rather than standing on
                           its own (``graph_stats._INSTRUMENTS``)

judgments
    props.court_code     — uppercase ECLI court segment (e.g. 'HR', 'GHARN')
    props.tier           — the coarse tier, the Type of the court in the Instanties list
                           (``core.courts.court_of``: 'hoge_raad', 'gerechtshof',
                           'andere_instantie', ...)
    props.court_kind     — the kind of court within the tier ('ambtenarengerecht',
                           'gerecht_in_eerste_aanleg'; a tier of one kind: the tier)
    props.date_eff       — effective judgment date
    props.inbound_citation_count — the judgments that cite it (REFERS_TO), or a
                           publication of the same decision it keeps (SAME_AS), each once
    props.outbound_citation_count — the judgments it cites (REFERS_TO)
    props.decision_kind  — of a judgment without one (a stub): the kind its kind of
                           court gives (``core.judgment_kinds.KIND_OF_COURT_KIND``)
    props.names          — of a stub: its names in ``core.judgment_names``

articles
    props.inbound_citation_count — count of inbound REFERS_TO / EXPLAINS edges

committees
    props.active_dossier_count — the open dossiers a committee leads: those its
                                 activities are about and its cases are part of

Idempotent: only writes when the computed value differs from what is already on
the document.

``--since`` (the daily run): the counts of every node again, from the edges, but what only a
node's own props give (``date_eff`` of a judgment, ``amending`` of a regulation: its articles'
texts) only of the rows written since the previous complete run of this step began; the others
keep theirs. That run's moment is kept in ``pipeline_state`` (``graph-list-stats``) as the
oldest transaction then open, not as a time: the rows know the transaction that wrote them
(``xmin``), not when. The first run, a run after more than ``_FAR`` transactions and a run
without ``--since`` (the weekly run, or by hand: ``lawgraph semantic graph-list-stats``) read
every row. A change to how a key is derived from the props (a release) needs that run over all.
"""

from __future__ import annotations

import argparse
import datetime as dt
from typing import Any

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.progress import Progress
from lawgraph.db import GraphStore
from lawgraph.db.queries import graph_stats
from lawgraph.db.queries.state import get_state, set_state
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)

# ``pipeline_state``: the oldest transaction open when the last complete run began.
STATE_KEY = "graph-list-stats"
# Transactions after which a run reads every row: ``age`` of a transaction id wraps at 2^31.
_FAR = 1_000_000_000

_REFRESHERS = (
    ("instruments", graph_stats.refresh_instruments),
    ("judgments", graph_stats.refresh_judgments),
    ("committees", graph_stats.refresh_committees),
    ("articles", graph_stats.refresh_articles),
)


def add_args(parser: argparse.ArgumentParser) -> None:
    only_group = parser.add_mutually_exclusive_group()
    for name, _ in _REFRESHERS:
        only_group.add_argument(
            f"--{name}-only", action="store_true", help=f"Only update {name}."
        )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows would change; write nothing.",
    )


def extra_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    only = [name for name, _ in _REFRESHERS if getattr(args, f"{name}_only")]
    return {"only": only[0] if only else None, "dry_run": args.dry_run}


class GraphListStatsSemanticPipeline(PipelineBase):
    store: GraphStore

    def __init__(
        self,
        store: GraphStore,
        *,
        only: str | None = None,  # the collection of --<name>-only
        dry_run: bool = False,
    ) -> None:
        super().__init__(store)
        self.only = only
        self.dry_run = dry_run

    def run(self, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        began = graph_stats.oldest_open_transaction(self.store)
        written_after = self._written_after(began) if since is not None else None
        if written_after is None:
            logger.info("Every row read.")
        todo = [(n, r) for n, r in _REFRESHERS if self.only in (None, n)]
        # One update query per collection: the progress is in collections.
        progress = Progress("collections", total=len(todo))
        for name, refresh in progress.track(todo):
            count = refresh(
                self.store, dry_run=self.dry_run, written_after=written_after
            )
            if self.dry_run:
                logger.info("Would update %d %s.", count, name)
                result.skipped += count
            else:
                result.updated += count
        if not self.dry_run and self.only is None:
            set_state(self.store, STATE_KEY, {"transaction": began})
        return result

    def _written_after(self, began: int) -> str | None:
        """The transaction (as an ``xid``) the previous complete run began at, when the
        rows written since can be told apart from the others; None: read every row."""
        state = get_state(self.store, STATE_KEY) or {}
        previous = state.get("transaction")
        if not isinstance(previous, int) or not 0 <= began - previous < _FAR:
            return None
        logger.info("The props of the rows written since transaction %d.", previous)
        return str(previous % 2**32)
