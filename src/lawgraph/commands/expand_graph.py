"""``lawgraph expand-graph``: fetch what the graph refers to until nothing new turns up.

Each iteration runs ``fill-gaps --apply``; when that retrieved records, ``normalize all``
and ``semantic all`` follow for what was fetched since the iteration began, which may
reveal new stubs. When the loop ends one full ``semantic all`` follows: a text that was
loaded long ago can name a law that was loaded just now. Exit code 1 when any step failed.
"""

from __future__ import annotations

import argparse
import datetime as dt

from lawgraph.commands.fill_gaps import main as fill_gaps
from lawgraph.config.constants import COLLECTION_RAW_SOURCES, RAW_KIND_MISSING_SUFFIX
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore
from lawgraph.pipelines.execution import Outcome, combined, execute
from lawgraph.pipelines.orchestration import normalize_all, semantic_all

logger = get_logger(__name__)

_RECORDS_AQL = f"""
FOR r IN {COLLECTION_RAW_SOURCES}
    COLLECT kind = r.kind WITH COUNT INTO n
    FILTER NOT LIKE(kind, @missing)
    RETURN n
"""


def _count_records(store: ArangoStore) -> int:
    """The raw records that hold a document (not those that remember a 404)."""
    return sum(store.query(_RECORDS_AQL, {"missing": f"%{RAW_KIND_MISSING_SUFFIX}"}))


def _expand(max_iterations: int) -> list[Outcome]:
    """Run the loop; how every step of it ended.

    An iteration is worth repeating when fill-gaps retrieved something. The number of stubs
    does not tell: loading a judgment closes one stub and opens one for every judgment it
    cites that is not loaded either, so the count can stand still or grow while the graph
    fills.
    """
    store = ArangoStore()
    outcomes: list[Outcome] = []
    total = 0
    for iteration in range(1, max_iterations + 1):
        logger.info("expand-graph: iteration %d/%d", iteration, max_iterations)
        # ``fetched_at`` has a precision of a second: the second this round began in.
        began = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        before = _count_records(store)
        outcomes.append(execute("fill-gaps", fill_gaps, ["--apply"]))
        retrieved = _count_records(store) - before
        if retrieved <= 0:
            logger.info(
                "expand-graph: fill-gaps retrieved nothing new; the graph is stable."
            )
            break

        total += retrieved
        logger.info("expand-graph: %d new record(s) retrieved.", retrieved)
        since = ["--since", began]
        outcomes.append(execute("normalize all", normalize_all, since))
        outcomes.append(execute("semantic all", semantic_all, since))

    logger.info("expand-graph: %d record(s) retrieved in total.", total)
    if total:
        outcomes.append(execute("semantic all", semantic_all, []))
    return outcomes


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description=(
            "Repeat fill-gaps and, for what it retrieved, normalize all and semantic all, "
            "while fill-gaps keeps retrieving records; then one full semantic all."
        ),
    )
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument(
        "--dry-run", action="store_true", help="Only print the fill-gaps report."
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        return fill_gaps(argv=[])
    return combined(_expand(args.max_iterations))
