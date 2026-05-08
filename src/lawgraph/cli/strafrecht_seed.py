from __future__ import annotations

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.seed_treaties import TreatiesSeedPipeline
from lawgraph.pipelines.strafrecht_seed import StrafrechtSeedPipeline

logger = get_logger(__name__)


def main() -> None:
    load_dotenv()
    setup_logging()

    store = ArangoStore()

    # 1. Seed EVRM articles (independent of domain profile)
    treaties = TreatiesSeedPipeline(store=store)
    treaties_summary = treaties.run()
    logger.info("Treaties seed pipeline result: %s", treaties_summary)

    # 2. Seed strafrecht domain topic + instruments
    pipeline = StrafrechtSeedPipeline(store=store)
    summary = pipeline.run()
    logger.info("Strafrecht seed pipeline result: %s", summary)
