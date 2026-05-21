"""CLI entry point: link publications to the article versions they caused."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.version_causes import VersionCausesSemanticPipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create CAUSED_VERSION edges from TK/EK publications to the "
            "instrument_article_versions they legislatively caused."
        )
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=365,
        help=(
            "Maximum days between a publication's datum and the version's valid_from "
            "for the link to be considered valid (default: 365)."
        ),
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    store = ArangoStore()
    pipeline = VersionCausesSemanticPipeline(store=store, window_days=args.window_days)

    try:
        result = pipeline.run()
    except Exception as exc:
        logger.error("Version-causes semantic pipeline failed: %s", exc)
        sys.exit(1)

    logger.info("Version-causes complete: %s", result.summary())
