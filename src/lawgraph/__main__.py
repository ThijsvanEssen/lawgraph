"""The ``lawgraph`` command (also ``python -m lawgraph``).

    lawgraph <retrieve|normalize|semantic> <source|all> [options]
    lawgraph <bootstrap|expand-graph|fill-gaps> [options]
    lawgraph sources

Sources and their order come from ``lawgraph.sources.registry``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from lawgraph.commands.bootstrap import main as bootstrap
from lawgraph.commands.expand_graph import main as expand_graph
from lawgraph.commands.fill_gaps import main as fill_gaps
from lawgraph.core.logging import get_logger, log_step, setup_logging
from lawgraph.pipelines.orchestration import (
    run_normalize_all,
    run_retrieve_all,
    run_semantic_all,
)
from lawgraph.sources.registry import SOURCES, describe

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


def _sources_overview() -> str:
    """Every source with what each of its phases does, in the order the phases run."""
    lines = ["Sources, in registry order (the order of `<phase> all`):", ""]
    for source in SOURCES:
        lines.append(f"{source.id.replace('_', '-')}  —  {source.display_name}")
        for phase in ("retrieve", "normalize", "semantic"):
            if getattr(source, f"{phase}_main") is None:
                continue
            note = ""
            if phase == "retrieve" and source.retrieve_argv_builder is None:
                note = " [manual: not in retrieve all]"
            text = source.descriptions.get(phase, "(no description)")
            lines.append(f"    {phase:<10} {text}{note}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _usage(dispatch: dict[str, dict[str, Main]]) -> str:
    lines = ["Usage: lawgraph <phase> <source> [options]", ""]
    lines += [
        f"  {phase}: {', '.join(sorted(mains))}" for phase, mains in dispatch.items()
    ]
    lines += ["", f"       lawgraph <{'|'.join(_COMMANDS)}> [options]", ""]
    lines += ["       lawgraph sources     what every source and phase does", ""]
    lines += ["Add --help after a command for its options."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    dispatch = _build_dispatch()

    if not argv or argv[0] in ("-h", "--help"):
        print(_usage(dispatch))
        return

    command, rest = argv[0], argv[1:]
    if command == "sources":
        print(_sources_overview())
        return
    if command in _COMMANDS:
        setup_logging()
        with log_step(command):
            _COMMANDS[command](argv=rest)
        return

    if command not in dispatch or not rest or rest[0] not in dispatch[command]:
        print(_usage(dispatch), file=sys.stderr)
        sys.exit(2)

    setup_logging()
    with log_step(f"{command} {rest[0]}"):
        description = describe(command, rest[0])
        if description:
            get_logger(__name__).info("%s", description)
        dispatch[command][rest[0]](argv=rest[1:])


if __name__ == "__main__":
    main()
