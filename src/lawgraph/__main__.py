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
from lawgraph.pipelines.command import Command, State, run_command
from lawgraph.pipelines.orchestration import normalize_all, retrieve_all, semantic_all
from lawgraph.sources.registry import PHASES, PIPELINES, SOURCES, find

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


def _sources_overview() -> str:
    """Every source with its pipelines, per phase in the order the phase runs them."""
    lines = [
        "Pipelines per source; within a phase, `<phase> all` runs registry order.",
        "",
    ]
    for source, display_name in SOURCES.items():
        lines.append(f"{source}  —  {display_name}")
        for phase in PHASES:
            for pipeline in PIPELINES[phase]:
                if pipeline.source != source:
                    continue
                manual = phase == "retrieve" and pipeline.argv_for_all is None
                note = " [manual: not in retrieve all]" if manual else ""
                lines.append(f"    {pipeline.address:<34} {pipeline.description}{note}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _usage() -> str:
    lines = ["Usage: lawgraph <phase> <pipeline|all> [options]", ""]
    lines += [
        f"  {phase}: all, {', '.join(pipeline.name for pipeline in PIPELINES[phase])}"
        for phase in PHASES
    ]
    lines += ["", f"       lawgraph <{'|'.join(_COMMANDS)}> [options]", ""]
    lines += [
        "       lawgraph sources     every pipeline per source, and what it does",
        "",
    ]
    lines += ["Add --help after a command for its options."]
    return "\n".join(lines)


def _chosen(argv: list[str]) -> tuple[str, Command, list[str], str] | None:
    """``(label, command, options, description)`` of what was typed, or None."""
    command, rest = argv[0], argv[1:]
    if command in _COMMANDS:
        return command, _COMMANDS[command], rest, ""
    if command in _PHASE_ALL and rest and rest[0] == "all":
        return f"{command} all", _PHASE_ALL[command], rest[1:], ""
    pipeline = find(command, rest[0]) if rest else None
    if pipeline is None:
        return None
    return pipeline.address, pipeline.command, rest[1:], pipeline.description


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(_usage())
        return
    if argv[0] == "sources":
        print(_sources_overview())
        return

    chosen = _chosen(argv)
    if chosen is None:
        print(_usage(), file=sys.stderr)
        sys.exit(2)

    setup_logging()
    label, command, options, description = chosen
    outcome = run_command(label, command, options, description=description)
    if outcome.state is State.FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
