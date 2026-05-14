from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

from dotenv import load_dotenv

from lawgraph.cli.backfill_list_stats import main as backfill_list_stats_main
from lawgraph.cli.strafrecht_seed import main as strafrecht_seed_main
from lawgraph.config import list_domain_profiles
from lawgraph.logging import get_logger, setup_logging
from lawgraph.sources import SOURCES

logger = get_logger(__name__)

_TRUE_VALUES = {"1", "true"}


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Run all normalization pipelines in sequence."
    )
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
        help="Domain profile to use for all sub-pipelines.",
    )
    args = parser.parse_args(argv)

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    normalized_profile = profile.lower() if profile else None

    logger.info("normalize-all starting (profile=%s).", profile or "default")

    steps: list[tuple[str, str, Callable[[], None]]] = []

    if normalized_profile in (None, "strafrecht"):
        steps.append(
            (
                "Strafrecht seed",
                "LAWGRAPH_NORMALIZE_SKIP_STRAFRECHT_SEED",
                strafrecht_seed_main,
            )
        )

    for source in SOURCES:
        if source.normalize_main is None:
            continue
        main_fn = source.normalize_main

        def _make_runner(
            fn: Callable[..., None], _argv: list[str]
        ) -> Callable[[], None]:
            return lambda: fn(argv=_argv)

        steps.append(
            (
                source.display_name,
                source.normalize_skip_env or "",
                _make_runner(main_fn, []),
            )
        )

    # Refresh precomputed sort/filter stats consumed by /api/instruments and
    # /api/judgments. article_count depends on edges from BWB/EurLex above,
    # so this must run last.
    steps.append(
        (
            "List-endpoint stats backfill",
            "LAWGRAPH_NORMALIZE_SKIP_LIST_STATS",
            backfill_list_stats_main,
        )
    )

    results: list[tuple[str, str]] = []
    for name, env_var, runner in steps:
        if env_var and _should_skip(env_var):
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
