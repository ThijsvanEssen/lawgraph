from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.config.settings import BWB_BASE_URL  # noqa: F401 — triggers env load
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve ALL historical BWB toestanden (not just latest)."
    )
    parser.add_argument(
        "bwb_ids",
        nargs="*",
        help="BWB-IDs to retrieve history for. Omit to enumerate all via SRU.",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    store = ArangoStore()
    pipeline = BWBRetrievePipeline(store=store)

    try:
        if args.bwb_ids:
            result = pipeline.run_history(bwb_ids=args.bwb_ids)
        else:
            result = pipeline.run_history_full()
    except Exception as exc:
        logger.error("BWB history retrieval failed: %s", exc)
        sys.exit(1)

    logger.info("BWB history retrieval complete: %s", result.summary())
