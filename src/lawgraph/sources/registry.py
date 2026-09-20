"""Registry of all sources: the single definition of CLI commands and their order.

Adding a source: write its pipelines (and a retrieve command in ``pipelines/retrieve_cli.py``)
and add a ``SourceDescriptor`` here. ``lawgraph <phase> <source>`` and ``<phase> all`` are
built from ``SOURCES``; list order is execution order.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable

from lawgraph.pipelines.factory import make_pipeline_cli
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
    the other, so no server gets two request streams from us.
    Every normalize command accepts ``--since``; a semantic command only when
    ``semantic_accepts_since`` is set.
    """

    id: str
    display_name: str
    retrieve_main: Callable[..., None] | None = None
    retrieve_argv_builder: Callable[[RetrieveCtx], list[str]] | None = None
    retrieve_lane: str | None = None
    normalize_main: Callable[..., None] | None = None
    semantic_main: Callable[..., None] | None = None
    semantic_accepts_since: bool = False


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
    normalize = make_pipeline_cli(
        TKNormalizePipeline,
        description="Normalize raw TK records.",
        with_since=True,
    )
    normalize_dossiers = make_pipeline_cli(
        TKDossiersNormalizePipeline,
        description="Normalize raw TK dossier records.",
        with_since=True,
    )
    semantic = make_pipeline_cli(
        TKArticlesSemanticPipeline,
        description="Detect TK references to Dutch and EU articles.",
        with_since=True,
    )
    return [
        SourceDescriptor(
            id="tk",
            display_name="Tweede Kamer (cases & documents)",
            retrieve_main=retrieve_tk,
            retrieve_argv_builder=_windowed_argv,
            retrieve_lane=LANE_TWEEDE_KAMER,
            normalize_main=normalize,
            semantic_main=semantic,
            semantic_accepts_since=True,
        ),
        SourceDescriptor(
            id="tk_dossiers",
            display_name="Tweede Kamer (dossiers, votes, committees)",
            retrieve_main=retrieve_tk_dossiers,
            retrieve_argv_builder=_tk_dossiers_argv,
            retrieve_lane=LANE_TWEEDE_KAMER,
            normalize_main=normalize_dossiers,
        ),
        SourceDescriptor(
            id="tk_content",
            display_name="Tweede Kamer (document text from PDF)",
            # No retrieve_argv_builder: slow (hours), run manually, not part of
            # `retrieve all`.
            retrieve_main=retrieve_tk_content,
        ),
    ]


def _register_rechtspraak() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        RechtspraakNormalizePipeline,
        description="Normalize raw Rechtspraak records.",
        with_since=True,
    )
    semantic = make_pipeline_cli(
        RechtspraakArticlesSemanticPipeline,
        description="Detect references to BWB articles in Rechtspraak judgments.",
        with_since=True,
    )
    return [
        SourceDescriptor(
            id="rechtspraak",
            display_name="Rechtspraak (judgments)",
            retrieve_main=retrieve_rechtspraak,
            retrieve_argv_builder=_windowed_argv,
            normalize_main=normalize,
            semantic_main=semantic,
            semantic_accepts_since=True,
        ),
    ]


def _register_eurlex() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        EurlexNormalizePipeline,
        description="Normalize raw EUR-Lex records.",
        with_since=True,
    )
    semantic = make_pipeline_cli(
        EUArticlesSemanticPipeline,
        description="Link EU instruments to national and EU articles.",
        with_since=True,
    )
    return [
        SourceDescriptor(
            id="eurlex",
            display_name="EUR-Lex (EU legislation)",
            retrieve_main=retrieve_eurlex,
            # Never lists acts: the graph (fill-gaps, expand-graph) says which are needed.
            retrieve_argv_builder=_no_argv,
            normalize_main=normalize,
            semantic_main=semantic,
            semantic_accepts_since=True,
        ),
    ]


