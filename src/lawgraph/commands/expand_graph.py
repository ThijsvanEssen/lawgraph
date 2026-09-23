"""``lawgraph expand-graph``: fetch what the graph refers to until nothing new turns up.

A round is the three phases for what the graph lacks::

    retrieve all --mode gaps        every source fetches what is referred to, side by side
    normalize all --since <round>   the records of this round become nodes
    semantic all --since <round>    and get their edges, which may name new things

It repeats while a round retrieved records. When the loop ends one full ``semantic all``
follows: a text that was loaded long ago can name a law that was loaded just now.
"""

from __future__ import annotations

import argparse
import datetime as dt

from lawgraph.config.constants import RAW_KIND_MISSING_SUFFIX
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.command import Outcome, combined_result, run_command
from lawgraph.pipelines.orchestration import normalize_all, retrieve_all, semantic_all
from lawgraph.pipelines.retrieve_commands import GAPS

logger = get_logger(__name__)


def _count_records(store: ArangoStore) -> int:
    """The raw records that hold a document (not those that remember a 404)."""
    return sum(raw_queries.record_counts(store, RAW_KIND_MISSING_SUFFIX))


def _expand(max_iterations: int) -> list[Outcome]:
    """Run the loop; how every step of it ended.

    A round is worth repeating when it retrieved something. The number of stubs
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
        outcomes.append(run_command("retrieve all", retrieve_all, ["--mode", GAPS]))
        retrieved = _count_records(store) - before
        if retrieved <= 0:
            logger.info("expand-graph: nothing new was retrieved; the graph is stable.")
            break

        total += retrieved
        logger.info("expand-graph: %d new record(s) retrieved.", retrieved)
        since = ["--since", began]
        outcomes.append(run_command("normalize all", normalize_all, since))
        outcomes.append(run_command("semantic all", semantic_all, since))

    logger.info("expand-graph: %d record(s) retrieved in total.", total)
    if total:
        outcomes.append(run_command("semantic all", semantic_all, []))
    return outcomes


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description=(
            "Repeat `retrieve all --mode gaps` and, for what it retrieved, normalize all and "
            "semantic all, while records keep coming; then one full semantic all."
        ),
    )
    parser.add_argument("--max-iterations", type=int, default=10)
    args = parser.parse_args(argv)
    return combined_result(_expand(args.max_iterations))
