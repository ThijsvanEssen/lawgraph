"""Every pipeline, per phase, in the order it runs.

A **phase** is ``retrieve``, ``normalize`` or ``semantic``. A **source** is where records
come from (``SOURCES``; ``graph`` is what works on the whole graph). A **pipeline** is one
unit of work in one phase for one source, and it has an address::

    <phase> <source>[-<part>]        normalize tk-dossiers, semantic rechtspraak-citations

The address is what one types after ``lawgraph``, the label on its log lines, its skip
variable (``LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS``) and its module
(``pipelines/normalize/tk_dossiers.py`` holding ``TKDossiersNormalizePipeline``). It is
written nowhere in this file: ``_pipeline`` reads it from the module of what it registers
(``addresses.address_of``), and a class whose name does not follow is refused when this
module is imported. Its name is also the source on the edges it writes
(``addresses.edge_source``), where a stored label allows. A pipeline
that links two sources belongs to the one its edges start at, the text that is read.

The source is the stored key of the site (``eerstekamer`` in ``raw_sources.source``, the edge
sources and the addresses); what reads it is named by the chamber, ``core/ek_<part>.py``
for ``eerstekamer-<part>``, as ``tk`` is for the Tweede Kamer.

The lists below are the order of ``<phase> all``; a pipeline that reads edges written by
another comes after it.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
)
from lawgraph.config.sources import (
    BWB_SEARCH,
    CELLAR,
    EERSTEKAMER_SITE,
    HUDOC,
    KIESRAAD,
    KOOP_REPOSITORY,
    RECHTSPRAAK,
    RIJKSOVERHEID,
    TOOI,
    TWEEDE_KAMER,
)
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.pipelines import retrieve_commands as commands
from lawgraph.pipelines.command import (
    Command,
    HandWritten,
    Main,
    PipelineCommand,
    add_limit_argument,
)
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.normalize.bwb_history import BWBHistoryNormalizePipeline
from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline
from lawgraph.pipelines.normalize.eerstekamer import EerstekamerNormalizePipeline
from lawgraph.pipelines.normalize.eerstekamer_agenda import (
    EerstekamerAgendaNormalizePipeline,
)
from lawgraph.pipelines.normalize.eerstekamer_bills import (
    EerstekamerBillsNormalizePipeline,
)
from lawgraph.pipelines.normalize.eerstekamer_composition import (
    EerstekamerCompositionNormalizePipeline,
)
from lawgraph.pipelines.normalize.eerstekamer_motions import (
    EerstekamerMotionsNormalizePipeline,
)
from lawgraph.pipelines.normalize.eerstekamer_mutations import (
    EerstekamerMutationsNormalizePipeline,
)
from lawgraph.pipelines.normalize.eerstekamer_persons import (
    EerstekamerPersonsNormalizePipeline,
)
from lawgraph.pipelines.normalize.eerstekamer_votes import (
    EerstekamerVotesNormalizePipeline,
)
from lawgraph.pipelines.normalize.eurlex import EurlexNormalizePipeline
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from lawgraph.pipelines.normalize.rijksoverheid import RijksoverheidNormalizePipeline
from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline
from lawgraph.pipelines.normalize.staatsblad_laws import (
    StaatsbladLawsNormalizePipeline,
)
from lawgraph.pipelines.normalize.staatscourant import StaatscourantNormalizePipeline
from lawgraph.pipelines.normalize.tk import TKNormalizePipeline
from lawgraph.pipelines.normalize.tk_case_actors import TKCaseActorsNormalizePipeline
from lawgraph.pipelines.normalize.tk_content import TKContentNormalizePipeline
from lawgraph.pipelines.normalize.tk_document_links import (
    TKDocumentLinksNormalizePipeline,
)
from lawgraph.pipelines.normalize.tk_dossiers import TKDossiersNormalizePipeline
from lawgraph.pipelines.normalize.verdragenbank import VerdragenbankNormalizePipeline
from lawgraph.pipelines.retrieve.eerstekamer_composition import (
    EerstekamerCompositionRetrievePipeline,
)
from lawgraph.pipelines.retrieve.eerstekamer_composition_observed import (
    EerstekamerCompositionObservedRetrievePipeline,
)
from lawgraph.pipelines.retrieve.eerstekamer_motions import (
    EerstekamerMotionsRetrievePipeline,
)
from lawgraph.pipelines.retrieve.eerstekamer_mutations import (
    EerstekamerMutationsRetrievePipeline,
)
from lawgraph.pipelines.retrieve.eerstekamer_persons import (
    EerstekamerPersonsRetrievePipeline,
)
from lawgraph.pipelines.retrieve.kiesraad import KiesraadRetrievePipeline
from lawgraph.pipelines.retrieve.rechtspraak_instanties import (
    RechtspraakInstantiesRetrievePipeline,
)
from lawgraph.pipelines.retrieve.rijksoverheid import RijksoverheidRetrievePipeline
from lawgraph.pipelines.retrieve.staatscourant_posts import (
    StaatscourantPostsRetrievePipeline,
)
from lawgraph.pipelines.retrieve.tk_transposition_tables import (
    TKTranspositionTablesRetrievePipeline,
)
from lawgraph.pipelines.retrieve.tooi import TooiRetrievePipeline
from lawgraph.pipelines.retrieve_commands import (
    AddArgs,
    Reads,
    RetrieveCommand,
    RetrieveMode,
    Run,
)
from lawgraph.pipelines.semantic import (
    graph_derive,
    graph_light,
    graph_list_stats,
    tk_dictum,
)
from lawgraph.pipelines.semantic.bwb import BWBSemanticPipeline
from lawgraph.pipelines.semantic.bwb_amendments import BWBAmendmentsSemanticPipeline
from lawgraph.pipelines.semantic.bwb_annexes import BWBAnnexesSemanticPipeline
from lawgraph.pipelines.semantic.bwb_captions import BWBCaptionsSemanticPipeline
from lawgraph.pipelines.semantic.bwb_definitions import BWBDefinitionsSemanticPipeline
from lawgraph.pipelines.semantic.bwb_grondslagen import BWBGrondslagenSemanticPipeline
from lawgraph.pipelines.semantic.bwb_implements import BWBImplementsSemanticPipeline
from lawgraph.pipelines.semantic.bwb_publications import BWBPublicationsSemanticPipeline
from lawgraph.pipelines.semantic.bwb_relation_types import (
    BWBRelationTypesSemanticPipeline,
)
from lawgraph.pipelines.semantic.echr import ECHRSemanticPipeline
from lawgraph.pipelines.semantic.echr_versions import ECHRVersionsSemanticPipeline
from lawgraph.pipelines.semantic.eerstekamer import (
    EerstekamerSemanticPipeline,
)
from lawgraph.pipelines.semantic.eurlex import EurlexSemanticPipeline
from lawgraph.pipelines.semantic.eurlex_cjeu import EurlexCjeuSemanticPipeline
from lawgraph.pipelines.semantic.graph_article_terms import (
    GraphArticleTermsSemanticPipeline,
)
from lawgraph.pipelines.semantic.graph_derive import GraphDeriveSemanticPipeline
from lawgraph.pipelines.semantic.graph_heat import GraphHeatSemanticPipeline
from lawgraph.pipelines.semantic.graph_light import GraphLightSemanticPipeline
from lawgraph.pipelines.semantic.graph_list_stats import GraphListStatsSemanticPipeline
from lawgraph.pipelines.semantic.rechtspraak import (
    RechtspraakSemanticPipeline,
)
from lawgraph.pipelines.semantic.rechtspraak_appeal import (
    RechtspraakAppealSemanticPipeline,
)
from lawgraph.pipelines.semantic.rechtspraak_citations import (
    RechtspraakCitationsSemanticPipeline,
)
from lawgraph.pipelines.semantic.rechtspraak_conclusions import (
    RechtspraakConclusionsSemanticPipeline,
)
from lawgraph.pipelines.semantic.rechtspraak_duplicates import (
    RechtspraakDuplicatesSemanticPipeline,
)
from lawgraph.pipelines.semantic.rechtspraak_referrals import (
    RechtspraakReferralsSemanticPipeline,
)
from lawgraph.pipelines.semantic.rechtspraak_related import (
    RechtspraakRelatedSemanticPipeline,
)
from lawgraph.pipelines.semantic.rechtspraak_series import (
    RechtspraakSeriesSemanticPipeline,
)
from lawgraph.pipelines.semantic.staatsblad import StaatsbladSemanticPipeline
from lawgraph.pipelines.semantic.staatsblad_law_references import (
    StaatsbladLawReferencesSemanticPipeline,
)
from lawgraph.pipelines.semantic.staatscourant import (
    StaatscourantSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk import TKSemanticPipeline
from lawgraph.pipelines.semantic.tk_amendment_articles import (
    TKAmendmentArticlesSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_amends import TKAmendsSemanticPipeline
from lawgraph.pipelines.semantic.tk_cited_papers import (
    TKCitedPapersSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_coalition_votes import (
    TKCoalitionVotesSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_dossier_outcomes import (
    TKDossierOutcomesSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_dossier_relations import (
    TKDossierRelationsSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_dossier_titles import (
    TKDossierTitlesSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_government import TKGovernmentSemanticPipeline
from lawgraph.pipelines.semantic.tk_mvt import TKMvtSemanticPipeline
from lawgraph.pipelines.semantic.tk_mvt_articles import (
    TKMvtArticlesSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_paper_outcomes import (
    TKPaperOutcomesSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_person_duplicates import (
    TKPersonDuplicatesSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_transposition_tables import (
    TKTranspositionTablesSemanticPipeline,
)
from lawgraph.pipelines.semantic.verdragenbank import VerdragenbankSemanticPipeline
from lawgraph.sources.addresses import Phase, address_of, name_of

# How a source is spelled in a class name, where capitalising it is not enough.
_CLASS_PREFIX = {"tk": "TK", "bwb": "BWB", "echr": "ECHR"}


@dataclass(frozen=True)
class RetrieveCtx:
    """Options of ``retrieve all`` that ``argv_for_all`` translates per pipeline."""

    since: str
    mode: RetrieveMode
    window: str | None = None  # full mode: what changed since then; None: everything


@dataclass(frozen=True)
class Pipeline:
    """One pipeline of the registry: its address, its command and how ``retrieve all`` runs it."""

    phase: Phase
    source: str
    part: str | None
    command: Command
    description: str  # printed by ``lawgraph sources`` and in the first log line
    # Retrieve only (every retrieve pipeline has it). ``argv_for_all`` turns the options of
    # ``retrieve all`` into those of the command; ``lane`` is that of the host it talks to
    # (``config/sources.py``), so no host gets two request streams.
    # Retrieve and normalize: ``after`` names pipelines of the same phase that must have
    # ended first, because this one reads what they wrote (normalize: the nodes of the
    # Ordering table in docs/pipelines.md; registry order already keeps them before it).
    argv_for_all: Callable[[RetrieveCtx], list[str]] | None = None
    lane: str = ""
    after: tuple[str, ...] = ()
    # Retrieve only: the command has ``--mode gaps`` (what the graph refers to and lacks),
    # so it is part of ``retrieve all --mode gaps`` and of every round of ``expand-graph``.
    fills_gaps: bool = False
    # Retrieve only: the nodes of a normalize pipeline it chooses its work from (not what
    # another retrieve stored: that is ``after``); its command warns when there are none.
    reads: tuple[Reads, ...] = ()
    # Normalize only: the retrieve pipelines whose raw records it reads besides the one of its
    # own name (``normalize bwb`` also reads the TOOI thesaurus of ``retrieve tooi``).
    fed_by: tuple[str, ...] = ()
    # What it does in plain Dutch, lower case as it stands in a sentence ("het ophalen van
    # uitspraken van de Rechtspraak"): what an alert names it by (``lawgraph.alert``).
    plain: str = ""

    @property
    def name(self) -> str:
        """``tk-dossiers``: the source and the part."""
        return name_of(self.source, self.part)

    @property
    def address(self) -> str:
        """``normalize tk-dossiers``: what one types, and the label of every log line."""
        return f"{self.phase} {self.name}"

    @property
    def lane_id(self) -> str:
        return self.lane or self.name


def _class_name(phase: Phase, source: str, part: str | None) -> str:
    words = "".join(word.capitalize() for word in (part or "").split("-"))
    prefix = _CLASS_PREFIX.get(source, source.capitalize())
    return f"{prefix}{words}{phase.capitalize()}Pipeline"


@dataclass(frozen=True)
class Options:
    """The options a pipeline class adds to its command, and its constructor arguments
    from them."""

    add_args: Callable[[argparse.ArgumentParser], None]
    extra_kwargs: Callable[[argparse.Namespace], dict[str, Any]]


def _class_address(cls: type) -> tuple[Phase, str, str | None]:
    """The address of a pipeline class, which its name must spell."""
    phase, source, part = address_of(cls.__module__, "")
    if cls.__name__ != _class_name(phase, source, part):
        raise ValueError(
            f"{cls.__module__} holds {cls.__name__}; the pipeline of "
            f"'{phase} {source}{'-' + part if part else ''}' is called "
            f"{_class_name(phase, source, part)}"
        )
    return phase, source, part


def _pipeline(
    runs: type | Main,
    plain: str,
    description: str,
    *,
    options: Options | None = None,
    after: tuple[str, ...] = (),
    fed_by: tuple[str, ...] = (),
) -> Pipeline:
    """Register a normalize or semantic pipeline class, or a hand-written command (which
    takes no ``--since``).

    A class gets a ``PipelineCommand`` with *description* and *options*, so ``--help``,
    ``lawgraph sources`` and the first log line say the same."""
    if isinstance(runs, type):
        phase, source, part = _class_address(runs)
        command: Command = PipelineCommand(
            runs,
            description,
            options.add_args if options else None,
            options.extra_kwargs if options else None,
        )
    else:
        if options:
            raise ValueError(
                f"{runs.__name__}: a hand-written command adds its own options"
            )
        phase, source, part = address_of(runs.__module__, runs.__name__)
        command = HandWritten(runs)
    return Pipeline(
        phase,
        source,
        part,
        command,
        description,
        after=after,
        fed_by=fed_by,
        plain=plain,
    )


def _constructed(
    cls: type, extra_kwargs: Callable[[argparse.Namespace], dict[str, Any]] | None
) -> Run:
    """The run of a retrieve pipeline class: made on the graph with the parsed options."""

    def run(args: argparse.Namespace) -> PipelineResult:
        extra = extra_kwargs(args) if extra_kwargs else {}
        result: PipelineResult = cls(store=GraphStore(), **extra).run()
        return result

    return run


def _retrieve(
    runs: type | Run,
    plain: str,
    description: str,
    *,
    argv_for_all: Callable[[RetrieveCtx], list[str]],
    add_args: AddArgs | None = None,
    extra_kwargs: Callable[[argparse.Namespace], dict[str, Any]] | None = None,
    lane: str = "",
    after: tuple[str, ...] = (),
    fills_gaps: bool = False,
    reads: tuple[Reads, ...] = (),
) -> Pipeline:
    """Register a retrieve: its pipeline class, made with *extra_kwargs* of the options
    *add_args* adds, or a function of ``retrieve_commands`` that runs it on them."""
    if isinstance(runs, type):
        phase, source, part = _class_address(runs)
        run = _constructed(runs, extra_kwargs)
    else:
        if extra_kwargs:
            raise ValueError(f"{runs.__name__}: a function takes the options it parsed")
        phase, source, part = address_of(runs.__module__, runs.__name__)
        run = runs
    command = RetrieveCommand(run, description, add_args, reads)
    return Pipeline(
        phase,
        source,
        part,
        command,
        description,
        argv_for_all,
        lane,
        after,
        fills_gaps,
        reads,
        plain=plain,
    )


# ── retrieve-all argv builders ───────────────────────────────────────────


def _no_argv(ctx: RetrieveCtx) -> list[str]:
    return []


def _mode_argv(ctx: RetrieveCtx) -> list[str]:
    return ["--mode", ctx.mode]


def _windowed_argv(ctx: RetrieveCtx) -> list[str]:
    """Sources that keep producing: a full load only reads what changed inside the window,
    and all of it without one (no ``--since``: a full load reads none)."""
    if ctx.mode is RetrieveMode.FULL:
        return (
            ["--mode", RetrieveMode.INCREMENTAL, "--since", ctx.window]
            if ctx.window
            else ["--mode", RetrieveMode.FULL]
        )
    return ["--mode", ctx.mode, "--since", ctx.since]


def _tk_dossiers_argv(ctx: RetrieveCtx) -> list[str]:
    if ctx.mode is RetrieveMode.FULL:
        return ["--since", ctx.window] if ctx.window else []
    return ["--since", ctx.since, "--skip-members"]


# ── options of pipeline classes ──────────────────────────────────────────


def _slice_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {"after": args.after, "limit": args.limit}


def slice_args(unit: str, key: str) -> Options:
    """``--after`` and ``--limit`` of a run over every *unit* in slices, past a *key*."""

    def add_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--after", help=f"Start past this {key}: the next slice of a run over all."
        )
        add_limit_argument(parser, f"Stop after this many {unit} (a slice).")

    return Options(add_args, _slice_kwargs)


def _tk_dossiers_add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mixed-votes",
        action="store_true",
        help="Only the decisions read as a roll call that were a faction vote with "
        "members voting apart, normalized again from their stored votes.",
    )
    add_limit_argument(parser, "With --mixed-votes: this many decisions (a slice).")
    parser.add_argument(
        "--persons",
        action="store_true",
        help="Only every stored Persoon record, normalized again into its member.",
    )
    parser.add_argument(
        "--seats",
        action="store_true",
        help="Only every stored FractieZetelPersoon record, linked again to its member "
        "and faction (the members' faction timelines).",
    )
    parser.add_argument(
        "--committees",
        action="store_true",
        help="Only every stored Commissie record, normalized again into its committee "
        "and the MEMBER_OF edges of its seats.",
    )
    parser.add_argument(
        "--factions",
        action="store_true",
        help="Only every stored Fractie record, normalized again into its faction "
        "(its aliases and abbreviation from the names its vote rows give it).",
    )


_TK_DOSSIERS_OPTIONS = Options(
    _tk_dossiers_add_args,
    lambda args: {
        "mixed_votes": args.mixed_votes,
        "limit": args.limit,
        "persons": args.persons,
        "seats": args.seats,
        "factions": args.factions,
        "committees": args.committees,
    },
)


# ── the pipelines, in the order each phase runs them ─────────────────────────

RETRIEVE: list[Pipeline] = [
    _retrieve(
        commands.retrieve_tk,
        "het ophalen van de zaken van de Tweede Kamer",
        "Tweede Kamer cases (Zaak) from the OData API.",
        argv_for_all=_windowed_argv,
        add_args=commands.tk_args,
        lane=TWEEDE_KAMER.lane,
    ),
    _retrieve(
        commands.retrieve_tk_dossiers,
        "het ophalen van de dossiers, stemmingen en stukken van de Tweede Kamer",
        (
            "Tweede Kamer dossiers, activities, votes, commitments, committees, members, factions"
            " and documents."
        ),
        argv_for_all=_tk_dossiers_argv,
        add_args=commands.tk_dossiers_args,
        lane=TWEEDE_KAMER.lane,
        fills_gaps=True,
    ),
    _retrieve(
        commands.retrieve_tk_document_links,
        "het ophalen van de koppelingen tussen stukken van de Tweede Kamer",
        (
            "The links of Tweede Kamer documents alone: the activity a document is the record"
            " of (a stenogram: its debate), its attachments, the letters it is attached to."
        ),
        argv_for_all=_windowed_argv,
        add_args=commands.windowed_from_a_day_args,
        lane=TWEEDE_KAMER.lane,
    ),
    _retrieve(
        commands.retrieve_tk_case_actors,
        "het ophalen van de indieners en commissies van zaken van de Tweede Kamer",
        (
            "The actors of Tweede Kamer cases alone: who submitted a case and which"
            " committee leads it."
        ),
        argv_for_all=_windowed_argv,
        add_args=commands.windowed_from_a_day_args,
        lane=TWEEDE_KAMER.lane,
    ),
    _retrieve(
        commands.retrieve_tk_content,
        "het ophalen van de tekst van Kamerstukken",
        (
            "XML of Tweede Kamer papers (memoranda, motions, amendments, bills) from the KOOP "
            "repository: those of which none is stored yet, one XML per paper."
        ),
        argv_for_all=_no_argv,
        add_args=commands.tk_content_args,
        lane=KOOP_REPOSITORY.lane,  # the documents come from repository.overheid.nl
        after=("tk-dossiers",),
        fills_gaps=True,
        reads=(Reads("tk-dossiers", COLLECTION_DOCUMENTS, "TK"),),
    ),
    _retrieve(
        TKTranspositionTablesRetrievePipeline,
        "het ophalen van transponeringstabellen",
        "The transposition tables among the attachments of Kamerstukken (PDF), as the KOOP "
        "SRU lists them: those not stored yet or changed since.",
        argv_for_all=_no_argv,
        lane=KOOP_REPOSITORY.lane,
    ),
    _retrieve(
        commands.retrieve_rechtspraak,
        "het ophalen van uitspraken van de Rechtspraak",
        (
            "Judgments of every court (--court narrows it), by decision date, and those given "
            "with --ecli."
        ),
        argv_for_all=_windowed_argv,
        add_args=commands.rechtspraak_args,
        lane=RECHTSPRAAK.lane,
        fills_gaps=True,
    ),
    _retrieve(
        RechtspraakInstantiesRetrievePipeline,
        "het ophalen van de lijst van gerechten",
        "The Instanties value list of the Rechtspraak (every court an ECLI names); "
        "`lawgraph courts build` makes data/courts.json from it.",
        argv_for_all=_no_argv,
        lane=RECHTSPRAAK.lane,
    ),
    _retrieve(
        commands.retrieve_eurlex,
        "het ophalen van EU-wetgeving",
        (
            "EU acts as HTML by CELEX number: those in the graph that are not stored or that"
            " CELLAR changed since (--mode gaps adds the ones BWB regulations name)."
        ),
        argv_for_all=_no_argv,
        add_args=commands.eurlex_args,
        lane=CELLAR.lane,
        fills_gaps=True,
        # the acts already in the graph; full and nim list them at EUR-Lex, gaps reads BWB
        reads=(
            Reads(
                "eurlex",
                COLLECTION_INSTRUMENTS,
                "EU",
                modes=(RetrieveMode.INCREMENTAL, RetrieveMode.COM),
            ),
        ),
    ),
    _retrieve(
        commands.retrieve_eurlex_nim,
        "het ophalen van de nationale uitvoering van EU-wetgeving",
        (
            "The Dutch national implementing measures of EU acts (CELLAR SPARQL): those "
            "changed in the window, all with --mode full."
        ),
        argv_for_all=_windowed_argv,
        add_args=commands.eurlex_nim_args,
        lane=CELLAR.lane,
    ),
    _retrieve(
        commands.retrieve_bwb,
        "het ophalen van wetten en regelingen",
        (
            "Dutch legislation: the current toestand XML and the WTI abbreviations of every "
            "regulation."
        ),
        argv_for_all=_mode_argv,
        add_args=commands.bwb_args,
        lane=BWB_SEARCH.lane,
        fills_gaps=True,
    ),
    _retrieve(
        commands.retrieve_bwb_history,
        "het ophalen van eerdere versies van wetten en regelingen",
        (
            "Every historical toestand of the regulations of which the current one is stored: "
            "those not stored yet."
        ),
        argv_for_all=_mode_argv,
        add_args=commands.bwb_history_args,
        lane=BWB_SEARCH.lane,  # after bwb in its lane: it reads which regulations bwb stored
    ),
    _retrieve(
        commands.retrieve_staatsblad,
        "het ophalen van publicaties uit het Staatsblad",
        (
            "Staatsblad publications as XML: the explanatory notes of the AMvBs the stored BWB "
            "XML refers to, and the laws of the dossiers the graph holds as adopted without a "
            "law."
        ),
        argv_for_all=_no_argv,
        add_args=commands.staatsblad_args,
        lane=KOOP_REPOSITORY.lane,
        after=("bwb",),
    ),
    _retrieve(
        commands.retrieve_staatscourant,
        "het ophalen van ministeriële regelingen uit de Staatscourant",
        "Ministerial regulations from the Staatscourant as XML, via the KOOP SRU.",
        argv_for_all=_windowed_argv,
        add_args=commands.staatscourant_args,
        lane=KOOP_REPOSITORY.lane,
    ),
    _retrieve(
        commands.retrieve_eerstekamer,
        "het ophalen van Kamerstukken van de Eerste Kamer",
        "Eerste Kamer Kamerstukken from the KOOP SRU (no votes).",
        argv_for_all=_windowed_argv,
        add_args=commands.eerstekamer_args,
        lane=KOOP_REPOSITORY.lane,
    ),
    _retrieve(
        commands.retrieve_eerstekamer_votes,
        "het ophalen van stemmingen van de Eerste Kamer",
        "The votes of the Eerste Kamer on bills (since June 2015) and the list of the "
        "bills it rejected (since 1996), from eerstekamer.nl.",
        argv_for_all=_windowed_argv,
        add_args=commands.windowed_args,
        lane=EERSTEKAMER_SITE.lane,
    ),
    _retrieve(
        EerstekamerCompositionObservedRetrievePipeline,
        "het overnemen van de eerder waargenomen samenstelling van de Eerste Kamer",
        "Once: the composition of the Eerste Kamer the graph holds, with the periods "
        "observed before its pages were kept per version.",
        argv_for_all=_no_argv,
        lane=EERSTEKAMER_SITE.lane,
    ),
    _retrieve(
        EerstekamerCompositionRetrievePipeline,
        "het ophalen van de samenstelling van de Eerste Kamer",
        "The factions (with their seats and boards) and committees of the Eerste Kamer "
        "and who sits in them, as eerstekamer.nl shows them: a version of each page per "
        "day it changed.",
        argv_for_all=_no_argv,
        # after the observed composition in its lane: it covers the versions stored before
        lane=EERSTEKAMER_SITE.lane,
    ),
    _retrieve(
        EerstekamerMutationsRetrievePipeline,
        "het ophalen van de wisselingen in de Eerste Kamer",
        "The changes in the composition of the Eerste Kamer, term by term, as "
        "eerstekamer.nl tells them (/personele_mutaties): the lists, and each change once.",
        argv_for_all=_no_argv,
        lane=EERSTEKAMER_SITE.lane,
    ),
    _retrieve(
        EerstekamerPersonsRetrievePipeline,
        "het ophalen van de pagina's van leden van de Eerste Kamer",
        "The page of every member of the Eerste Kamer (/persoon): those the composition "
        "lists and every person a stored change links, each once, again when a change "
        "names them later (--sitting: every sitting member's again, the weekly run).",
        argv_for_all=_no_argv,
        add_args=commands.eerstekamer_persons_args,
        extra_kwargs=lambda args: {"sitting": args.sitting},
        lane=EERSTEKAMER_SITE.lane,
    ),
    _retrieve(
        EerstekamerMotionsRetrievePipeline,
        "het ophalen van moties van de Eerste Kamer",
        "The page of every motion of the Eerste Kamer voted on (/motiedossier): what it "
        "asks, its key data and who submitted and co-signed it; each page once.",
        argv_for_all=_no_argv,
        add_args=commands.eerstekamer_motions_args,
        extra_kwargs=lambda args: {"limit": args.limit},
        lane=EERSTEKAMER_SITE.lane,
        # the motions voted on: the motion_url of its decisions on a motion
        reads=(Reads("eerstekamer-votes", COLLECTION_DECISIONS, "EK"),),
    ),
    _retrieve(
        KiesraadRetrievePipeline,
        "het ophalen van verkiezingsuitslagen bij de Kiesraad",
        "The seats each list won at the elections of the Eerste Kamer since 2003, from the "
        "Kiesraad's databank: each election once.",
        argv_for_all=_no_argv,
        lane=KIESRAAD.lane,
    ),
    _retrieve(
        commands.retrieve_eerstekamer_agenda,
        "het ophalen van de agenda van de Eerste Kamer",
        "The agendas of the plenary sittings and committee meetings of the Eerste Kamer, "
        "from eerstekamer.nl: those planned, and back to --since (without it back to June "
        "2015, a long run that goes on where one broke off).",
        argv_for_all=_windowed_argv,
        add_args=commands.windowed_args,
        lane=EERSTEKAMER_SITE.lane,
    ),
    _retrieve(
        commands.retrieve_eerstekamer_bills,
        "het ophalen van wetsvoorstellen van de Eerste Kamer",
        "The pages of the bills of the Eerste Kamer: those its committees list (now and "
        "lately) and those it voted on, from eerstekamer.nl.",
        argv_for_all=_windowed_argv,
        add_args=commands.windowed_args,
        lane=EERSTEKAMER_SITE.lane,
        # those it voted on: the bill_url of its decisions
        reads=(Reads("eerstekamer-votes", COLLECTION_DECISIONS, "EK"),),
    ),
    _retrieve(
        commands.retrieve_echr,
        "het ophalen van uitspraken van het EHRM",
        "European Court of Human Rights judgments against the Netherlands (HUDOC).",
        argv_for_all=_windowed_argv,
        add_args=commands.echr_args,
        lane=HUDOC.lane,
        fills_gaps=True,
    ),
    _retrieve(
        commands.retrieve_verdragenbank,
        "het ophalen van verdragen",
        "Treaties the Netherlands is party to, from the KOOP SRU.",
        argv_for_all=_no_argv,
        add_args=commands.verdragenbank_args,
        lane=KOOP_REPOSITORY.lane,
        fills_gaps=True,
    ),
    _retrieve(
        TooiRetrievePipeline,
        "het ophalen van de lijst van ministeries",
        "The TOOI value list of every ministry (names, dates, mergers since about 2010); "
        "`lawgraph ministries build` makes data/ministries.json from it.",
        argv_for_all=_no_argv,
        lane=TOOI.lane,
    ),
    _retrieve(
        RijksoverheidRetrievePipeline,
        "het ophalen van de kabinetten bij Rijksoverheid",
        "The page of every cabinet since 1945 (posts, holders, dates), from rijksoverheid.nl.",
        argv_for_all=_no_argv,
        lane=RIJKSOVERHEID.lane,
    ),
    _retrieve(
        StaatscourantPostsRetrievePipeline,
        "het ophalen van de ministeries achter bewindsposten",
        "Per cabinet post whose function names no ministry: which ministries issued the "
        "publications naming it (Staatscourant and Staatsblad, from 1995).",
        argv_for_all=_no_argv,
        lane=KOOP_REPOSITORY.lane,
        after=("rijksoverheid",),
    ),
]

NORMALIZE: list[Pipeline] = [
    _pipeline(
        TKNormalizePipeline,
        "het verwerken van de zaken van de Tweede Kamer",
        "Cases as nodes.",
    ),
    _pipeline(
        TKDossiersNormalizePipeline,
        "het verwerken van de dossiers, stemmingen en stukken van de Tweede Kamer",
        "Committees, members, factions, dossiers, activities, votes, commitments and "
        "documents as nodes, with their edges.",
        options=_TK_DOSSIERS_OPTIONS,
        after=("tk",),  # the case-to-dossier links read the cases
    ),
    _pipeline(
        TKDocumentLinksNormalizePipeline,
        "het verwerken van de koppelingen tussen stukken van de Tweede Kamer",
        (
            "MADE_IN from a document to the activity it is the record of, and ACCOMPANIES "
            "from an attachment to its letter, from the stored links of the documents."
        ),
        after=("tk-dossiers",),  # the documents and activities it links
    ),
    _pipeline(
        TKCaseActorsNormalizePipeline,
        "het verwerken van de indieners en commissies van zaken van de Tweede Kamer",
        (
            "AUTHORED from a member to the case they submitted, and LED_BY from a case to "
            "its lead committee, from the stored actors of the cases."
        ),
        after=("tk", "tk-dossiers"),  # the cases, members and committees it links
    ),
    _pipeline(
        TKContentNormalizePipeline,
        "het verwerken van de tekst van Kamerstukken",
        "Text, sections (articles, onderdelen, leden) and footnotes of the papers whose "
        "XML was retrieved, on their documents.",
        options=slice_args("papers", "record key"),
        after=("tk-dossiers",),  # it writes on the documents
    ),
    _pipeline(
        RechtspraakNormalizePipeline,
        "het verwerken van uitspraken van de Rechtspraak",
        "Judgment nodes from the stored judgment XML (court, date, summary, text, "
        "footnotes, related ECLIs).",
        options=slice_args("judgments", "record key"),
    ),
    _pipeline(
        EurlexNormalizePipeline,
        "het verwerken van EU-wetgeving en uitspraken van het Hof van Justitie",
        "EU instruments and their articles; the judgments of the courts of the EU (CELEX "
        "sector 6), keyed by their ECLI.",
    ),
    _pipeline(
        BWBNormalizePipeline,
        "het verwerken van wetten en regelingen",
        "Instruments and articles; short titles and aliases from the WTI abbreviations.",
        fed_by=("tooi",),  # the subjects of the TOOI thesaurus
    ),
    _pipeline(
        BWBHistoryNormalizePipeline,
        "het verwerken van eerdere versies van wetten en regelingen",
        "Article and instrument versions from the stored toestanden.",
        after=("bwb",),  # the articles and instruments
    ),
    _pipeline(
        StaatsbladNormalizePipeline,
        "het verwerken van publicaties uit het Staatsblad",
        "Publications as documents.",
    ),
    _pipeline(
        StaatsbladLawsNormalizePipeline,
        "het verwerken van wetten uit het Staatsblad",
        "The laws of the Staatsblad the BWB does not hold (yet) as instruments with their "
        "articles, read from the XML of their publication; one the BWB holds now goes.",
        # the regulations the BWB holds, and the dossiers of the publications
        after=("bwb", "tk-dossiers"),
        fed_by=("staatsblad",),  # the laws retrieve staatsblad stores
    ),
    _pipeline(
        StaatscourantNormalizePipeline,
        "het verwerken van regelingen uit de Staatscourant",
        "Regulations as documents.",
    ),
    _pipeline(
        EerstekamerNormalizePipeline,
        "het verwerken van Kamerstukken van de Eerste Kamer",
        "Kamerstukken as documents, with the dossier number and its addition.",
    ),
    _pipeline(
        EerstekamerCompositionNormalizePipeline,
        "het verwerken van de samenstelling van de Eerste Kamer",
        "The factions, committees and members of the Eerste Kamer as its pages show them "
        "on each day they changed; periods as observed.",
        after=("tk-dossiers",),  # the members it is matched to
        fed_by=("eerstekamer-composition-observed",),  # the periods observed before
    ),
    _pipeline(
        EerstekamerMutationsNormalizePipeline,
        "het verwerken van de zetels in de Eerste Kamer",
        "The seats of the Eerste Kamer day by day since 2003: each term from the Kiesraad's "
        "result through the changes the Kamer's pages tell, checked.",
        after=("eerstekamer-composition",),  # the factions of today and their history
    ),
    _pipeline(
        EerstekamerPersonsNormalizePipeline,
        "het verwerken van de fractieperiodes van leden van de Eerste Kamer",
        "The periods of the members of the Eerste Kamer in its factions, as their own pages "
        "say them, checked against the changes of the Kamer's pages.",
        # the members and factions, and the changes the periods are checked against
        after=("eerstekamer-composition", "eerstekamer-mutations"),
    ),
    _pipeline(
        EerstekamerMotionsNormalizePipeline,
        "het verwerken van moties van de Eerste Kamer",
        "What the page of a motion of the Eerste Kamer says on the motion's Kamerstuk: what "
        "it asks, its key data and who submitted and co-signed it, with AUTHORED from them.",
        # the Kamerstukken of the Eerste Kamer, and the members of the persons' pages
        after=("eerstekamer", "eerstekamer-persons"),
    ),
    _pipeline(
        EerstekamerAgendaNormalizePipeline,
        "het verwerken van de agenda van de Eerste Kamer",
        "The agendas of the Eerste Kamer as activities: each block of a plenary sitting "
        "and each committee meeting, about the dossiers it names.",
        after=("tk-dossiers", "eerstekamer-composition"),  # cases, dossiers, committees
    ),
    _pipeline(
        EerstekamerBillsNormalizePipeline,
        "het verwerken van wetsvoorstellen van de Eerste Kamer",
        "The page of each bill of the Eerste Kamer onto its dossier: the day it was "
        "submitted and its progress, as the page gives them.",
        after=("tk-dossiers",),  # the dossiers it writes on
    ),
    _pipeline(
        EerstekamerVotesNormalizePipeline,
        "het verwerken van stemmingen van de Eerste Kamer",
        "The votes of the Eerste Kamer on bills as decisions about their dossiers; the "
        "day each rejected bill was rejected on its dossier.",
        after=("tk-dossiers",),  # the dossiers it writes on
    ),
    _pipeline(
        ECHRNormalizePipeline,
        "het verwerken van uitspraken van het EHRM",
        "Judgments as nodes.",
    ),
    _pipeline(
        RijksoverheidNormalizePipeline,
        "het verwerken van kabinetten en bewindspersonen",
        "Cabinets with their phases and parties, and every post held in them onto the "
        "member who held it (surname and initials, or signatures); a holder without a "
        "Tweede Kamer person becomes a member of their own.",
        after=("tk-dossiers",),  # members, signatures, commitments
        fed_by=("staatscourant-posts",),  # the ministries of the posts that name none
    ),
    _pipeline(
        VerdragenbankNormalizePipeline,
        "het verwerken van verdragen",
        "Treaties as instruments.",
    ),
]

SEMANTIC: list[Pipeline] = [
    _pipeline(
        TKSemanticPipeline,
        "het koppelen van wetsartikelen in Kamerstukken",
        "Article citations in Tweede Kamer documents: REFERS_TO to BWB and EU articles.",
        options=slice_args("documents", "document key"),
    ),
    _pipeline(
        RechtspraakSemanticPipeline,
        "het koppelen van wetsartikelen in uitspraken",
        "Article citations in judgments (of the Rechtspraak and of the courts of the EU): "
        "REFERS_TO to BWB and EU articles.",
        options=slice_args("judgments", "judgment key"),
    ),
    _pipeline(
        EurlexSemanticPipeline,
        "het koppelen van artikelen in EU-wetgeving",
        "Article citations in EU articles: links EU instruments to national and EU articles.",
    ),
    _pipeline(
        BWBSemanticPipeline,
        "het koppelen van verwijzingen tussen wetsartikelen",
        "REFERS_TO between BWB articles, read from the references in their toestand XML.",
    ),
    _pipeline(
        BWBDefinitionsSemanticPipeline,
        "het vastleggen van begripsbepalingen",
        "The definitions each regulation gives itself (its begripsbepalingen), read from "
        "its stored toestand.",
        options=slice_args("regulations", "BWB id"),
    ),
    _pipeline(
        BWBCaptionsSemanticPipeline,
        "het vastleggen van de opschriften van artikelen",
        "What each article is about, for its title (its caption): the deepest title of the "
        "divisions it stands in that one division of its law has.",
        options=slice_args("regulations", "BWB id"),
    ),
    _pipeline(
        BWBGrondslagenSemanticPipeline,
        "het koppelen van regelingen aan hun grondslag",
        "BASED_ON from a regulation to the article it is issued under ('Gelet op').",
    ),
    _pipeline(
        BWBAmendmentsSemanticPipeline,
        "het koppelen van regelingen aan de publicaties die ze wijzigen",
        (
            "ESTABLISHES from the publication that enacted a regulation, AMENDS, INTRODUCES "
            "and REPEALS from amending publications, and LEGISLATED_IN from dossier "
            "references."
        ),
    ),
    _pipeline(
        BWBAnnexesSemanticPipeline,
        "het koppelen van artikelen aan bijlagen",
        "SCOPED_BY: links articles to the annexes their text names (stubs for missing ones).",
    ),
    _pipeline(
        StaatsbladSemanticPipeline,
        "het koppelen van toelichtingen uit het Staatsblad",
        "EXPLAINS: links Staatsblad explanatory notes to the instrument they explain.",
    ),
    _pipeline(
        StaatsbladLawReferencesSemanticPipeline,
        "het koppelen van verwijzingen in wetten uit het Staatsblad",
        "REFERS_TO between the articles of a law of the Staatsblad, read from their text.",
    ),
    _pipeline(
        TKTranspositionTablesSemanticPipeline,
        "het koppelen van oude aan nieuwe wetsartikelen",
        "TRANSPOSED_TO from an article of the old law to its place in the new law, from the "
        "stored transposition tables, each row checked against the text of the new law.",
    ),
    _pipeline(
        StaatscourantSemanticPipeline,
        "het koppelen van regelingen uit de Staatscourant",
        "EXPLAINS: links Staatscourant regulations to instruments.",
    ),
    _pipeline(
        BWBPublicationsSemanticPipeline,
        "het koppelen van publicaties aan regelingen",
        "SAME_AS: a paper of the Staatsblad or the Staatscourant to the publication of the "
        "BWB of the same official id, by their keys.",
    ),
    _pipeline(
        EerstekamerSemanticPipeline,
        "het koppelen van stukken van de Eerste Kamer aan dossiers",
        "PART_OF: links each paper to its Tweede Kamer dossier.",
    ),
    _pipeline(
        ECHRSemanticPipeline,
        "het koppelen van uitspraken van het EHRM aan verdragsartikelen",
        "REFERS_TO: links ECHR judgments to Convention articles.",
    ),
    _pipeline(
        ECHRVersionsSemanticPipeline,
        "het koppelen van taalversies van uitspraken van het EHRM",
        (
            "SAME_AS between the language versions of an ECHR decision without an ECLI "
            "(same appno and date); the lists show it once."
        ),
    ),
    _pipeline(
        RechtspraakAppealSemanticPipeline,
        "het koppelen van uitspraken in hoger beroep aan eerdere uitspraken",
        (
            "APPEAL_OF, CONTINUES and REFERRED_BY from a judgment to the earlier judgments "
            "of its case; the decision an appeal names but is not loaded."
        ),
    ),
    _pipeline(
        RechtspraakConclusionsSemanticPipeline,
        "het koppelen van conclusies aan uitspraken",
        "ADVISES_ON from the conclusion of an advocate-general to the judgment in its case.",
    ),
    _pipeline(
        RechtspraakReferralsSemanticPipeline,
        "het koppelen van prejudiciële beslissingen aan hun vragen",
        "ANSWERS from a preliminary ruling to the decision that asked its questions.",
    ),
    _pipeline(
        EurlexCjeuSemanticPipeline,
        "het koppelen van uitspraken van het Hof van Justitie",
        "REFERS_TO from a judgment of the Court of Justice of the EU to the judgments its "
        "text cites by ECLI (stubs for those not loaded); ANSWERS to the Dutch decision that "
        "referred its questions.",
    ),
    _pipeline(
        RechtspraakRelatedSemanticPipeline,
        "het koppelen van samenhangende uitspraken",
        (
            "RELATED_TO from a judgment to the connected cases its summary names "
            '("Samenhang met", "Zie ook"), on an exact ECLI or case number of the same court.'
        ),
    ),
    _pipeline(
        RechtspraakDuplicatesSemanticPipeline,
        "het koppelen van vervangen publicaties van uitspraken",
        (
            "SAME_AS from a publication of a decision to the one that replaces it "
            "(dcterms:isReplacedBy); the lists show the decision once."
        ),
    ),
    _pipeline(
        RechtspraakCitationsSemanticPipeline,
        "het koppelen van verwijzingen tussen uitspraken",
        "ECLI references between judgments: REFERS_TO, none between judgments that "
        "APPEAL_OF, CONTINUES, REFERRED_BY, ADVISES_ON or ANSWERS already tie; cited "
        "judgments that are not loaded become stubs.",
        options=slice_args("judgments", "record key"),
    ),
    _pipeline(
        RechtspraakSeriesSemanticPipeline,
        "het herkennen van reeksen gelijke uitspraken",
        "Series of parallel judgments: one court, one day, (nearly) the same text.",
    ),
    _pipeline(
        TKAmendsSemanticPipeline,
        "het koppelen van Kamerstukken aan de wet die ze wijzigen",
        "AMENDS from a Tweede Kamer document to the law its title says it changes.",
    ),
    _pipeline(
        BWBImplementsSemanticPipeline,
        "het koppelen van regelingen aan de EU-wetgeving die ze uitvoeren",
        (
            "IMPLEMENTS to an EU act from the publications EUR-Lex lists as its national "
            "implementing measures, the regulations they enacted or changed, and the "
            "regulations whose considerans says they implement it; REFERS_TO for the other "
            "EU acts a regulation names."
        ),
    ),
    _pipeline(
        VerdragenbankSemanticPipeline,
        "het koppelen van verdragen aan publicaties en dossiers",
        (
            "From the register of a treaty: PUBLISHED_IN to its Tractatenbladen, LEGISLATED_IN "
            "to the dossier of its approval, PART_OF to the treaty it belongs to."
        ),
    ),
    _pipeline(
        TKAmendmentArticlesSemanticPipeline,
        "het koppelen van amendementen aan de artikelen die ze wijzigen",
        "Amendment language in Tweede Kamer documents, linked to the articles it changes.",
    ),
    _pipeline(
        TKDossierRelationsSemanticPipeline,
        "het koppelen van samenhangende dossiers",
        (
            "RELATED_TO, REVISES, ACCOMPANIES and SECOND_READING_OF between dossiers: the cases "
            "the Kamer relates, the budget a budget change revises and the nota it comes with, "
            "and the first reading of a change in the Grondwet; MADE_IN from a motion to the "
            "debate it was submitted in."
        ),
    ),
    _pipeline(
        TKCitedPapersSemanticPipeline,
        "het koppelen van Kamerstukken die elkaar noemen",
        (
            "ANSWERS and REFERS_TO to the Kamerstukken a paper's subject names by dossier "
            'and number, "(Kamerstuk 25424-795)": ANSWERS from a letter of the government '
            "to a motion, also one its text or a footnote names."
        ),
    ),
    _pipeline(
        TKMvtSemanticPipeline,
        "het koppelen van memories van toelichting",
        "EXPLAINS: links explanatory memoranda to what they explain.",
    ),
    _pipeline(
        TKMvtArticlesSemanticPipeline,
        "het koppelen van toelichtingen aan artikelen",
        "EXPLAINS: the section of an explanatory memorandum that explains an article.",
    ),
    _pipeline(
        BWBRelationTypesSemanticPipeline,
        "het indelen van verwijzingen tussen artikelen",
        "Classifies article-to-article REFERS_TO edges by what they mean.",
    ),
    _pipeline(
        TKDossierTitlesSemanticPipeline,
        "het vastleggen van de titels van dossiers",
        "The title and opening date of every dossier without, from its papers and "
        "activities: also of a dossier another source made.",
    ),
    _pipeline(
        TKDossierOutcomesSemanticPipeline,
        "het bepalen van de afloop van dossiers",
        (
            "Whether each dossier is closed and how it ended: the publication of its law, "
            "the vote of the Tweede Kamer that rejected its bill, or the outcome in the "
            "Eerste Kamer; and the last decision of each chamber on its bill."
        ),
    ),
    _pipeline(
        TKGovernmentSemanticPipeline,
        "het bepalen van ministerie en kabinet bij stukken en toezeggingen",
        (
            "Who in government made each commitment and brought each dossier in (ministry "
            "or initiative), and the cabinet in office then."
        ),
    ),
    _pipeline(
        TKCoalitionVotesSemanticPipeline,
        "het bepalen van het stemgedrag van de coalitie",
        "What the coalition did on each vote of the Tweede Kamer: together, split or a "
        "wisselmeerderheid, and whether it carried or decided it.",
    ),
    _pipeline(
        TKPersonDuplicatesSemanticPipeline,
        "het samenvoegen van dubbele Kamerleden",
        "SAME_AS from a bare Persoon of the Tweede Kamer to the member with a role who is "
        "the same person (birth date, surname and initials).",
    ),
    _pipeline(
        tk_dictum.main,
        "het vastleggen van het dictum van moties",
        "Keeps the dictum of every motion with text (what it asks or says) and the opening "
        "of the Toelichting of every amendment with text.",
    ),
    _pipeline(
        TKPaperOutcomesSemanticPipeline,
        "het bepalen van de afloop van moties en amendementen",
        "How each motion and amendment ended (aangenomen, verworpen, ingetrokken, "
        "aangehouden, vervallen, vervangen), when, and by how many seats.",
    ),
    _pipeline(
        GraphDeriveSemanticPipeline,
        "het opnieuw afleiden van kolommen",
        "Derives the columns of a table again from its props, after a release changed how "
        "they are derived; without a table it names the tables that need it.",
        options=Options(graph_derive.add_args, graph_derive.extra_kwargs),
    ),
    _pipeline(
        GraphLightSemanticPipeline,
        "het bijwerken van de lijsten zonder tekst",
        "Keeps every judgment, paper, instrument name, faction vote, signature and item a "
        "committee leads light, without its text, for those written before the triggers "
        "that keep them.",
        options=Options(graph_light.add_args, graph_light.extra_kwargs),
    ),
    _pipeline(
        GraphArticleTermsSemanticPipeline,
        "het bijwerken van de zoektermen per artikel",
        "Keeps per article the terms the judgments that cite it call it by (noodweer of "
        "art. 41 Sr), which the search finds it by.",
    ),
    _pipeline(
        GraphHeatSemanticPipeline,
        "het bijwerken van de verbondenheid van de graaf",
        "Keeps the heat of the whole graph, which the API reads instead of the edges.",
    ),
    _pipeline(
        GraphListStatsSemanticPipeline,
        "het bijwerken van de sorteer- en filtervelden van de lijsten",
        "Precomputes the sort and filter fields of the list endpoints.",
        options=Options(graph_list_stats.add_args, graph_list_stats.extra_kwargs),
    ),
]

PIPELINES: dict[Phase, list[Pipeline]] = {
    "retrieve": RETRIEVE,
    "normalize": NORMALIZE,
    "semantic": SEMANTIC,
}


def find(phase: str, name: str) -> Pipeline | None:
    """The pipeline with this address, as typed (``tk-dossiers``)."""
    return next(
        (p for p in PIPELINES.get(cast(Phase, phase), []) if p.name == name), None
    )