def _register_bwb() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        BWBNormalizePipeline,
        description="Normalize raw BWB records.",
        with_since=True,
    )
    normalize_history = make_pipeline_cli(
        BWBHistoryNormalizePipeline,
        description="Normalize historical BWB toestanden.",
        with_since=True,
    )
    semantic = make_pipeline_cli(
        BWBArticlesSemanticPipeline,
        description="Detect BWB article references and store REFERS_TO edges.",
        with_since=True,
        add_args=_bwb_articles_add_args,
        make_extra_kwargs=_bwb_articles_extra_kwargs,
    )
    semantic_grondslagen = make_pipeline_cli(
        BWBGrondslagenSemanticPipeline,
        description="Create BASED_ON edges from the 'Gelet op' basis of BWB regulations.",
    )
    semantic_amendments = make_pipeline_cli(
        BWBAmendmentsSemanticPipeline,
        description=(
            "Create AMENDS/INTRODUCES/REPEALS edges from amending publications "
            "and LEGISLATED_IN edges from dossier references."
        ),
    )
    semantic_annexes = make_pipeline_cli(
        AnnexLinksSemanticPipeline,
        description="Extract annex nodes from BWB XML and create SCOPED_BY edges.",
    )
    return [
        SourceDescriptor(
            id="bwb",
            display_name="BWB (Dutch legislation)",
            retrieve_main=retrieve_bwb,
            retrieve_argv_builder=_mode_argv,
            normalize_main=normalize,
            semantic_main=semantic,
            semantic_accepts_since=True,
        ),
        SourceDescriptor(
            id="bwb_history",
            display_name="BWB (historical toestanden)",
            # No retrieve_argv_builder: run manually, not part of `retrieve all`.
            retrieve_main=retrieve_bwb_history,
            normalize_main=normalize_history,
        ),
        SourceDescriptor(
            id="bwb_grondslagen",
            display_name="BWB delegation bases (BASED_ON)",
            semantic_main=semantic_grondslagen,
        ),
        SourceDescriptor(
            id="bwb_amendments",
            display_name="BWB amendments (AMENDS/INTRODUCES/REPEALS/LEGISLATED_IN)",
            semantic_main=semantic_amendments,
        ),
        SourceDescriptor(
            id="bwb_annexes",
            display_name="BWB annexes (SCOPED_BY)",
            semantic_main=semantic_annexes,
        ),
    ]


def _register_staatsblad() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        StaatsbladNormalizePipeline,
        description="Normalize raw Staatsblad AMvB records.",
        with_since=True,
    )
    semantic = make_pipeline_cli(
        StaatsbladNvtSemanticPipeline,
        description="Link Staatsblad NvT publications to BWB instruments.",
    )
    return [
        SourceDescriptor(
            id="staatsblad",
            display_name="Staatsblad (NvT for AMvBs)",
            retrieve_main=retrieve_staatsblad,
            retrieve_argv_builder=_no_argv,
            retrieve_lane=LANE_KOOP_REPOSITORY,
            normalize_main=normalize,
            semantic_main=semantic,
        ),
    ]


def _register_staatscourant() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        StaatscourantNormalizePipeline,
        description="Normalize Staatscourant ministeriele regelingen.",
        with_since=True,
    )
    semantic = make_pipeline_cli(
        StaatscourantRegelingSemanticPipeline,
        description="Create EXPLAINS edges from Staatscourant regulations.",
        with_since=True,
    )
    return [
        SourceDescriptor(
            id="staatscourant",
            display_name="Staatscourant (ministerial regulations)",
            retrieve_main=retrieve_staatscourant,
            retrieve_argv_builder=_windowed_argv,
            retrieve_lane=LANE_KOOP_REPOSITORY,
            normalize_main=normalize,
            semantic_main=semantic,
            semantic_accepts_since=True,
        ),
    ]


def _register_eerstekamer() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        EerstekamerNormalizePipeline,
        description="Normalize Eerste Kamer Kamerstukken.",
        with_since=True,
    )
    semantic = make_pipeline_cli(
        EerstekamerDossierLinkSemanticPipeline,
        description="Link Eerste Kamer Kamerstukken to their Tweede Kamer dossier.",
    )
    return [
        SourceDescriptor(
            id="eerstekamer",
            display_name="Eerste Kamer (Kamerstukken)",
            retrieve_main=retrieve_eerstekamer,
            retrieve_argv_builder=_windowed_argv,
            retrieve_lane=LANE_KOOP_REPOSITORY,
            normalize_main=normalize,
            semantic_main=semantic,
        ),
    ]


