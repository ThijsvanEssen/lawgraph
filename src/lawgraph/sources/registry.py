"""Every pipeline, per phase, in the order it runs.

A **phase** is ``retrieve``, ``normalize`` or ``semantic``. A **source** is where records
come from (``SOURCES``; ``graph`` is what works on the whole graph). A **pipeline** is one
unit of work in one phase for one source, and it has an address::

    <phase> <source>[-<part>]        normalize tk-dossiers, semantic rechtspraak-citations

The address is what one types after ``lawgraph``, the label on its log lines, its skip
variable (``LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS``) and its module
(``pipelines/normalize/tk_dossiers.py`` holding ``TKDossiersNormalizePipeline``). It is
written nowhere in this file: ``_pipeline`` reads it from the module of what it registers,
and a class whose name does not follow is refused when this module is imported. A pipeline
that links two sources belongs to the one its edges start at, the text that is read.

The lists below are the order of ``<phase> all``; a pipeline that reads edges written by
another comes after it. A retrieve pipeline without ``argv_for_all`` is a manual command.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast, get_args

from lawgraph.pipelines.command import Command, PipelineCommand
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.normalize.bwb_history import BWBHistoryNormalizePipeline
from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline
from lawgraph.pipelines.normalize.eerstekamer import EerstekamerNormalizePipeline
from lawgraph.pipelines.normalize.eurlex import EurlexNormalizePipeline
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline
from lawgraph.pipelines.normalize.staatscourant import StaatscourantNormalizePipeline
from lawgraph.pipelines.normalize.tk import TKNormalizePipeline
from lawgraph.pipelines.normalize.tk_content import TKContentNormalizePipeline
from lawgraph.pipelines.normalize.tk_dossiers import TKDossiersNormalizePipeline
from lawgraph.pipelines.normalize.verdragenbank import VerdragenbankNormalizePipeline
from lawgraph.pipelines.normalize.wikidata import WikidataNormalizePipeline
from lawgraph.pipelines.retrieve_commands import (
    retrieve_bwb,
    retrieve_bwb_history,
    retrieve_echr,
    retrieve_eerstekamer,
    retrieve_eurlex,
    retrieve_rechtspraak,
    retrieve_staatsblad,
    retrieve_staatscourant,
    retrieve_tk,
    retrieve_tk_content,
    retrieve_tk_dossiers,
    retrieve_verdragenbank,
    retrieve_wikidata,
)
from lawgraph.pipelines.semantic import graph_list_stats
from lawgraph.pipelines.semantic.bwb import BWBSemanticPipeline
from lawgraph.pipelines.semantic.bwb_amendments import BWBAmendmentsSemanticPipeline
from lawgraph.pipelines.semantic.bwb_annexes import BWBAnnexesSemanticPipeline
from lawgraph.pipelines.semantic.bwb_grondslagen import BWBGrondslagenSemanticPipeline
from lawgraph.pipelines.semantic.bwb_implements import BWBImplementsSemanticPipeline
from lawgraph.pipelines.semantic.bwb_relation_types import (
    BWBRelationTypesSemanticPipeline,
)
from lawgraph.pipelines.semantic.echr import ECHRSemanticPipeline
from lawgraph.pipelines.semantic.eerstekamer import (
    EerstekamerSemanticPipeline,
)
from lawgraph.pipelines.semantic.eurlex import EurlexSemanticPipeline
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
from lawgraph.pipelines.semantic.rechtspraak_referrals import (
    RechtspraakReferralsSemanticPipeline,
)
from lawgraph.pipelines.semantic.staatsblad import StaatsbladSemanticPipeline
from lawgraph.pipelines.semantic.staatscourant import (
    StaatscourantSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk import TKSemanticPipeline
from lawgraph.pipelines.semantic.tk_amendment_articles import (
    TKAmendmentArticlesSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_amends import TKAmendsSemanticPipeline
from lawgraph.pipelines.semantic.tk_dossier_outcomes import (
    TKDossierOutcomesSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_dossier_relations import (
    TKDossierRelationsSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_mvt import TKMvtSemanticPipeline
from lawgraph.pipelines.semantic.tk_mvt_articles import (
    TKMvtArticlesSemanticPipeline,
)

Phase = Literal["retrieve", "normalize", "semantic"]
PHASES: tuple[Phase, ...] = get_args(Phase)

# Where records come from; ``graph``: no source of its own, the graph as a whole.
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
    "wikidata": "Wikidata",
    "graph": "The whole graph",
}
# How a source is spelled in a class name, where capitalising it is not enough.
_CLASS_PREFIX = {"tk": "TK", "bwb": "BWB", "echr": "ECHR"}

# Retrieve pipelines that share a server run one after the other.
LANE_TWEEDE_KAMER = "tweede_kamer"
LANE_KOOP_REPOSITORY = "koop_repository"  # repository.overheid.nl: SRU and publications


@dataclass(frozen=True)
class RetrieveCtx:
    """Options of ``retrieve all`` that ``argv_for_all`` translates per pipeline."""

    since: str
    mode: str  # "incremental" | "full"
    window: str | None = None  # full mode: what changed since then; None: everything


@dataclass(frozen=True)
class Pipeline:
    """One pipeline of the registry: its address, its command and how ``retrieve all`` runs it."""

    phase: Phase
    source: str
    part: str | None
    command: Command
    description: str  # printed by ``lawgraph sources`` and in the first log line
    # Retrieve only. ``argv_for_all`` turns the options of ``retrieve all`` into those of the
    # command (without it: a manual command); ``lane`` names the server it talks to, so no
    # server gets two request streams; ``after`` names pipelines that must have ended first.
    argv_for_all: Callable[[RetrieveCtx], list[str]] | None = None
    lane: str = ""
    after: tuple[str, ...] = ()
    # Retrieve only: the command has ``--mode gaps`` (what the graph refers to and lacks),
    # so it is part of ``retrieve all --mode gaps`` and of every round of ``expand-graph``.
    fills_gaps: bool = False

    @property
    def name(self) -> str:
        """``tk-dossiers``: the source and the part."""
        return f"{self.source}-{self.part}" if self.part else self.source

    @property
    def address(self) -> str:
        """``normalize tk-dossiers``: what one types, and the label of every log line."""
        return f"{self.phase} {self.name}"

    @property
    def lane_id(self) -> str:
        return self.lane or self.name


def _address_of(module: str, function: str) -> tuple[Phase, str, str | None]:
    """``(phase, source, part)`` from where a pipeline lives.

    ``lawgraph.pipelines.semantic.rechtspraak_citations`` is ``semantic
    rechtspraak-citations``; a retrieve command is a function of ``retrieve_commands``
    named ``retrieve_<source>[_<part>]``.
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
    return cast(Phase, phase), source, part


