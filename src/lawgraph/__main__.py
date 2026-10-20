"""The ``lawgraph`` command (also ``python -m lawgraph``).

    lawgraph <retrieve|normalize|semantic> <pipeline|all> [options]
    lawgraph <command> [options]      (``lawgraph --help`` lists the commands)
    lawgraph sources
    lawgraph openapi

Sources and their order come from ``lawgraph.sources.registry``. This is the one place
that sets up logging and ends the process: 0 when the command went well, 1 when it failed,
2 for a command line that cannot be read (an unknown command, or argparse), 3 when a source
refused us and the rest went on. With ``LAWGRAPH_OUTCOME_FILE`` it writes there why the
command ended so, in one line (``Outcome.reason``), for runs.log and the alert.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

from lawgraph.commands.bootstrap import main as bootstrap
from lawgraph.commands.built_beforehand import main as built_beforehand
from lawgraph.commands.check import main as check
from lawgraph.commands.code_families import main as code_families
from lawgraph.commands.courts import main as courts
from lawgraph.commands.curated import main as curated
from lawgraph.commands.expand_graph import main as expand_graph
from lawgraph.commands.feed_events import main as feed_events
from lawgraph.commands.gaps import main as gaps
from lawgraph.commands.ministries import main as ministries
from lawgraph.commands.poll import main as poll
from lawgraph.commands.search_candidates import main as search_candidates
from lawgraph.commands.search_stats import main as search_stats
from lawgraph.commands.sitemaps import main as sitemaps
from lawgraph.commands.succession_gaps import main as succession_gaps
from lawgraph.commands.verify import main as verify
from lawgraph.config.settings import OUTCOME_FILE
from lawgraph.core.logging import log_step, setup_logging
from lawgraph.pipelines.command import (
    EXIT_UNAVAILABLE,
    Main,
    Outcome,
    State,
    run_command,
)
from lawgraph.pipelines.orchestration import normalize_all, retrieve_all, semantic_all
from lawgraph.sources.addresses import PHASES, SOURCES
from lawgraph.sources.registry import PIPELINES, find

_COMMANDS: dict[str, Main] = {
    "bootstrap": bootstrap,
    "built-beforehand": built_beforehand,
    "check": check,
    "code-families": code_families,
    "courts": courts,
    "curated": curated,
    "expand-graph": expand_graph,
    "feed-events": feed_events,
    "gaps": gaps,
    "ministries": ministries,
    "poll": poll,
    "search-candidates": search_candidates,
    "search-stats": search_stats,
    "sitemaps": sitemaps,
    "succession-gaps": succession_gaps,
    "verify": verify,
}
_PHASE_ALL: dict[str, Main] = {
    "retrieve": retrieve_all,
    "normalize": normalize_all,
    "semantic": semantic_all,
}


# What asks for the help of lawgraph, or of a command after it.
_HELP = frozenset({"-h", "--help"})


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
                lines.append(f"    {pipeline.address:<34} {pipeline.description}")
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
        "       lawgraph openapi     the OpenAPI schema of the API, without a server",
        "",
    ]
    lines += ["Add --help after a command for its options."]
    return "\n".join(lines)


def _openapi() -> str:
    """The OpenAPI schema of the API as it serves ``/openapi.json``; ``docs/openapi.json``
    is this, and the front end generates its types from it."""
    # imported only here: the app sets up its routes and the logging of the API
    from lawgraph.api.app import app

    return json.dumps(app.openapi(), indent=2, ensure_ascii=False)


def _chosen(argv: list[str]) -> tuple[str, Main, list[str], str] | None:
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


def _unknown(argv: list[str]) -> str:
    """What is wrong with a command line ``_chosen`` found nothing for, with the nearest name."""
    command, rest = argv[0], argv[1:]
    if command in PHASES:
        if not rest:
            return f"{command} needs a pipeline or all"
        names = ["all", *(pipeline.name for pipeline in PIPELINES[command])]
        return _nearest(f"unknown pipeline '{rest[0]}' of {command}", rest[0], names)
    names = [*_COMMANDS, *PHASES, "sources", "openapi"]
    return _nearest(f"unknown command '{command}'", command, names)


def _nearest(said: str, typed: str, names: list[str]) -> str:
    near = difflib.get_close_matches(typed, names, n=1)
    return f"{said}; did you mean '{near[0]}'?" if near else said


# How much of the reason goes in runs.log and the alert; the log has all of it.
REASON_CHARS = 300


def _write_outcome(outcome: Outcome) -> None:
    if not OUTCOME_FILE:
        return
    said = outcome.reason
    if len(said) > REASON_CHARS:
        said = said[: REASON_CHARS - 2].rsplit(" ", 1)[0] + " …"
    Path(OUTCOME_FILE).write_text(said + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in _HELP:
        print(_usage())
        return
    if argv[0] == "sources":
        print(_sources_overview())
        return
    if argv[0] == "openapi":
        print(_openapi())
        return

    chosen = _chosen(argv)
    if chosen is None:
        print(f"lawgraph: {_unknown(argv)}\n\n{_usage()}", file=sys.stderr)
        sys.exit(2)

    label, command, options, description = chosen
    if _HELP.intersection(options):
        # the help of the command alone: no log lines, and its usage names the command
        with log_step(label):
            command(options)  # argparse prints the help and ends the process
        return
    setup_logging()
    outcome = run_command(label, command, options, description=description)
    _write_outcome(outcome)
    if outcome.state is State.FAILED:
        sys.exit(1)
    if outcome.state is State.UNAVAILABLE:
        sys.exit(EXIT_UNAVAILABLE)


if __name__ == "__main__":
    main()
