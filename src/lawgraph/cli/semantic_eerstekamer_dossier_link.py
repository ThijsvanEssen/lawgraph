"""CLI: semantic pipeline linking EK stukken to TK kamerstukdossiers."""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.eerstekamer_dossier_link import (
    EerstekamerDossierLinkPipeline,
)

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Create DEEL_VAN_DOSSIER edges from EK stukken to TK kamerstukdossiers."
    )
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    logger.info(
        "EK dossier link semantic: starting (profile=%s).", profile or "default"
    )

    store = ArangoStore()
    pipeline = EerstekamerDossierLinkPipeline(store=store, domain_profile=profile)
    result = pipeline.run()

    logger.info("EK dossier link semantic completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("EK dossier link error: %s", err)
        sys.exit(1)
