from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

from dotenv import load_dotenv

from lawgraph.cli.normalize_bwb import main as normalize_bwb_main
from lawgraph.cli.normalize_eurlex import main as normalize_eurlex_main
from lawgraph.cli.normalize_rechtspraak import main as normalize_rechtspraak_main
from lawgraph.cli.normalize_tk import main as normalize_tk_main
from lawgraph.cli.strafrecht_seed import main as strafrecht_seed_main
from lawgraph.config import list_domain_profiles
from lawgraph.logging import get_logger, setup_logging

logger = get_logger(__name__)

_TRUE_VALUES = {"1", "true"}
_PROFILE_CHOICES = list_domain_profiles()


def main() -> None:
    load_dotenv()
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Run all normalization pipelines in sequence."
    )
    parser.add_argument(
        "--profile",
        choices=_PROFILE_CHOICES or None,
        help="Domain profile to use for all sub-pipelines.",
    )
    args = parser.parse_args()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    normalized_profile = profile.lower() if profile else None

    logger.info("normalize-all starting (profile=%s).", profile or "default")

    steps: list[tuple[str, str, Callable[[], None]]] = []

    if not _should_skip("LAWGRAPH_NORMALIZE_SKIP_STRAFRECHT_SEED"):
        if normalized_profile in (None, "strafrecht"):
            steps.append(
                (
                    "Strafrecht seed",
                    "LAWGRAPH_NORMALIZE_SKIP_STRAFRECHT_SEED",
                    strafrecht_seed_main,
                )
            )

    steps += [
        ("TK normalization", "LAWGRAPH_NORMALIZE_SKIP_TK", normalize_tk_main),
        (
            "Rechtspraak normalization",
            "LAWGRAPH_NORMALIZE_SKIP_RECHTSPRAAK",
            normalize_rechtspraak_main,
        ),
        (
            "EurLex normalization",
            "LAWGRAPH_NORMALIZE_SKIP_EURLEX",
            normalize_eurlex_main,
        ),
        ("BWB normalization", "LAWGRAPH_NORMALIZE_SKIP_BWB", normalize_bwb_main),
    ]

    results: list[tuple[str, str]] = []
    for name, env_var, runner in steps:
        if _should_skip(env_var):
            logger.info("%s skipped (%s set).", name, env_var)
            results.append((name, "skipped"))
            continue
        status = _run_step(name=name, runner=runner)
        results.append((name, status))

    _log_summary("normalize-all", results)


def _run_step(*, name: str, runner: Callable[[], None]) -> str:
    logger.info("Starting %s...", name)
    try:
        runner()
        logger.info("%s completed.", name)
        return "ok"
    except SystemExit as exc:
        if exc.code not in (None, 0):
            logger.error("%s failed with exit code %s.", name, exc.code)
            return f"exit({exc.code})"
        logger.info("%s completed.", name)
        return "ok"
    except Exception as exc:
        logger.error("%s raised an exception: %s", name, exc)
        return f"error: {exc}"


def _log_summary(label: str, results: list[tuple[str, str]]) -> None:
    logger.info("%s summary:", label)
    for name, status in results:
        logger.info("  %-40s %s", name, status)
    failures = [name for name, status in results if status not in ("ok", "skipped")]
    if failures:
        logger.error("%s finished with %d failure(s).", label, len(failures))
        sys.exit(1)
    logger.info("%s completed successfully.", label)


def _should_skip(env_var: str) -> bool:
    value = os.getenv(env_var)
    if not value:
        return False
    return value.strip().lower() in _TRUE_VALUES
