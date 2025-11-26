from __future__ import annotations

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline

logger = get_logger(__name__)


def main() -> None:
    load_dotenv()
    setup_logging()

    store = ArangoStore()
    pipeline = BWBNormalizePipeline(store=store)
    pipeline.run()

    logger.info("BWB-normalisatie afgerond.")
