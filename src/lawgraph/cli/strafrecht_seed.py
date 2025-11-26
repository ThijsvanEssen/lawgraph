from __future__ import annotations

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.strafrecht_seed import StrafrechtSeedPipeline

logger = get_logger(__name__)


def main() -> None:
    load_dotenv()
    setup_logging()

    store = ArangoStore()
    pipeline = StrafrechtSeedPipeline(store=store)
    summary = pipeline.run()

    logger.info("Strafrecht seed pipeline result: %s", summary)
