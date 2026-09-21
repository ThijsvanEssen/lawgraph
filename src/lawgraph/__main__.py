"""The ``lawgraph`` command (also ``python -m lawgraph``).

    lawgraph <retrieve|normalize|semantic> <source|all> [options]
    lawgraph <bootstrap|check|expand-graph|fill-gaps> [options]
    lawgraph sources

Sources and their order come from ``lawgraph.sources.registry``. This is the one place
that sets up logging and ends the process: 0 when the command went well, 1 when it failed,
2 for a command line that cannot be read (argparse).
"""

from __future__ import annotations

import sys

from lawgraph.commands.bootstrap import main as bootstrap
from lawgraph.commands.check import main as check
from lawgraph.commands.expand_graph import main as expand_graph
from lawgraph.commands.fill_gaps import main as fill_gaps
from lawgraph.core.logging import setup_logging
from lawgraph.pipelines.command import Command
from lawgraph.pipelines.execution import State, execute
from lawgraph.pipelines.orchestration import normalize_all, retrieve_all, semantic_all
from lawgraph.sources.registry import SOURCES, describe

_COMMANDS: dict[str, Command] = {
    "bootstrap": bootstrap,
    "check": check,
    "expand-graph": expand_graph,
    "fill-gaps": fill_gaps,
}
_PHASE_ALL: dict[str, Command] = {
    "retrieve": retrieve_all,
    "normalize": normalize_all,
    "semantic": semantic_all,
}


def _build_dispatch() -> dict[str, dict[str, Command]]:
    """phase -> CLI source name -> ``main(argv)``; ``tk_dossiers`` becomes ``tk-dossiers``."""
    dispatch: dict[str, dict[str, Command]] = {}
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


def _usage(dispatch: dict[str, dict[str, Command]]) -> str:
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
        label, chosen, options, description = command, _COMMANDS[command], rest, ""
    elif command in dispatch and rest and rest[0] in dispatch[command]:
        label, chosen, options = (
            f"{command} {rest[0]}",
            dispatch[command][rest[0]],
            rest[1:],
        )
        description = describe(command, rest[0])
    else:
        print(_usage(dispatch), file=sys.stderr)
        sys.exit(2)

    setup_logging()
    outcome = execute(label, chosen, options, description=description)
    if outcome.state is State.FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
