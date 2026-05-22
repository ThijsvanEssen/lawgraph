"""Orchestration helpers and run_*_all() entry points.

Combines the step-runner utilities (formerly cli/_orchestration.py) and the
three phase orchestrators (formerly cli/normalize_all.py, retrieve_all.py,
semantic_all.py).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

from dotenv import load_dotenv

from lawgraph.core.logging import get_logger, setup_logging
from lawgraph.pipelines.list_stats import main as list_stats_main
from lawgraph.sources.registry import SOURCES, RetrieveCtx

logger = get_logger(__name__)

# ── Step runner helpers ───────────────────────────────────────────────────────


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
    return os.getenv(env_var, "").strip().lower() == "true"


def _make_step_runner(fn: Callable[..., None], argv: list[str]) -> Callable[[], None]:
    """Wrap a pipeline main function with a fixed argv into a zero-arg callable."""
    return lambda: fn(argv=argv)


# ── normalize-all ─────────────────────────────────────────────────────────────


def run_normalize_all(argv: list[str] | None = None) -> None:
    load_dotenv()
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Run all normalization pipelines in sequence."
    )
    parser.parse_args(argv)

    logger.info("normalize-all starting.")

    steps: list[tuple[str, str, Callable[[], None]]] = []

    for source in SOURCES:
        if source.normalize_main is None:
            continue
        steps.append(
            (
                source.display_name,
                source.normalize_skip_env or "",
                _make_step_runner(source.normalize_main, []),
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


# ── retrieve-all ──────────────────────────────────────────────────────────────


def run_retrieve_all(argv: list[str] | None = None) -> None:
    load_dotenv()
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Run all retrieve pipelines in sequence."
    )
    parser.add_argument("--since-days", type=int, default=1)
    parser.add_argument(
        "--mode", choices=["incremental", "full"], default="incremental"
    )
    args = parser.parse_args(argv)

    ctx = RetrieveCtx(since_days=args.since_days, mode=args.mode)

    logger.info(
        "retrieve-all starting (mode=%s, since-days=%d).",
        ctx.mode,
        ctx.since_days,
    )

    steps: list[tuple[str, str, Callable[[], None]]] = []
    for source in SOURCES:
        if source.retrieve_main is None or source.retrieve_argv_builder is None:
            continue
        steps.append(
            (
                source.display_name,
                source.retrieve_skip_env or "",
                _make_step_runner(
                    source.retrieve_main, source.retrieve_argv_builder(ctx)
                ),
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

    _log_summary("retrieve-all", results)


# ── semantic-all ──────────────────────────────────────────────────────────────


def run_semantic_all(argv: list[str] | None = None) -> None:
    load_dotenv()
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Run all semantic pipelines in sequence."
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    logger.info("semantic-all starting.")

    steps: list[tuple[str, str, Callable[[], None]]] = []
    for source in SOURCES:
        if source.semantic_main is None:
            continue
        steps.append(
            (
                source.display_name,
                source.semantic_skip_env or "",
                _make_step_runner(source.semantic_main, []),
            )
        )

    steps.append(
        ("List-endpoint stats", "LAWGRAPH_SEMANTIC_SKIP_LIST_STATS", list_stats_main)
    )

    results: list[tuple[str, str]] = []
    for name, env_var, runner in steps:
        if env_var and _should_skip(env_var):
            logger.info("%s skipped (%s set).", name, env_var)
            results.append((name, "skipped"))
            continue
        status = _run_step(name=name, runner=runner)
        results.append((name, status))
        if args.strict and status not in ("ok", "skipped"):
            logger.error(
                "semantic-all: aborting after failure in '%s' (--strict).", name
            )
            sys.exit(1)

    _log_summary("semantic-all", results)
