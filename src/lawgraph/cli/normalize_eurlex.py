from __future__ import annotations

import datetime as dt

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.normalize.eurlex import EUNormalizePipeline

logger = get_logger(__name__)


def main() -> None:
    load_dotenv()
    setup_logging()

    store = ArangoStore()
    pipeline = EUNormalizePipeline(store=store)

    since: dt.datetime | None = None
    pipeline.run(since=since)

    logger.info("EU normalization completed.")
