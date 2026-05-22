"""Bootstrap the LawGraph database from scratch.

Runs all pipeline phases in the correct sequence:
  1. retrieve_all  --mode=full
  2. normalize_all
  3. semantic_all  [--strict]
  4. expand_graph  --max-iterations
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv

from lawgraph.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Bootstrap the LawGraph database from scratch by running all pipeline phases."
    )
    parser.add_argument("--max-expand", type=int, default=5, metavar="N")
    parser.add_argument("--skip-expand", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--skip-retrieve", action="store_true")
    args = parser.parse_args(argv)

    logger.info("bootstrap: starting (max_expand=%d, strict=%s).", args.max_expand, args.strict)

    from lawgraph.commands.expand_graph import main as expand_main
    from lawgraph.pipelines.orchestration import run_normalize_all as normalize_main
    from lawgraph.pipelines.orchestration import run_retrieve_all as retrieve_main
    from lawgraph.pipelines.orchestration import run_semantic_all as semantic_main

    def _phase(name: str, fn: Callable[..., Any], phase_argv: list[str]) -> None:
        logger.info("bootstrap: phase '%s' starting.", name)
        try:
            fn(argv=phase_argv)
        except SystemExit as exc:
            if exc.code not in (None, 0):
                logger.error("bootstrap: phase '%s' exited with code %s.", name, exc.code)
                if args.strict:
                    sys.exit(exc.code)
                return
        except Exception as exc:
            logger.error("bootstrap: phase '%s' raised: %s", name, exc)
            if args.strict:
                sys.exit(1)
            return
        logger.info("bootstrap: phase '%s' completed.", name)

    if not args.skip_retrieve:
        _phase("retrieve_all", retrieve_main, ["--mode", "full"])

    _phase("normalize_all", normalize_main, [])

    semantic_argv = ["--strict"] if args.strict else []
    _phase("semantic_all", semantic_main, semantic_argv)

    if not args.skip_expand:
        expand_argv = ["--max-iterations", str(args.max_expand)]
        _phase("expand_graph", expand_main, expand_argv)

    logger.info("bootstrap: all phases complete.")


if __name__ == "__main__":
    main()