def _class_name(phase: Phase, source: str, part: str | None) -> str:
    words = "".join(word.capitalize() for word in (part or "").split("-"))
    prefix = _CLASS_PREFIX.get(source, source.capitalize())
    return f"{prefix}{words}{phase.capitalize()}Pipeline"


def _pipeline(
    runs: type | Command,
    description: str,
    *,
    argv_for_all: Callable[[RetrieveCtx], list[str]] | None = None,
    lane: str = "",
    after: tuple[str, ...] = (),
    fills_gaps: bool = False,
) -> Pipeline:
    """Register a pipeline class, a ``PipelineCommand`` or a hand-written command."""
    cls = runs.pipeline_cls if isinstance(runs, PipelineCommand) else runs
    if isinstance(cls, type):
        phase, source, part = _address_of(cls.__module__, "")
        if cls.__name__ != _class_name(phase, source, part):
            raise ValueError(
                f"{cls.__module__} holds {cls.__name__}; the pipeline of "
                f"'{phase} {source}{'-' + part if part else ''}' is called "
                f"{_class_name(phase, source, part)}"
            )
        command: Command = (
            runs
            if isinstance(runs, PipelineCommand)
            else PipelineCommand(cls, description)
        )
    else:
        phase, source, part = _address_of(runs.__module__, runs.__name__)
        command = runs
    return Pipeline(
        phase, source, part, command, description, argv_for_all, lane, after, fills_gaps
    )


# ── Extra args for semantic pipelines with non-standard constructor args ──


def _bwb_articles_add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store-citations", action="store_true")


def _bwb_articles_extra_kwargs(args: argparse.Namespace) -> dict:
    return {"store_citations": args.store_citations}


# ── retrieve-all argv builders ───────────────────────────────────────────


def _no_argv(ctx: RetrieveCtx) -> list[str]:
    return []


def _mode_argv(ctx: RetrieveCtx) -> list[str]:
    return ["--mode", ctx.mode]


def _windowed_argv(ctx: RetrieveCtx) -> list[str]:
    """Sources that keep producing: a full load only reads what changed inside the window."""
    if ctx.mode == "full" and ctx.window:
        return ["--mode", "incremental", "--since", ctx.window]
    return ["--mode", ctx.mode, "--since", ctx.since]


def _tk_dossiers_argv(ctx: RetrieveCtx) -> list[str]:
    if ctx.mode == "full":
        return ["--since", ctx.window] if ctx.window else []
    return ["--since", ctx.since, "--skip-members"]


