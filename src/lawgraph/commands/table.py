"""The commands of ``lawgraph`` besides the pipelines of the registry, each with what it does
in plain Dutch: the words an alert names it by (``lawgraph.alert``). A pipeline has those in
the registry (``Pipeline.plain``)."""

from __future__ import annotations

from dataclasses import dataclass

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
from lawgraph.pipelines.command import Main
from lawgraph.pipelines.orchestration import normalize_all, retrieve_all, semantic_all
from lawgraph.sources.addresses import Phase


@dataclass(frozen=True)
class Entry:
    main: Main
    plain: str  # "de controle": lower case, as it stands in a sentence


COMMANDS: dict[str, Entry] = {
    "bootstrap": Entry(bootstrap, "het vullen van een lege database"),
    "built-beforehand": Entry(
        built_beforehand, "het voorbereiden van de indexen van een nieuwe versie"
    ),
    "check": Entry(check, "de controle"),
    "code-families": Entry(code_families, "het bijwerken van de wetboeken"),
    "courts": Entry(courts, "het bijwerken van de lijst van gerechten"),
    "curated": Entry(
        curated, "het bijwerken van de lijsten die met de hand zijn gemaakt"
    ),
    "expand-graph": Entry(expand_graph, "het aanvullen van wat nog ontbreekt"),
    "feed-events": Entry(feed_events, "het bijwerken van de nieuwsfeed"),
    "gaps": Entry(gaps, "het tellen van wat nog ontbreekt"),
    "ministries": Entry(ministries, "het bijwerken van de lijst van ministeries"),
    "poll": Entry(poll, "het ophalen van nieuwe stukken"),
    "search-candidates": Entry(
        search_candidates, "het bijwerken van de zoeksuggesties"
    ),
    "search-stats": Entry(search_stats, "het bijhouden van wat er gezocht is"),
    "sitemaps": Entry(sitemaps, "het maken van de sitemaps"),
    "succession-gaps": Entry(
        succession_gaps, "het tellen van wat de transponeringstabellen niet plaatsen"
    ),
    "verify": Entry(verify, "het nalopen van de kabinetten"),
}

# ``lawgraph <phase> all``: every pipeline of the phase.
PHASE_ALL: dict[Phase, Entry] = {
    "retrieve": Entry(retrieve_all, "het ophalen bij de bronnen"),
    "normalize": Entry(normalize_all, "het verwerken van wat is opgehaald"),
    "semantic": Entry(semantic_all, "het leggen van verbanden"),
}
