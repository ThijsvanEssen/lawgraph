"""Iteratively expand the graph until no new documents are discovered."""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

from lawgraph.core.logging import get_logger, setup_logging
from lawgraph.db import ArangoStore

logger = get_logger(__name__)


def _count_stubs(store: ArangoStore) -> int:
    aql = """
    RETURN {
        stub_articles: LENGTH(FOR d IN instrument_articles FILTER d.props.stub == true RETURN 1),
        stub_judgments: LENGTH(FOR j IN judgments FILTER j.props.stub == true RETURN 1)
    }
    """
    try:
        row = next(iter(store.query(aql)), {})
    except Exception as exc:
        logger.debug("Could not count stubs: %s", exc)
        return 0
    return (row.get("stub_articles") or 0) + (row.get("stub_judgments") or 0)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Expand the graph by iterating fill_gaps → normalize_all → semantic_all.",
    )
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    store = ArangoStore()

    from lawgraph.commands.fill_gaps import main as fill_gaps_main
    from lawgraph.pipelines.orchestration import run_normalize_all as normalize_all_main
    from lawgraph.pipelines.orchestration import run_semantic_all as semantic_all_main

    logger.info(
        "expand_graph: starting (max_iterations=%d, dry_run=%s).",
        args.max_iterations,
        args.dry_run,
    )

    iteration = 0
    total_resolved = 0

    for iteration in range(1, args.max_iterations + 1):
        logger.info("expand_graph: iteration %d/%d", iteration, args.max_iterations)

        before = _count_stubs(store)

        fill_argv = ["--apply"] if not args.dry_run else []

        try:
            fill_gaps_main(argv=fill_argv)
        except SystemExit as exc:
            if exc.code not in (None, 0):
                logger.warning(
                    "expand_graph: fill_gaps exited with code %s (iteration %d).",
                    exc.code,
                    iteration,
                )
        except Exception as exc:
            logger.error(
                "expand_graph: fill_gaps raised an exception (iteration %d): %s",
                iteration,
                exc,
            )

        if args.dry_run:
            logger.info("expand_graph: dry-run mode, stopping after diagnosis.")
            break

        after = _count_stubs(store)
        resolved = before - after

        if resolved <= 0:
            logger.info(
                "expand_graph: no new documents found in iteration %d, graph is stable.",
                iteration,
            )
            break

        total_resolved += resolved
        logger.info(
            "expand_graph: %d stub(s) resolved in iteration %d — running normalize + semantic.",
            resolved,
            iteration,
        )

        try:
            normalize_all_main(argv=[])
        except SystemExit as exc:
            if exc.code not in (None, 0):
                logger.warning(
                    "expand_graph: normalize_all exited with code %s (iteration %d).",
                    exc.code,
                    iteration,
                )
        except Exception as exc:
            logger.error(
                "expand_graph: normalize_all raised an exception (iteration %d): %s",
                iteration,
                exc,
            )

        try:
            semantic_all_main(argv=[])
        except SystemExit as exc:
            if exc.code not in (None, 0):
                logger.warning(
                    "expand_graph: semantic_all exited with code %s (iteration %d).",
                    exc.code,
                    iteration,
                )
        except Exception as exc:
            logger.error(
                "expand_graph: semantic_all raised an exception (iteration %d): %s",
                iteration,
                exc,
            )

    logger.info(
        "expand_graph: completed %d iteration(s), %d total stub(s) resolved.",
        iteration,
        total_resolved,
    )


if __name__ == "__main__":
    main()
