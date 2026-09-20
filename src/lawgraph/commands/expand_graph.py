"""``lawgraph expand-graph``: fetch what the graph refers to until nothing new turns up.

Each iteration runs ``fill-gaps --apply``; when that resolved stub nodes, ``normalize all``
and ``semantic all`` follow, which may reveal new stubs. Exit code 1 when any step failed.
"""

from __future__ import annotations

import argparse
import sys

from lawgraph.commands.fill_gaps import main as fill_gaps
from lawgraph.config.constants import COLLECTION_ARTICLES, COLLECTION_JUDGMENTS
from lawgraph.core.logging import get_logger, setup_logging
from lawgraph.db import ArangoStore
from lawgraph.pipelines.factory import run_command
from lawgraph.pipelines.orchestration import run_normalize_all, run_semantic_all

logger = get_logger(__name__)

_STUB_COUNT_AQL = f"""
RETURN LENGTH(FOR a IN {COLLECTION_ARTICLES} FILTER a.props.stub == true RETURN 1)
     + LENGTH(FOR j IN {COLLECTION_JUDGMENTS} FILTER j.props.stub == true RETURN 1)
"""


def _count_stubs(store: ArangoStore) -> int:
    return next(iter(store.query(_STUB_COUNT_AQL)))


def _expand(max_iterations: int) -> bool:
    """Run the loop; return True when every step succeeded."""
    store = ArangoStore()
    succeeded = True
    total_resolved = 0
    for iteration in range(1, max_iterations + 1):
        logger.info("expand-graph: iteration %d/%d", iteration, max_iterations)
        before = _count_stubs(store)
        succeeded &= run_command("fill-gaps", fill_gaps, ["--apply"])
        resolved = before - _count_stubs(store)
        if resolved <= 0:
            logger.info("expand-graph: no stubs resolved; the graph is stable.")
            break

        total_resolved += resolved
        logger.info("expand-graph: %d stub(s) resolved.", resolved)
        succeeded &= run_command("normalize all", run_normalize_all, [])
        succeeded &= run_command("semantic all", run_semantic_all, [])

    logger.info("expand-graph: %d stub(s) resolved in total.", total_resolved)
    return succeeded


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description=(
            "Repeat fill-gaps, normalize all and semantic all while stub nodes "
            "keep disappearing."
        ),
    )
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument(
        "--dry-run", action="store_true", help="Only print the fill-gaps report."
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        fill_gaps(argv=[])
        return

    try:
        succeeded = _expand(args.max_iterations)
    except Exception as exc:
        logger.error("expand-graph failed: %s", exc)
        sys.exit(1)
    if not succeeded:
        logger.error("expand-graph finished with failures.")
        sys.exit(1)
