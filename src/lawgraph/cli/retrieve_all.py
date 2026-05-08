from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

from dotenv import load_dotenv

from lawgraph.cli.retrieve_bwb import main as retrieve_bwb_main
from lawgraph.cli.retrieve_eurlex import main as retrieve_eurlex_main
from lawgraph.cli.retrieve_rechtspraak import main as retrieve_rechtspraak_main
from lawgraph.cli.retrieve_tk import main as retrieve_tk_main
from lawgraph.config import list_domain_profiles
from lawgraph.logging import get_logger, setup_logging

logger = get_logger(__name__)

_TRUE_VALUES = {"1", "true"}
PROFILE_CHOICES = list_domain_profiles()


def main() -> None:
    load_dotenv()
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Run all retrieve pipelines in sequence."
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES or None,
        help="Domain profile to use for all sub-pipelines.",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=1,
        help="How many days to look back for time-based retrieval (TK, Rechtspraak).",
    )
    args = parser.parse_args()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    since_days = args.since_days

    logger.info(
        "retrieve-all starting (profile=%s, since-days=%d).",
        profile or "default",
        since_days,
    )

    base_argv = []
    if profile:
        base_argv = ["--profile", profile]

    def tk_runner() -> None:
        retrieve_tk_main(argv=[*base_argv, "--since-days", str(since_days)])

    def rechtspraak_runner() -> None:
        retrieve_rechtspraak_main(argv=[*base_argv, "--since-days", str(since_days)])

    def eurlex_runner() -> None:
        retrieve_eurlex_main(argv=base_argv)

    def bwb_runner() -> None:
        retrieve_bwb_main(argv=base_argv)

    steps = [
        ("TK retrieve", "LAWGRAPH_RETRIEVE_SKIP_TK", tk_runner),
        (
            "Rechtspraak retrieve",
            "LAWGRAPH_RETRIEVE_SKIP_RECHTSPRAAK",
            rechtspraak_runner,
        ),
        ("EurLex retrieve", "LAWGRAPH_RETRIEVE_SKIP_EURLEX", eurlex_runner),
        ("BWB retrieve", "LAWGRAPH_RETRIEVE_SKIP_BWB", bwb_runner),
    ]

    results: list[tuple[str, str]] = []
    for name, env_var, runner in steps:
        if _should_skip(env_var):
            logger.info("%s skipped (%s set).", name, env_var)
            results.append((name, "skipped"))
            continue
        status = _run_step(name=name, runner=runner)
        results.append((name, status))

    _log_summary("retrieve-all", results)


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
