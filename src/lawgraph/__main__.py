"""The ``lawgraph`` command (also ``python -m lawgraph``).

    lawgraph <retrieve|normalize|semantic> <source|all> [options]
    lawgraph <bootstrap|expand-graph|fill-gaps> [options]

Sources and their order come from ``lawgraph.sources.registry``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from lawgraph.commands.bootstrap import main as bootstrap
from lawgraph.commands.expand_graph import main as expand_graph
from lawgraph.commands.fill_gaps import main as fill_gaps
from lawgraph.pipelines.orchestration import (
    run_normalize_all,
    run_retrieve_all,
    run_semantic_all,
)
from lawgraph.sources.registry import SOURCES

Main = Callable[..., None]

_COMMANDS: dict[str, Main] = {
    "bootstrap": bootstrap,
    "expand-graph": expand_graph,
    "fill-gaps": fill_gaps,
}
_PHASE_ALL: dict[str, Main] = {
    "retrieve": run_retrieve_all,
    "normalize": run_normalize_all,
    "semantic": run_semantic_all,
}


def _build_dispatch() -> dict[str, dict[str, Main]]:
    """phase -> CLI source name -> ``main(argv)``; ``tk_dossiers`` becomes ``tk-dossiers``."""
    dispatch: dict[str, dict[str, Main]] = {}
    for phase, run_all in _PHASE_ALL.items():
        dispatch[phase] = {"all": run_all}
        for source in SOURCES:
            main = getattr(source, f"{phase}_main")
            if main is not None:
                dispatch[phase][source.id.replace("_", "-")] = main
    return dispatch


def _usage(dispatch: dict[str, dict[str, Main]]) -> str:
    lines = ["Usage: lawgraph <phase> <source> [options]", ""]
    lines += [
        f"  {phase}: {', '.join(sorted(mains))}" for phase, mains in dispatch.items()
    ]
    lines += ["", f"       lawgraph <{'|'.join(_COMMANDS)}> [options]", ""]
    lines += ["Add --help after a command for its options."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    dispatch = _build_dispatch()

    if not argv or argv[0] in ("-h", "--help"):
        print(_usage(dispatch))
        return

    command, rest = argv[0], argv[1:]
    if command in _COMMANDS:
        _COMMANDS[command](argv=rest)
        return

    if command not in dispatch or not rest or rest[0] not in dispatch[command]:
        print(_usage(dispatch), file=sys.stderr)
        sys.exit(2)

    dispatch[command][rest[0]](argv=rest[1:])


if __name__ == "__main__":
    main()
