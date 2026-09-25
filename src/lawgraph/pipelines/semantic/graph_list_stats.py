"""``lawgraph semantic graph-list-stats``: precompute list-endpoint sort and filter keys on nodes.

Persists the keys onto each document so ``/api/instruments``, ``/api/judgments``
and friends can sort and filter via persistent indexes instead of deriving the
value per row.

Fields written:

instruments
    props.jurisdiction   — 'nl' (bwb_id present) | 'eu' (celex present) | null
    props.article_count  — count of PART_OF edges pointing at it
    props.kind           — lower-cased copy of props.kind when present

judgments
    props.court_code     — uppercase ECLI court segment (e.g. 'HR', 'GHARN')
    props.tier           — the college (``core.judgments.court_tier``: 'hoge_raad',
                           'raad_van_state', 'gerechtshof', 'rechtbank', ...)
    props.date_eff       — effective judgment date
    props.inbound_citation_count — count of inbound REFERS_TO edges
    props.decision_kind  — of a judgment without one (a stub): the kind its tier gives
                           (``core.judgments.KIND_OF_TIER``)
    props.names          — of a stub: its names in ``core.judgment_names``

articles
    props.inbound_citation_count — count of inbound REFERS_TO / EXPLAINS edges

committees
    props.active_dossier_count — committees leading an activity about an open
                                 dossier

Idempotent: only writes when the computed value differs from what is already on
the document.
"""

from __future__ import annotations

import argparse

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.progress import Progress
from lawgraph.db import ArangoStore
from lawgraph.db.queries import graph_stats

logger = get_logger(__name__)

_REFRESHERS = (
    ("instruments", graph_stats.refresh_instruments),
    ("judgments", graph_stats.refresh_judgments),
    ("committees", graph_stats.refresh_committees),
    ("articles", graph_stats.refresh_articles),
)


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description=(
            "Precompute the list-endpoint sort and filter keys on instruments, "
            "judgments, articles and committees so those endpoints can sort and "
            "filter via persistent indexes."
        )
    )
    only_group = parser.add_mutually_exclusive_group()
    for name, _ in _REFRESHERS:
        only_group.add_argument(
            f"--{name}-only", action="store_true", help=f"Only update {name}."
        )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many docs would change; write nothing.",
    )
    args = parser.parse_args(argv)

    store = ArangoStore()
    selected = [name for name, _ in _REFRESHERS if getattr(args, f"{name}_only")]
    result = PipelineResult()
    todo = [(n, r) for n, r in _REFRESHERS if not selected or n in selected]
    # One update query per collection: the progress is in collections.
    progress = Progress("collections", total=len(todo))
    for name, refresh in progress.track(todo):
        count = refresh(store, dry_run=args.dry_run)
        if args.dry_run:
            logger.info("Would update %d %s.", count, name)
            result.skipped += count
        else:
            result.updated += count
    return result
