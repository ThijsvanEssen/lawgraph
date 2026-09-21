"""Registry of all sources: the single definition of CLI commands and their order.

Adding a source: write its pipelines (and a retrieve command in ``pipelines/retrieve_cli.py``)
and add a ``SourceDescriptor`` here. ``lawgraph <phase> <source>`` and ``<phase> all`` are
built from ``SOURCES``; list order is execution order.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Callable

from lawgraph.pipelines.command import PipelineCommand
from lawgraph.pipelines.list_stats import main as list_stats_main
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.normalize.bwb_history import BWBHistoryNormalizePipeline
from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline
from lawgraph.pipelines.normalize.eerstekamer import EerstekamerNormalizePipeline
from lawgraph.pipelines.normalize.eurlex import EurlexNormalizePipeline
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline
from lawgraph.pipelines.normalize.staatscourant import StaatscourantNormalizePipeline
from lawgraph.pipelines.normalize.tk import TKNormalizePipeline
from lawgraph.pipelines.normalize.tk_dossiers import TKDossiersNormalizePipeline
from lawgraph.pipelines.normalize.verdragenbank import VerdragenbankNormalizePipeline
from lawgraph.pipelines.retrieve_cli import (
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
)
from lawgraph.pipelines.semantic.amendment_articles import (
    AmendmentArticlesSemanticPipeline,
)
from lawgraph.pipelines.semantic.annex_links import AnnexLinksSemanticPipeline
from lawgraph.pipelines.semantic.bwb_amendments import BWBAmendmentsSemanticPipeline
from lawgraph.pipelines.semantic.bwb_articles import BWBArticlesSemanticPipeline
from lawgraph.pipelines.semantic.bwb_grondslagen import BWBGrondslagenSemanticPipeline
from lawgraph.pipelines.semantic.echr_citations import ECHRCitationsSemanticPipeline
from lawgraph.pipelines.semantic.eerstekamer_dossier_link import (
    EerstekamerDossierLinkSemanticPipeline,
)
from lawgraph.pipelines.semantic.eu_articles import EUArticlesSemanticPipeline
from lawgraph.pipelines.semantic.instrument_relations import (
    InstrumentRelationsSemanticPipeline,
)
from lawgraph.pipelines.semantic.judgment_appeal import JudgmentAppealSemanticPipeline
from lawgraph.pipelines.semantic.judgment_citations import (
    JudgmentCitationsSemanticPipeline,
)
from lawgraph.pipelines.semantic.mvt_articles import MvtArticlesSemanticPipeline
from lawgraph.pipelines.semantic.rechtspraak_articles import (
    RechtspraakArticlesSemanticPipeline,
)
from lawgraph.pipelines.semantic.relation_semantics import (
    RelationSemanticsSemanticPipeline,
)
from lawgraph.pipelines.semantic.staatsblad_nvt import StaatsbladNvtSemanticPipeline
from lawgraph.pipelines.semantic.staatscourant_regeling import (
    StaatscourantRegelingSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_articles import TKArticlesSemanticPipeline

# Retrieve steps that share a server.
LANE_TWEEDE_KAMER = "tweede_kamer"
LANE_KOOP_REPOSITORY = "koop_repository"  # repository.overheid.nl: SRU and publications


@dataclass(frozen=True)
class RetrieveCtx:
    """Options of ``retrieve all`` that the argv builders translate per source."""

    since: str
    mode: str  # "incremental" | "full"
    window: str | None = (
        None  # full mode: only what changed since then; None: everything
    )


@dataclass(frozen=True)
class SourceDescriptor:
    """The entry points of one source; each is a ``main(argv)`` and each phase is optional.

    ``retrieve_argv_builder`` turns the ``retrieve all`` options into the argv of
    ``retrieve_main``. A source without it is a manual command, left out of ``retrieve all``.
    ``retrieve_lane`` names the server a retrieve step talks to (default: the source id):
    ``retrieve all --jobs N`` runs lanes side by side and the steps of one lane one after
    the other, so no server gets two request streams from us. ``retrieve_after`` names the
    sources whose retrieve must have ended first, because this one reads what they stored.
    Whether a normalize or semantic command has ``--since`` follows from the ``run`` of its
    pipeline (``PipelineCommand.accepts_since``). ``descriptions`` says per phase what the
    command does; it is printed by ``lawgraph sources`` and in the first log line of the step.
    """

    id: str
    display_name: str
    descriptions: Mapping[str, str] = field(
        default_factory=dict
    )  # phase -> what it does
    retrieve_main: Callable[..., None] | None = None
    retrieve_argv_builder: Callable[[RetrieveCtx], list[str]] | None = None
    retrieve_lane: str | None = None
    retrieve_after: tuple[str, ...] = ()
    normalize_main: Callable[..., None] | None = None
    semantic_main: Callable[..., None] | None = None


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


def _mode_and_since_argv(ctx: RetrieveCtx) -> list[str]:
    return ["--mode", ctx.mode, "--since", ctx.since]


def _windowed_argv(ctx: RetrieveCtx) -> list[str]:
    """Sources that keep producing: a full load only reads what changed inside the window."""
    if ctx.mode == "full" and ctx.window:
        return ["--mode", "incremental", "--since", ctx.window]
    return _mode_and_since_argv(ctx)


def _tk_dossiers_argv(ctx: RetrieveCtx) -> list[str]:
    if ctx.mode == "full":
        return ["--since", ctx.window] if ctx.window else []
    return ["--since", ctx.since, "--skip-members"]


# ── Per-source-family registration functions ─────────────────────────────


def _register_tk() -> list[SourceDescriptor]:
    normalize = PipelineCommand(
        TKNormalizePipeline,
        description="Normalize raw TK records.",
    )
    normalize_dossiers = PipelineCommand(
        TKDossiersNormalizePipeline,
        description="Normalize raw TK dossier records.",
    )
    semantic = PipelineCommand(
        TKArticlesSemanticPipeline,
        description="Detect TK references to Dutch and EU articles.",
    )
    return [
        SourceDescriptor(
            id="tk",
            display_name="Tweede Kamer (cases & documents)",
            descriptions={
                "retrieve": ("Tweede Kamer cases (Zaak) from the OData API."),
                "normalize": "Cases as nodes.",
                "semantic": (
                    "Article citations in Tweede Kamer documents: REFERS_TO to BWB and EU articles."
                ),
            },
            retrieve_main=retrieve_tk,
            retrieve_argv_builder=_windowed_argv,
            retrieve_lane=LANE_TWEEDE_KAMER,
            normalize_main=normalize,
            semantic_main=semantic,
        ),
        SourceDescriptor(
            id="tk_dossiers",
            display_name="Tweede Kamer (dossiers, votes, committees)",
            descriptions={
                "retrieve": (
                    "Tweede Kamer dossiers, activities, votes, commitments, committees, members, "
                    "factions and documents."
                ),
                "normalize": (
                    "Committees, members, factions, dossiers, activities, votes, commitments and "
                    "documents as nodes, with their edges."
                ),
            },
            retrieve_main=retrieve_tk_dossiers,
            retrieve_argv_builder=_tk_dossiers_argv,
            retrieve_lane=LANE_TWEEDE_KAMER,
            normalize_main=normalize_dossiers,
        ),
        SourceDescriptor(
            id="tk_content",
            display_name="Tweede Kamer (paper text from XML)",
            descriptions={
                "retrieve": (
                    "Text of Tweede Kamer papers (explanatory memoranda) from their "
                    "XML in the KOOP repository; slow, one XML per paper."
                ),
            },
            # No retrieve_argv_builder: slow (hours), run manually, not part of
            # `retrieve all`.
            retrieve_main=retrieve_tk_content,
        ),
    ]


def _register_rechtspraak() -> list[SourceDescriptor]:
    normalize = PipelineCommand(
        RechtspraakNormalizePipeline,
        description="Normalize raw Rechtspraak records.",
    )
    semantic = PipelineCommand(
        RechtspraakArticlesSemanticPipeline,
        description="Detect references to BWB articles in Rechtspraak judgments.",
    )
    return [
        SourceDescriptor(
            id="rechtspraak",
            display_name="Rechtspraak (judgments)",
            descriptions={
                "retrieve": (
                    "Judgments of the Hoge Raad, Raad van State and gerechtshoven "
                    "(--court), by decision date, and those given with --ecli."
                ),
                "normalize": (
                    "Judgment nodes from the stored judgment XML (court, date, summary, text, "
                    "related ECLIs)."
                ),
                "semantic": "Article citations in judgments: REFERS_TO to BWB articles.",
            },
            retrieve_main=retrieve_rechtspraak,
            retrieve_argv_builder=_windowed_argv,
            normalize_main=normalize,
            semantic_main=semantic,
        ),
    ]


def _register_eurlex() -> list[SourceDescriptor]:
    normalize = PipelineCommand(
        EurlexNormalizePipeline,
        description="Normalize raw EUR-Lex records.",
    )
    semantic = PipelineCommand(
        EUArticlesSemanticPipeline,
        description="Link EU instruments to national and EU articles.",
    )
    return [
        SourceDescriptor(
            id="eurlex",
            display_name="EUR-Lex (EU legislation)",
            descriptions={
                "retrieve": (
                    "EU acts as HTML by CELEX number: those already in the graph (fill-gaps adds "
                    "the ones records refer to)."
                ),
                "normalize": "EU instruments and their articles.",
                "semantic": (
                    "Article citations in EU articles: links EU instruments to national and EU "
                    "articles."
                ),
            },
            retrieve_main=retrieve_eurlex,
            # Never lists acts: the graph (fill-gaps, expand-graph) says which are needed.
            retrieve_argv_builder=_no_argv,
            normalize_main=normalize,
            semantic_main=semantic,
        ),
    ]


def _register_bwb() -> list[SourceDescriptor]:
    normalize = PipelineCommand(
        BWBNormalizePipeline,
        description="Normalize raw BWB records.",
    )
    normalize_history = PipelineCommand(
        BWBHistoryNormalizePipeline,
        description="Normalize historical BWB toestanden.",
    )
    semantic = PipelineCommand(
        BWBArticlesSemanticPipeline,
        description="Detect BWB article references and store REFERS_TO edges.",
        add_args=_bwb_articles_add_args,
        make_extra_kwargs=_bwb_articles_extra_kwargs,
    )
    semantic_grondslagen = PipelineCommand(
        BWBGrondslagenSemanticPipeline,
        description="Create BASED_ON edges from the 'Gelet op' basis of BWB regulations.",
    )
    semantic_amendments = PipelineCommand(
        BWBAmendmentsSemanticPipeline,
        description=(
            "Create AMENDS/INTRODUCES/REPEALS edges from amending publications "
            "and LEGISLATED_IN edges from dossier references."
        ),
    )
    semantic_annexes = PipelineCommand(
        AnnexLinksSemanticPipeline,
        description="Extract annex nodes from BWB XML and create SCOPED_BY edges.",
    )
    return [
        SourceDescriptor(
            id="bwb",
            display_name="BWB (Dutch legislation)",
            descriptions={
                "retrieve": (
                    "Dutch legislation: the current toestand XML and the WTI "
                    "abbreviations of every regulation."
                ),
                "normalize": "Instruments and articles; short titles from the WTI abbreviations.",
                "semantic": "REFERS_TO between articles, read from the XML.",
            },
            retrieve_main=retrieve_bwb,
            retrieve_argv_builder=_mode_argv,
            normalize_main=normalize,
            semantic_main=semantic,
        ),
        SourceDescriptor(
            id="bwb_history",
            display_name="BWB (historical toestanden)",
            descriptions={
                "retrieve": "Every toestand of the given regulations; slow.",
                "normalize": "Article and instrument versions from the stored toestanden.",
            },
            # No retrieve_argv_builder: run manually, not part of `retrieve all`.
            retrieve_main=retrieve_bwb_history,
            normalize_main=normalize_history,
        ),
        SourceDescriptor(
            id="bwb_grondslagen",
            display_name="BWB delegation bases (BASED_ON)",
            descriptions={
                "semantic": (
                    "BASED_ON from a regulation to the article it is issued under ('Gelet op')."
                ),
            },
            semantic_main=semantic_grondslagen,
        ),
        SourceDescriptor(
            id="bwb_amendments",
            display_name="BWB amendments (AMENDS/INTRODUCES/REPEALS/LEGISLATED_IN)",
            descriptions={
                "semantic": (
                    "AMENDS, INTRODUCES and REPEALS from amending publications, and LEGISLATED_IN "
                    "from dossier references."
                ),
            },
            semantic_main=semantic_amendments,
        ),
        SourceDescriptor(
            id="bwb_annexes",
            display_name="BWB annexes (SCOPED_BY)",
            descriptions={
                "semantic": "Annex nodes from the BWB XML and SCOPED_BY edges.",
            },
            semantic_main=semantic_annexes,
        ),
    ]


def _register_staatsblad() -> list[SourceDescriptor]:
    normalize = PipelineCommand(
        StaatsbladNormalizePipeline,
        description="Normalize raw Staatsblad AMvB records.",
    )
    semantic = PipelineCommand(
        StaatsbladNvtSemanticPipeline,
        description="Link Staatsblad NvT publications to BWB instruments.",
    )
    return [
        SourceDescriptor(
            id="staatsblad",
            display_name="Staatsblad (NvT for AMvBs)",
            descriptions={
                "retrieve": (
                    "Staatsblad publications (explanatory notes of AMvBs) as XML, for the "
                    "regulations the stored BWB XML refers to."
                ),
                "normalize": "Publications as documents.",
                "semantic": (
                    "EXPLAINS: links Staatsblad explanatory notes to the instrument they explain."
                ),
            },
            retrieve_main=retrieve_staatsblad,
            retrieve_argv_builder=_no_argv,
            retrieve_lane=LANE_KOOP_REPOSITORY,
            # from-graph: the publications the stored BWB toestanden refer to
            retrieve_after=("bwb",),
            normalize_main=normalize,
            semantic_main=semantic,
        ),
    ]


def _register_staatscourant() -> list[SourceDescriptor]:
    normalize = PipelineCommand(
        StaatscourantNormalizePipeline,
        description="Normalize Staatscourant ministeriele regelingen.",
    )
    semantic = PipelineCommand(
        StaatscourantRegelingSemanticPipeline,
        description="Create EXPLAINS edges from Staatscourant regulations.",
    )
    return [
        SourceDescriptor(
            id="staatscourant",
            display_name="Staatscourant (ministerial regulations)",
            descriptions={
                "retrieve": (
                    "Ministerial regulations from the Staatscourant as XML, via the KOOP SRU."
                ),
                "normalize": "Regulations as documents.",
                "semantic": "EXPLAINS: links Staatscourant regulations to instruments.",
            },
            retrieve_main=retrieve_staatscourant,
            retrieve_argv_builder=_windowed_argv,
            retrieve_lane=LANE_KOOP_REPOSITORY,
            normalize_main=normalize,
            semantic_main=semantic,
        ),
    ]


def _register_eerstekamer() -> list[SourceDescriptor]:
    normalize = PipelineCommand(
        EerstekamerNormalizePipeline,
        description="Normalize Eerste Kamer Kamerstukken.",
    )
    semantic = PipelineCommand(
        EerstekamerDossierLinkSemanticPipeline,
        description="Link Eerste Kamer Kamerstukken to their Tweede Kamer dossier.",
    )
    return [
        SourceDescriptor(
            id="eerstekamer",
            display_name="Eerste Kamer (Kamerstukken)",
            descriptions={
                "retrieve": "Eerste Kamer Kamerstukken from the KOOP SRU (no votes).",
                "normalize": "Kamerstukken as documents, with the dossier number and its addition.",
                "semantic": "PART_OF: links each paper to its Tweede Kamer dossier.",
            },
            retrieve_main=retrieve_eerstekamer,
            retrieve_argv_builder=_windowed_argv,
            retrieve_lane=LANE_KOOP_REPOSITORY,
            normalize_main=normalize,
            semantic_main=semantic,
        ),
    ]


def _register_echr() -> list[SourceDescriptor]:
    normalize = PipelineCommand(
        ECHRNormalizePipeline,
        description="Normalize ECHR HUDOC judgments.",
    )
    semantic = PipelineCommand(
        ECHRCitationsSemanticPipeline,
        description="Create REFERS_TO edges from ECHR judgments to articles and instruments.",
    )
    return [
        SourceDescriptor(
            id="echr",
            display_name="ECHR HUDOC (European Court of Human Rights)",
            descriptions={
                "retrieve": (
                    "European Court of Human Rights judgments against the Netherlands (HUDOC)."
                ),
                "normalize": "Judgments as nodes.",
                "semantic": "REFERS_TO: links ECHR judgments to Convention articles.",
            },
            retrieve_main=retrieve_echr,
            retrieve_argv_builder=_windowed_argv,
            normalize_main=normalize,
            semantic_main=semantic,
        ),
    ]


def _register_verdragenbank() -> list[SourceDescriptor]:
    normalize = PipelineCommand(
        VerdragenbankNormalizePipeline,
        description="Normalize Verdragenbank treaty records.",
    )
    return [
        SourceDescriptor(
            id="verdragenbank",
            display_name="Verdragenbank (Dutch treaties)",
            descriptions={
                "retrieve": "Treaties the Netherlands is party to, from the KOOP SRU.",
                "normalize": "Treaties as instruments.",
            },
            retrieve_main=retrieve_verdragenbank,
            retrieve_argv_builder=_no_argv,
            retrieve_lane=LANE_KOOP_REPOSITORY,
            normalize_main=normalize,
        ),
    ]


def _register_cross_source_semantic() -> list[SourceDescriptor]:
    semantic_judgment_citations = PipelineCommand(
        JudgmentCitationsSemanticPipeline,
        description="Detect ECLI cross-references and create REFERS_TO edges between judgments.",
    )
    semantic_judgment_appeal = PipelineCommand(
        JudgmentAppealSemanticPipeline,
        description="Create APPEAL_OF edges from hoger beroep/cassatie to prior proceedings.",
    )
    semantic_instrument_relations = PipelineCommand(
        InstrumentRelationsSemanticPipeline,
        description="Detect AMENDS and IMPLEMENTS edges between instruments.",
    )
    semantic_amendment_articles = PipelineCommand(
        AmendmentArticlesSemanticPipeline,
        description="Detect amendment language; write AMENDS/INTRODUCES/REPEALS edges.",
    )
    semantic_mvt_articles = PipelineCommand(
        MvtArticlesSemanticPipeline,
        description="Link MvT/NvT documents to the article versions they explain (EXPLAINS).",
    )
    semantic_relation_semantics = PipelineCommand(
        RelationSemanticsSemanticPipeline,
        description="Classify article-to-article REFERS_TO edges with semantic relationship types.",
    )
    return [
        SourceDescriptor(
            id="judgment_citations",
            display_name="Rechtspraak citation analysis (REFERS_TO)",
            descriptions={
                "semantic": (
                    "ECLI references between judgments: REFERS_TO; cited judgments that are not "
                    "loaded become stubs."
                ),
            },
            semantic_main=semantic_judgment_citations,
        ),
        SourceDescriptor(
            id="judgment_appeal",
            display_name="Rechtspraak appeal chain (APPEAL_OF)",
            descriptions={
                "semantic": (
                    "APPEAL_OF from appeal and cassation judgments to the earlier proceedings."
                ),
            },
            semantic_main=semantic_judgment_appeal,
        ),
        SourceDescriptor(
            id="instrument_relations",
            display_name="Instrument relations (AMENDS / IMPLEMENTS)",
            descriptions={
                "semantic": "AMENDS and IMPLEMENTS between instruments.",
            },
            semantic_main=semantic_instrument_relations,
        ),
        SourceDescriptor(
            id="amendment_articles",
            display_name="Amendment to article links (AMENDS / INTRODUCES / REPEALS)",
            descriptions={
                "semantic": (
                    "Amendment language in Tweede Kamer documents, linked to the articles it "
                    "changes."
                ),
            },
            semantic_main=semantic_amendment_articles,
        ),
        SourceDescriptor(
            id="mvt_articles",
            display_name="Explanatory memorandum to article links (EXPLAINS)",
            descriptions={
                "semantic": "EXPLAINS: links explanatory memoranda to what they explain.",
            },
            semantic_main=semantic_mvt_articles,
        ),
        # Runs after bwb_articles (registry order == orchestrator order) so the
        # REFERS_TO edges it classifies already exist.
        SourceDescriptor(
            id="relation_semantics",
            display_name="Semantic relationship types (article to article)",
            descriptions={
                "semantic": "Classifies article-to-article REFERS_TO edges by what they mean.",
            },
            semantic_main=semantic_relation_semantics,
        ),
        # Last: counts the edges written by every step above.
        SourceDescriptor(
            id="list_stats",
            display_name="List endpoint sort and filter fields",
            descriptions={
                "semantic": "Precomputes the sort and filter fields of the list endpoints.",
            },
            semantic_main=list_stats_main,
        ),
    ]


def _build_registry() -> list[SourceDescriptor]:
    return [
        *_register_tk(),
        *_register_rechtspraak(),
        *_register_eurlex(),
        *_register_bwb(),
        *_register_staatsblad(),
        *_register_staatscourant(),
        *_register_eerstekamer(),
        *_register_echr(),
        *_register_verdragenbank(),
        *_register_cross_source_semantic(),
    ]


SOURCES: list[SourceDescriptor] = _build_registry()


def describe(phase: str, source_id: str) -> str:
    """What ``<phase> <source>`` does, or an empty string."""
    for source in SOURCES:
        if source.id == source_id.replace("-", "_"):
            return source.descriptions.get(phase, "")
    return ""