def _register_echr() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        ECHRNormalizePipeline,
        description="Normalize ECHR HUDOC judgments.",
        with_since=True,
    )
    semantic = make_pipeline_cli(
        ECHRCitationsSemanticPipeline,
        description="Create REFERS_TO edges from ECHR judgments to articles and instruments.",
    )
    return [
        SourceDescriptor(
            id="echr",
            display_name="ECHR HUDOC (European Court of Human Rights)",
            retrieve_main=retrieve_echr,
            retrieve_argv_builder=_windowed_argv,
            normalize_main=normalize,
            semantic_main=semantic,
        ),
    ]


def _register_verdragenbank() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        VerdragenbankNormalizePipeline,
        description="Normalize Verdragenbank treaty records.",
        with_since=True,
    )
    return [
        SourceDescriptor(
            id="verdragenbank",
            display_name="Verdragenbank (Dutch treaties)",
            retrieve_main=retrieve_verdragenbank,
            retrieve_argv_builder=_no_argv,
            retrieve_lane=LANE_KOOP_REPOSITORY,
            normalize_main=normalize,
        ),
    ]


def _register_cross_source_semantic() -> list[SourceDescriptor]:
    semantic_judgment_citations = make_pipeline_cli(
        JudgmentCitationsSemanticPipeline,
        description="Detect ECLI cross-references and create REFERS_TO edges between judgments.",
    )
    semantic_judgment_appeal = make_pipeline_cli(
        JudgmentAppealSemanticPipeline,
        description="Create APPEAL_OF edges from hoger beroep/cassatie to prior proceedings.",
    )
    semantic_instrument_relations = make_pipeline_cli(
        InstrumentRelationsSemanticPipeline,
        description="Detect AMENDS and IMPLEMENTS edges between instruments.",
        with_since=True,
    )
    semantic_amendment_articles = make_pipeline_cli(
        AmendmentArticlesSemanticPipeline,
        description="Detect amendment language; write AMENDS/INTRODUCES/REPEALS edges.",
    )
    semantic_mvt_articles = make_pipeline_cli(
        MvtArticlesSemanticPipeline,
        description="Link MvT/NvT documents to the article versions they explain (EXPLAINS).",
    )
    semantic_relation_semantics = make_pipeline_cli(
        RelationSemanticsSemanticPipeline,
        description="Classify article-to-article REFERS_TO edges with semantic relationship types.",
    )
    return [
        SourceDescriptor(
            id="judgment_citations",
            display_name="Rechtspraak citation analysis (REFERS_TO)",
            semantic_main=semantic_judgment_citations,
        ),
        SourceDescriptor(
            id="judgment_appeal",
            display_name="Rechtspraak appeal chain (APPEAL_OF)",
            semantic_main=semantic_judgment_appeal,
        ),
        SourceDescriptor(
            id="instrument_relations",
            display_name="Instrument relations (AMENDS / IMPLEMENTS)",
            semantic_main=semantic_instrument_relations,
            semantic_accepts_since=True,
        ),
        SourceDescriptor(
            id="amendment_articles",
            display_name="Amendment to article links (AMENDS / INTRODUCES / REPEALS)",
            semantic_main=semantic_amendment_articles,
        ),
        SourceDescriptor(
            id="mvt_articles",
            display_name="Explanatory memorandum to article links (EXPLAINS)",
            semantic_main=semantic_mvt_articles,
        ),
        # Runs after bwb_articles (registry order == orchestrator order) so the
        # REFERS_TO edges it classifies already exist.
        SourceDescriptor(
            id="relation_semantics",
            display_name="Semantic relationship types (article to article)",
            semantic_main=semantic_relation_semantics,
        ),
        # Last: counts the edges written by every step above.
        SourceDescriptor(
            id="list_stats",
            display_name="List endpoint sort and filter fields",
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
