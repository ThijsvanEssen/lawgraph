"""CLI that runs all semantic pipelines in sequence."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

from dotenv import load_dotenv

from lawgraph.cli.semantic_bwb_articles import main as semantic_bwb_main
from lawgraph.cli.semantic_eu_articles import main as semantic_eu_main
from lawgraph.cli.semantic_instrument_relations import (
    main as semantic_instrument_relations_main,
)
from lawgraph.cli.semantic_judgment_citations import (
    main as semantic_judgment_citations_main,
)
from lawgraph.cli.semantic_rechtspraak_articles import main as semantic_rechtspraak_main
from lawgraph.cli.semantic_tk_articles import main as semantic_tk_main
from lawgraph.config import list_domain_profiles
from lawgraph.logging import get_logger, setup_logging

logger = get_logger(__name__)
_TRUE_VALUES = {"1", "true"}
PROFILE_CHOICES = list_domain_profiles()


def main() -> None:
    load_dotenv()
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Run all semantic pipelines in sequence."
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES or None,
        help="Domain profile to use for all sub-pipelines.",
    )
    args = parser.parse_args()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")

    logger.info("semantic-all starting (profile=%s).", profile or "default")

    base_argv = ["--profile", profile] if profile else []

    steps = [
        (
            "TK semantic linking",
            "LAWGRAPH_SEMANTIC_SKIP_TK",
            lambda: semantic_tk_main(argv=base_argv),
        ),
        (
            "Rechtspraak semantic linking",
            "LAWGRAPH_SEMANTIC_SKIP_RECHTSPRAAK",
            lambda: semantic_rechtspraak_main(argv=base_argv),
        ),
        (
            "EU semantic linking",
            "LAWGRAPH_SEMANTIC_SKIP_EU",
            lambda: semantic_eu_main(argv=base_argv),
        ),
        (
            "BWB article semantic linking",
            "LAWGRAPH_SEMANTIC_SKIP_BWB",
            lambda: semantic_bwb_main(argv=base_argv),
        ),
        (
            "Judgment citation linking",
            "LAWGRAPH_SEMANTIC_SKIP_JUDGMENT_CITATIONS",
            lambda: semantic_judgment_citations_main(argv=base_argv),
        ),
        (
            "Instrument relations (AMENDS/IMPLEMENTS)",
            "LAWGRAPH_SEMANTIC_SKIP_INSTRUMENT_RELATIONS",
            lambda: semantic_instrument_relations_main(argv=base_argv),
        ),
    ]

    results: list[tuple[str, str]] = []
    for name, env_var, runner in steps:
        if _should_skip(env_var):
            logger.info("%s skipped (%s set).", name, env_var)
            results.append((name, "skipped"))
            continue
        status = _run_step(name=name, runner=runner)
        results.append((name, status))

    _log_summary("semantic-all", results)


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
