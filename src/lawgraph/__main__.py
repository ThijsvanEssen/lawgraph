"""Unified CLI dispatcher for lawgraph.

Invoked as ``lawgraph <phase> <source> [options]`` (via the entry point) or
``python -m lawgraph <phase> <source> [options]``.

Phases:   retrieve | normalize | semantic
Sources:  any source ID from the registry (with hyphens), or ``all``

Examples:
    lawgraph normalize bwb --since 7d
    lawgraph normalize all
    lawgraph retrieve tk --mode full
    lawgraph semantic judgment-citations --since-days 30
    lawgraph bootstrap
    lawgraph expand-graph
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from dotenv import load_dotenv

from lawgraph.core.logging import setup_logging


def _build_dispatch() -> dict[str, dict[str, Callable]]:
    """Build the phase → source → main() dispatch table (deferred imports)."""
    from lawgraph.pipelines.orchestration import run_normalize_all as norm_all
    from lawgraph.pipelines.orchestration import run_retrieve_all as retr_all
    from lawgraph.pipelines.orchestration import run_semantic_all as sem_all
    from lawgraph.sources.registry import SOURCES

    # Build source-keyed dicts from the registry (id with underscores → hyphens for CLI)
    retrieve_map: dict[str, Callable] = {"all": retr_all}
    normalize_map: dict[str, Callable] = {"all": norm_all}
    semantic_map: dict[str, Callable] = {"all": sem_all}

    for source in SOURCES:
        cli_key = source.id.replace("_", "-")
        if source.retrieve_main is not None:
            retrieve_map[cli_key] = source.retrieve_main
        if source.normalize_main is not None:
            normalize_map[cli_key] = source.normalize_main
        if source.semantic_main is not None:
            semantic_map[cli_key] = source.semantic_main

    # Retrieve-only sources not covered by retrieve_argv_builder (ad-hoc)
    from lawgraph.pipelines.retrieve_cli import retrieve_bwb_history, retrieve_tk_content

    retrieve_map["bwb-history"] = retrieve_bwb_history
    retrieve_map["tk-content"] = retrieve_tk_content

    return {
        "retrieve": retrieve_map,
        "normalize": normalize_map,
        "semantic": semantic_map,
    }


def _print_help(dispatch: dict[str, dict[str, Callable]] | None = None) -> None:
    print("Usage: lawgraph <phase> <source> [options]")
    print()
    print("Phases and sources:")
    if dispatch:
        for phase, sources in dispatch.items():
            print(f"  {phase}: {', '.join(sorted(sources))}")
    else:
        print("  retrieve | normalize | semantic")
    print()
    print("Special commands:")
    print("  lawgraph bootstrap            Bootstrap database from scratch")
    print("  lawgraph expand-graph         Iterative fill-gaps loop")
    print("  lawgraph fill-gaps            Diagnose and fill knowledge gaps")
    print()
    print("Pass --help after a source name for source-specific options:")
    print("  lawgraph normalize bwb --help")


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    setup_logging()

    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        _print_help()
        return

    phase = argv[0]
    rest = argv[1:]

    if phase == "bootstrap":
        from lawgraph.commands.bootstrap import main as bootstrap_main
        bootstrap_main(argv=rest)
        return
    if phase == "expand-graph":
        from lawgraph.commands.expand_graph import main as expand_main
        expand_main(argv=rest)
        return
    if phase == "fill-gaps":
        from lawgraph.commands.fill_gaps import main as fill_gaps_main
        fill_gaps_main(argv=rest)
        return

    dispatch = _build_dispatch()

    if phase not in dispatch:
        print(f"error: unknown phase '{phase}'\n", file=sys.stderr)
        _print_help(dispatch)
        sys.exit(1)

    phase_dispatch = dispatch[phase]

    if not rest or rest[0] in ("-h", "--help"):
        print(f"Usage: lawgraph {phase} <source> [options]")
        print(f"Sources: {', '.join(sorted(phase_dispatch))}")
        return

    source = rest[0]
    source_argv = rest[1:]

    if source not in phase_dispatch:
        print(f"error: unknown source '{source}' for phase '{phase}'\n", file=sys.stderr)
        print(f"Available: {', '.join(sorted(phase_dispatch))}", file=sys.stderr)
        sys.exit(1)

    phase_dispatch[source](argv=source_argv)


if __name__ == "__main__":
    main()
