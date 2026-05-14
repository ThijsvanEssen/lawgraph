"""CLI for detecting AMENDS_INSTRUMENT and IMPLEMENTS_DIRECTIVE edges."""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from lawgraph.cli.retrieve_helpers import load_profile_config
from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.instrument_relations import InstrumentRelationsPipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Detect AMENDS_INSTRUMENT edges from TK titles and "
            "IMPLEMENTS_DIRECTIVE edges from BWB source text."
        )
    )
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
        help="Domain profile containing instrument_aliases (e.g. strafrecht).",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    store = ArangoStore()
    config = load_profile_config(profile)
    pipeline = InstrumentRelationsPipeline(
        store=store,
        domain_profile=profile,
        domain_config=config,
    )

    logger.info(
        "Starting instrument relations pipeline (profile=%s).", profile or "default"
    )
    result = pipeline.run()
    logger.info("Instrument relations: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("Instrument relations error: %s", err)
        sys.exit(1)
