"""CLI that runs all semantic pipelines in sequence."""

from __future__ import annotations

import os
from typing import Callable

from dotenv import load_dotenv

from lawgraph.cli.semantic_bwb_articles import main as semantic_bwb_main
from lawgraph.cli.semantic_eu_articles import main as semantic_eu_main
from lawgraph.cli.semantic_rechtspraak_articles import main as semantic_rechtspraak_main
from lawgraph.cli.semantic_tk_articles import main as semantic_tk_main
from lawgraph.logging import get_logger, setup_logging

logger = get_logger(__name__)
_TRUE_VALUES = {"1", "true"}


def main() -> None:
    load_dotenv()
    setup_logging()

    logger.info("semantic-all starting.")

    _run_optional_step(
        name="TK semantic linking",
        env_var="LAWGRAPH_SEMANTIC_SKIP_TK",
        runner=semantic_tk_main,
    )
    _run_optional_step(
        name="Rechtspraak semantic linking",
        env_var="LAWGRAPH_SEMANTIC_SKIP_RECHTSPRAAK",
        runner=semantic_rechtspraak_main,
    )
    _run_optional_step(
        name="EU semantic linking",
        env_var="LAWGRAPH_SEMANTIC_SKIP_EU",
        runner=semantic_eu_main,
    )
    _run_optional_step(
        name="BWB article semantic linking",
        env_var="LAWGRAPH_SEMANTIC_SKIP_BWB",
        runner=semantic_bwb_main,
    )

    logger.info("semantic-all completed.")


def _run_optional_step(
    *,
    name: str,
    env_var: str,
    runner: Callable[[], None],
) -> None:
    if _should_skip(env_var):
        logger.info("%s skipped (%s set).", name, env_var)
        return
    _run_step(name=name, runner=runner)


def _run_step(*, name: str, runner: Callable[[], None]) -> None:
    logger.info("Starting %s...", name)
    try:
        runner()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            logger.error("%s failed with exit code %s.", name, exc.code)
            raise
        logger.info("%s completed.", name)
        return
    logger.info("%s completed.", name)


def _should_skip(env_var: str) -> bool:
    value = os.getenv(env_var)
    if not value:
        return False
    return value.strip().lower() in _TRUE_VALUES
