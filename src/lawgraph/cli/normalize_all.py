from __future__ import annotations

import os
from typing import Callable

from dotenv import load_dotenv

from lawgraph.cli.normalize_bwb import main as normalize_bwb_main
from lawgraph.cli.normalize_eurlex import main as normalize_eurlex_main
from lawgraph.cli.normalize_rechtspraak import main as normalize_rechtspraak_main
from lawgraph.cli.normalize_tk import main as normalize_tk_main
from lawgraph.cli.strafrecht_seed import main as strafrecht_seed_main
from lawgraph.logging import get_logger, setup_logging

logger = get_logger(__name__)

_TRUE_VALUES = {"1", "true"}


def main() -> None:
    load_dotenv()
    setup_logging()

    logger.info("normalize-all starting.")

    profile = os.getenv("LAWGRAPH_PROFILE")
    normalized_profile = profile.lower() if profile else None

    _run_optional_strafrecht_seed(profile, normalized_profile)
    _run_optional_step(
        name="TK normalization",
        env_var="LAWGRAPH_NORMALIZE_SKIP_TK",
        runner=normalize_tk_main,
    )
    _run_optional_step(
        name="Rechtspraak normalization",
        env_var="LAWGRAPH_NORMALIZE_SKIP_RECHTSPRAAK",
        runner=normalize_rechtspraak_main,
    )
    _run_optional_step(
        name="EurLex normalization",
        env_var="LAWGRAPH_NORMALIZE_SKIP_EURLEX",
        runner=normalize_eurlex_main,
    )
    _run_optional_step(
        name="BWB normalization",
        env_var="LAWGRAPH_NORMALIZE_SKIP_BWB",
        runner=normalize_bwb_main,
    )

    logger.info("normalize-all completed.")


def _run_optional_strafrecht_seed(
    profile: str | None,
    normalized_profile: str | None,
) -> None:
    env_var = "LAWGRAPH_NORMALIZE_SKIP_STRAFRECHT_SEED"
    step_name = "Strafrecht seed"
    if _should_skip(env_var):
        logger.info("%s skipped (%s set).", step_name, env_var)
        return
    if normalized_profile in (None, "strafrecht"):
        _run_step(name=step_name, runner=strafrecht_seed_main)
        return
    logger.info(
        "%s skipped (profile=%s).",
        step_name,
        profile or "default",
    )


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
