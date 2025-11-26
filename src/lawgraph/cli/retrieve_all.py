from __future__ import annotations

import os
from typing import Callable

from dotenv import load_dotenv

from lawgraph.cli.retrieve_bwb import main as retrieve_bwb_main
from lawgraph.cli.retrieve_eurlex import main as retrieve_eurlex_main
from lawgraph.cli.retrieve_rechtspraak import main as retrieve_rechtspraak_main
from lawgraph.cli.retrieve_tk import main as retrieve_tk_main
from lawgraph.logging import get_logger, setup_logging

logger = get_logger(__name__)

_TRUE_VALUES = {"1", "true"}


def main() -> None:
    load_dotenv()
    setup_logging()

    logger.info("retrieve-all starting.")

    _run_optional_step(
        name="TK retrieve",
        env_var="LAWGRAPH_RETRIEVE_SKIP_TK",
        runner=retrieve_tk_main,
    )
    _run_optional_step(
        name="Rechtspraak retrieve",
        env_var="LAWGRAPH_RETRIEVE_SKIP_RECHTSPRAAK",
        runner=retrieve_rechtspraak_main,
    )
    _run_optional_step(
        name="EurLex retrieve",
        env_var="LAWGRAPH_RETRIEVE_SKIP_EURLEX",
        runner=retrieve_eurlex_main,
    )
    _run_optional_step(
        name="BWB retrieve",
        env_var="LAWGRAPH_RETRIEVE_SKIP_BWB",
        runner=retrieve_bwb_main,
    )

    logger.info("retrieve-all completed.")


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
