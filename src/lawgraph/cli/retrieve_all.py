from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.logging import get_logger, setup_logging
from lawgraph.sources import SOURCES

logger = get_logger(__name__)

_TRUE_VALUES = {"1", "true"}


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Run all retrieve pipelines in sequence."
    )
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
        help="Domain profile to use for all sub-pipelines.",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=1,
        help="How many days to look back for time-based retrieval (TK, Rechtspraak).",
    )
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help=(
            "'incremental' uses --since-days for time-windowed sources; "
            "'full' enables full-load for all sources that support it."
        ),
    )
    args = parser.parse_args(argv)

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    since_days = args.since_days
    mode = args.mode

    logger.info(
        "retrieve-all starting (profile=%s, mode=%s, since-days=%d).",
        profile or "default",
        mode,
        since_days,
    )

    base_argv = ["--profile", profile] if profile else []
    mode_argv = ["--mode", mode]

    # Each source needs its own argv — deferred imports happen inside SOURCES.
    # We map source.id → runner lambda; entries not in this dict are skipped.
    def _get_runners() -> dict[str, Callable[[], None]]:
        # Imports deferred to avoid heavy initialisation at module load.
        from lawgraph.cli.retrieve_bwb import main as retrieve_bwb_main
        from lawgraph.cli.retrieve_echr import main as retrieve_echr_main
        from lawgraph.cli.retrieve_eerstekamer import main as retrieve_eerstekamer_main
        from lawgraph.cli.retrieve_eurlex import main as retrieve_eurlex_main
        from lawgraph.cli.retrieve_rechtspraak import main as retrieve_rechtspraak_main
        from lawgraph.cli.retrieve_staatsblad import main as retrieve_staatsblad_main
        from lawgraph.cli.retrieve_staatscourant import (
            main as retrieve_staatscourant_main,
        )
        from lawgraph.cli.retrieve_tk import main as retrieve_tk_main
        from lawgraph.cli.retrieve_tk_dossiers import main as retrieve_tk_dossiers_main
        from lawgraph.cli.retrieve_verdragenbank import (
            main as retrieve_verdragenbank_main,
        )

        def tk_runner() -> None:
            retrieve_tk_main(
                argv=[*base_argv, *mode_argv, "--since-days", str(since_days)]
            )

        def tk_dossiers_runner() -> None:
            since_str = str(since_days) + "d"
            extra = [
                "--since",
                since_str,
                "--skip-personen",
                "--stemmingen-since",
                since_str,
                "--documents-since",
                since_str,
            ]
            retrieve_tk_dossiers_main(argv=[*base_argv, *extra])

        def rechtspraak_runner() -> None:
            retrieve_rechtspraak_main(
                argv=[*base_argv, *mode_argv, "--since-days", str(since_days)]
            )

        def eurlex_runner() -> None:
            retrieve_eurlex_main(argv=[*base_argv, *mode_argv])

        def bwb_runner() -> None:
            retrieve_bwb_main(argv=[*base_argv, *mode_argv])

        def staatsblad_runner() -> None:
            retrieve_staatsblad_main(argv=[*base_argv])

        def staatscourant_runner() -> None:
            retrieve_staatscourant_main(argv=[*base_argv, *mode_argv])

        def eerstekamer_runner() -> None:
            retrieve_eerstekamer_main(argv=[*base_argv, *mode_argv])

        def echr_runner() -> None:
            retrieve_echr_main(argv=[*base_argv, *mode_argv])

        def verdragenbank_runner() -> None:
            # Verdragenbank SPARQL has no incremental mode; always full.
            retrieve_verdragenbank_main(argv=[*base_argv])

        return {
            "tk": tk_runner,
            "tk_dossiers": tk_dossiers_runner,
            "rechtspraak": rechtspraak_runner,
            "eurlex": eurlex_runner,
            "bwb": bwb_runner,
            "staatsblad": staatsblad_runner,
            "staatscourant": staatscourant_runner,
            "eerstekamer": eerstekamer_runner,
            "echr": echr_runner,
            "verdragenbank": verdragenbank_runner,
        }

    runners = _get_runners()

    steps = [
        (source.display_name, source.retrieve_skip_env or "", runners[source.id])
        for source in SOURCES
        if source.retrieve_main is not None and source.id in runners
    ]

    results: list[tuple[str, str]] = []
    for name, env_var, runner in steps:
        if env_var and _should_skip(env_var):
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