BWB_SEMANTIC = PipelineCommand(
    BWBSemanticPipeline,
    "REFERS_TO between BWB articles, from the references of their toestand.",
    add_args=_bwb_articles_add_args,
    make_extra_kwargs=_bwb_articles_extra_kwargs,
)

# ── the pipelines, in the order each phase runs them ─────────────────────────

RETRIEVE: list[Pipeline] = [
    _pipeline(
        retrieve_tk,
        "Tweede Kamer cases (Zaak) from the OData API.",
        argv_for_all=_windowed_argv,
        lane=LANE_TWEEDE_KAMER,
    ),
    _pipeline(
        retrieve_tk_dossiers,
        (
            "Tweede Kamer dossiers, activities, votes, commitments, committees, members, factions"
            " and documents."
        ),
        argv_for_all=_tk_dossiers_argv,
        lane=LANE_TWEEDE_KAMER,
    ),
    _pipeline(
        retrieve_tk_content,
        (
            "XML of Tweede Kamer papers (explanatory memoranda) from the KOOP repository; slow, "
            "one XML per paper."
        ),
        lane=LANE_KOOP_REPOSITORY,  # the papers come from repository.overheid.nl
        fills_gaps=True,
    ),
    _pipeline(
        retrieve_rechtspraak,
        (
            "Judgments of the Hoge Raad, Raad van State and gerechtshoven (--court), by decision "
            "date, and those given with --ecli."
        ),
        argv_for_all=_windowed_argv,
        fills_gaps=True,
    ),
    _pipeline(
        retrieve_eurlex,
        (
            "EU acts as HTML by CELEX number: those already in the graph (--mode gaps adds the"
            " ones BWB regulations name)."
        ),
        argv_for_all=_no_argv,
        fills_gaps=True,
    ),
    _pipeline(
        retrieve_bwb,
        (
            "Dutch legislation: the current toestand XML and the WTI abbreviations of every "
            "regulation."
        ),
        argv_for_all=_mode_argv,
        fills_gaps=True,
    ),
    _pipeline(
        retrieve_bwb_history,
        "Every toestand of the given regulations; slow.",
    ),
    _pipeline(
        retrieve_staatsblad,
        (
            "Staatsblad publications (explanatory notes of AMvBs) as XML, for the regulations the"
            " stored BWB XML refers to."
        ),
        argv_for_all=_no_argv,
        lane=LANE_KOOP_REPOSITORY,
        after=("bwb",),
    ),
    _pipeline(
        retrieve_staatscourant,
        "Ministerial regulations from the Staatscourant as XML, via the KOOP SRU.",
        argv_for_all=_windowed_argv,
        lane=LANE_KOOP_REPOSITORY,
    ),
    _pipeline(
        retrieve_eerstekamer,
        "Eerste Kamer Kamerstukken from the KOOP SRU (no votes).",
        argv_for_all=_windowed_argv,
        lane=LANE_KOOP_REPOSITORY,
    ),
    _pipeline(
        retrieve_echr,
        "European Court of Human Rights judgments against the Netherlands (HUDOC).",
        argv_for_all=_windowed_argv,
        fills_gaps=True,
    ),
    _pipeline(
        retrieve_verdragenbank,
        "Treaties the Netherlands is party to, from the KOOP SRU.",
        argv_for_all=_no_argv,
        lane=LANE_KOOP_REPOSITORY,
        fills_gaps=True,
    ),
    _pipeline(
        retrieve_wikidata,
        "The posts people held in Dutch cabinets, from Wikidata (one SPARQL query).",
        argv_for_all=_no_argv,
    ),
]

NORMALIZE: list[Pipeline] = [
    _pipeline(
        TKNormalizePipeline,
        "Cases as nodes.",
    ),
    _pipeline(
        TKDossiersNormalizePipeline,
        (
            "Committees, members, factions, dossiers, activities, votes, commitments and "
            "documents as nodes, with their edges."
        ),
    ),
    _pipeline(
        TKContentNormalizePipeline,
        (
            "Text and sections (articles, onderdelen, leden) of the papers whose XML was "
            "retrieved, on their documents."
        ),
    ),
    _pipeline(
        RechtspraakNormalizePipeline,
        "Judgment nodes from the stored judgment XML (court, date, summary, text, related ECLIs).",
    ),
    _pipeline(
        EurlexNormalizePipeline,
        "EU instruments and their articles.",
    ),
    _pipeline(
        BWBNormalizePipeline,
        "Instruments and articles; short titles from the WTI abbreviations.",
    ),
    _pipeline(
        BWBHistoryNormalizePipeline,
        "Article and instrument versions from the stored toestanden.",
    ),
    _pipeline(
        StaatsbladNormalizePipeline,
        "Publications as documents.",
    ),
    _pipeline(
        StaatscourantNormalizePipeline,
        "Regulations as documents.",
    ),
    _pipeline(
        EerstekamerNormalizePipeline,
        "Kamerstukken as documents, with the dossier number and its addition.",
    ),
    _pipeline(
        ECHRNormalizePipeline,
        "Judgments as nodes.",
    ),
    _pipeline(
        WikidataNormalizePipeline,
        "Cabinet posts onto the members they belong to (date of birth and surname, or "
        "signatures); a person without a Tweede Kamer person becomes a member of their own.",
    ),
    _pipeline(
        VerdragenbankNormalizePipeline,
        "Treaties as instruments.",
    ),
]

