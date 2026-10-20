"""The address of a pipeline, read from where it lives (``registry`` registers them).

``lawgraph.pipelines.semantic.rechtspraak_citations`` is ``semantic rechtspraak-citations``:
its phase is its package and its name (``rechtspraak-citations``) its module, a source of
``SOURCES`` and a part. The name is also the source of the edges it writes (``edge_source``),
by which it removes its own stale ones.
"""

from __future__ import annotations

from typing import Literal, get_args

Phase = Literal["retrieve", "normalize", "semantic"]
PHASES: tuple[Phase, ...] = get_args(Phase)

# Where records come from; ``graph``: no source of its own, the graph as a whole.
GRAPH = "graph"
SOURCES: dict[str, str] = {
    "tk": "Tweede Kamer",
    "rechtspraak": "Rechtspraak",
    "eurlex": "EUR-Lex",
    "bwb": "BWB (wetten.overheid.nl)",
    "staatsblad": "Staatsblad",
    "staatscourant": "Staatscourant",
    "eerstekamer": "Eerste Kamer",
    "echr": "ECHR (HUDOC)",
    "verdragenbank": "Verdragenbank",
    "rijksoverheid": "Rijksoverheid (rijksoverheid.nl)",
    "tooi": "TOOI (standaarden.overheid.nl)",
    "kiesraad": "Kiesraad (verkiezingsuitslagen.nl)",
    GRAPH: "The whole graph",
}


def address_of(module: str, function: str) -> tuple[Phase, str, str | None]:
    """``(phase, source, part)`` from where a pipeline lives.

    ``lawgraph.pipelines.semantic.rechtspraak_citations`` is ``semantic
    rechtspraak-citations``; a retrieve that parses options of its own is a function of
    ``retrieve_commands`` named ``retrieve_<source>[_<part>]``.
    """
    package, _, stem = module.rpartition(".")
    phase = package.rpartition(".")[2]
    if stem == "retrieve_commands":
        phase, stem = "retrieve", function.removeprefix("retrieve_")
    if phase not in PHASES:
        raise ValueError(f"{module}.{function} is not in a package of a phase")
    source = max(
        (s for s in SOURCES if f"{stem}_".startswith(f"{s}_")), key=len, default=""
    )
    if not source:
        raise ValueError(f"{module}: '{stem}' does not start with a source of SOURCES")
    part = stem[len(source) + 1 :].replace("_", "-") or None
    return phase, source, part


def name_of(source: str, part: str | None) -> str:
    """``tk-dossiers``: the source and the part."""
    return f"{source}-{part}" if part else source


def edge_source(module: str) -> str:
    """The source a pipeline writes on its edges: the name of the pipeline of *module*
    (``tk-dossiers`` for ``lawgraph.pipelines.normalize.tk_dossiers``)."""
    _, source, part = address_of(module, "")
    return name_of(source, part)