SEMANTIC: list[Pipeline] = [
    _pipeline(
        TKSemanticPipeline,
        "Article citations in Tweede Kamer documents: REFERS_TO to BWB and EU articles.",
    ),
    _pipeline(
        RechtspraakSemanticPipeline,
        "Article citations in judgments: REFERS_TO to BWB articles.",
    ),
    _pipeline(
        EurlexSemanticPipeline,
        "Article citations in EU articles: links EU instruments to national and EU articles.",
    ),
    _pipeline(
        BWB_SEMANTIC,
        "REFERS_TO between articles, read from the XML.",
    ),
    _pipeline(
        BWBGrondslagenSemanticPipeline,
        "BASED_ON from a regulation to the article it is issued under ('Gelet op').",
    ),
    _pipeline(
        BWBAmendmentsSemanticPipeline,
        (
            "AMENDS, INTRODUCES and REPEALS from amending publications, and LEGISLATED_IN from "
            "dossier references."
        ),
    ),
    _pipeline(
        BWBAnnexesSemanticPipeline,
        "Annex nodes from the BWB XML and SCOPED_BY edges.",
    ),
    _pipeline(
        StaatsbladSemanticPipeline,
        "EXPLAINS: links Staatsblad explanatory notes to the instrument they explain.",
    ),
    _pipeline(
        StaatscourantSemanticPipeline,
        "EXPLAINS: links Staatscourant regulations to instruments.",
    ),
    _pipeline(
        EerstekamerSemanticPipeline,
        "PART_OF: links each paper to its Tweede Kamer dossier.",
    ),
    _pipeline(
        ECHRSemanticPipeline,
        "REFERS_TO: links ECHR judgments to Convention articles.",
    ),
    _pipeline(
        RechtspraakCitationsSemanticPipeline,
        (
            "ECLI references between judgments: REFERS_TO; cited judgments that are not loaded "
            "become stubs."
        ),
    ),
    _pipeline(
        RechtspraakAppealSemanticPipeline,
        "APPEAL_OF from appeal and cassation judgments to the earlier proceedings.",
    ),
    _pipeline(
        RechtspraakConclusionsSemanticPipeline,
        "ADVISES_ON from the conclusion of an advocate-general to the judgment in its case.",
    ),
    _pipeline(
        RechtspraakReferralsSemanticPipeline,
        "ANSWERS from a preliminary ruling to the decision that asked its questions.",
    ),
    _pipeline(
        TKAmendsSemanticPipeline,
        "AMENDS from a Tweede Kamer document to the law its title says it changes.",
    ),
    _pipeline(
        BWBImplementsSemanticPipeline,
        "IMPLEMENTS from a regulation to the EU acts its text names.",
    ),
    _pipeline(
        TKAmendmentArticlesSemanticPipeline,
        "Amendment language in Tweede Kamer documents, linked to the articles it changes.",
    ),
    _pipeline(
        TKMvtSemanticPipeline,
        "EXPLAINS: links explanatory memoranda to what they explain.",
    ),
    _pipeline(
        TKMvtArticlesSemanticPipeline,
        "EXPLAINS: the section of an explanatory memorandum that explains an article.",
    ),
    _pipeline(
        BWBRelationTypesSemanticPipeline,
        "Classifies article-to-article REFERS_TO edges by what they mean.",
    ),
    _pipeline(
        TKDossierOutcomesSemanticPipeline,
        (
            "Whether each dossier is closed and how it ended: the publication of its law, "
            "the withdrawal of its bill or the vote that rejected it."
        ),
    ),
    _pipeline(
        TKDossierRelationsSemanticPipeline,
        (
            "RELATED_TO, REVISES and ACCOMPANIES between dossiers: the cases the Kamer relates, "
            "and the budget a budget change revises and the nota it comes with."
        ),
    ),
    _pipeline(
        graph_list_stats.main,
        "Precomputes the sort and filter fields of the list endpoints.",
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
