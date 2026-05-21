"""Declarative registry of all data sources and their pipeline entry points.

Adding a new source means:
  1. Write a retrieve CLI entry point in pipelines/retrieve_cli.py.
  2. Write normalize and/or semantic pipeline classes in pipelines/.
  3. Add a SourceDescriptor here — no other files need changing.

The orchestrators in pipelines/orchestration.py iterate SOURCES to build their
step lists automatically.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable

from lawgraph.pipelines.factory import make_pipeline_cli
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.normalize.bwb_history import BWBHistoryNormalizePipeline
from lawgraph.pipelines.normalize.echr import EchrNormalizePipeline
from lawgraph.pipelines.normalize.eerstekamer import EerstekamerNormalizePipeline
from lawgraph.pipelines.normalize.eurlex import EUNormalizePipeline
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline
from lawgraph.pipelines.normalize.staatscourant import StaatscourantNormalizePipeline
from lawgraph.pipelines.normalize.tk import TkNormalizePipeline
from lawgraph.pipelines.normalize.tk_dossiers import TkDossiersNormalizePipeline
from lawgraph.pipelines.normalize.verdragenbank import VerdragenbankNormalizePipeline
from lawgraph.pipelines.retrieve_cli import (
    retrieve_bwb,
    retrieve_echr,
    retrieve_eerstekamer,
    retrieve_eurlex,
    retrieve_rechtspraak,
    retrieve_staatsblad,
    retrieve_staatscourant,
    retrieve_tk,
    retrieve_tk_dossiers,
    retrieve_verdragenbank,
)
from lawgraph.pipelines.semantic.amendment_articles import AmendmentArticlePipeline
from lawgraph.pipelines.semantic.bwb_articles import BwbArticlesSemanticPipeline
from lawgraph.pipelines.semantic.bwb_grondslagen import BWBGrondslagenSemanticPipeline
from lawgraph.pipelines.semantic.dossier_law_link import DossierLawLinkPipeline
from lawgraph.pipelines.semantic.echr_citations import EchrCitationsPipeline
from lawgraph.pipelines.semantic.eerstekamer_dossier_link import (
    EerstekamerDossierLinkPipeline,
)
from lawgraph.pipelines.semantic.eu_articles import EUArticleSemanticPipeline
from lawgraph.pipelines.semantic.instrument_relations import InstrumentRelationsPipeline
from lawgraph.pipelines.semantic.judgment_appeal import JudgmentAppealPipeline
from lawgraph.pipelines.semantic.judgment_citations import (
    JudgmentCitationsSemanticPipeline,
)
from lawgraph.pipelines.semantic.mvt_articles import MvtArticleSemanticPipeline
from lawgraph.pipelines.semantic.rechtspraak_articles import (
    RechtspraakArticleSemanticPipeline,
)
from lawgraph.pipelines.semantic.staatsblad_nvt import StaatsbladNvtSemanticPipeline
from lawgraph.pipelines.semantic.staatscourant_regeling import (
    StaatscourantRegelingSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_articles import TKArticleSemanticPipeline
from lawgraph.pipelines.semantic.version_causes import VersionCausesSemanticPipeline


@dataclass(frozen=True)
class RetrieveCtx:
    """Context passed to retrieve_argv_builder callables."""

    since_days: int
    mode: str  # "incremental" | "full"

    @property
    def mode_arg(self) -> list[str]:
        return ["--mode", self.mode]

    @property
    def since_arg(self) -> list[str]:
        return ["--since-days", str(self.since_days)]

    def as_argv(self) -> list[str]:
        """Return combined [--mode, <mode>, --since-days, <days>] argv."""
        return [*self.mode_arg, *self.since_arg]


@dataclass(frozen=True)
class SourceDescriptor:
    """Declarative description of a data source and its pipeline entry points.

    Each phase (retrieve / normalize / semantic) is optional. When a phase
    has no entry point, that step is simply skipped by the orchestrators.

    retrieve_main, normalize_main, semantic_main are all callables that accept
    an optional ``argv`` list (same interface as a CLI main() function).

    retrieve_argv_builder, when provided, lets run_retrieve_all build the argv
    for retrieve_main automatically from the orchestrator context. Sources that
    omit this field are skipped by run_retrieve_all.
    """

    id: str
    display_name: str

    retrieve_main: Callable[..., None] | None = None
    retrieve_argv_builder: Callable[[RetrieveCtx], list[str]] | None = None
    retrieve_skip_env: str | None = None

    normalize_main: Callable[..., None] | None = None
    normalize_skip_env: str | None = None

    semantic_main: Callable[..., None] | None = None
    semantic_skip_env: str | None = None

    supports_full_load: bool = False


# ── Extra args for semantic pipelines with non-standard constructor args ──


def _bwb_articles_add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store-citations", action="store_true")


def _bwb_articles_extra_kwargs(args: argparse.Namespace) -> dict:
    return {"store_citations": args.store_citations}


def _version_causes_add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--window-days", type=int, default=365)


def _version_causes_extra_kwargs(args: argparse.Namespace) -> dict:
    return {"window_days": args.window_days}


# ── Shared retrieve-argv builder helpers ─────────────────────────────────

_NO_ARGV: Callable[[RetrieveCtx], list[str]] = lambda ctx: []
_MODE_ONLY_ARGV: Callable[[RetrieveCtx], list[str]] = lambda ctx: [*ctx.mode_arg]

# ── Named retrieve-argv builders for complex argv shapes ─────────────────


def _tk_dossiers_retrieve_args(ctx: RetrieveCtx) -> list[str]:
    if ctx.mode == "full":
        return []
    return [
        "--since",
        f"{ctx.since_days}d",
        "--skip-personen",
        "--stemmingen-since",
        f"{ctx.since_days}d",
        "--documents-since",
        f"{ctx.since_days}d",
    ]


# ── Per-source-family registration functions ─────────────────────────────


def _register_tk() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        TkNormalizePipeline,
        description="Normalize raw TK records.",
        with_since=True,
    )
    normalize_dossiers = make_pipeline_cli(
        TkDossiersNormalizePipeline,
        description="Normalize raw TK dossier records.",
        with_since=True,
    )
    semantic = make_pipeline_cli(
        TKArticleSemanticPipeline,
        description="Detect TK references to Dutch and EU articles.",
        with_since_days=True,
    )
    return [
        SourceDescriptor(
            id="tk",
            display_name="Tweede Kamer (zaken & documenten)",
            retrieve_main=retrieve_tk,
            retrieve_argv_builder=RetrieveCtx.as_argv,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_TK",
            normalize_main=normalize,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_TK",
            semantic_main=semantic,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_TK",
            supports_full_load=True,
        ),
        SourceDescriptor(
            id="tk_dossiers",
            display_name="Tweede Kamer (dossiers, stemmingen, commissies)",
            retrieve_main=retrieve_tk_dossiers,
            retrieve_argv_builder=_tk_dossiers_retrieve_args,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_TK_DOSSIERS",
            normalize_main=normalize_dossiers,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS",
            supports_full_load=True,
        ),
    ]


def _register_rechtspraak() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        RechtspraakNormalizePipeline,
        description="Normalize raw Rechtspraak records.",
        with_since=True,
    )
    semantic = make_pipeline_cli(
        RechtspraakArticleSemanticPipeline,
        description="Detect references to BWB articles in Rechtspraak judgments.",
        with_since_days=True,
    )
    return [
        SourceDescriptor(
            id="rechtspraak",
            display_name="Rechtspraak (uitspraken)",
            retrieve_main=retrieve_rechtspraak,
            retrieve_argv_builder=RetrieveCtx.as_argv,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_RECHTSPRAAK",
            normalize_main=normalize,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_RECHTSPRAAK",
            semantic_main=semantic,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_RECHTSPRAAK",
            supports_full_load=True,
        ),
    ]


def _register_eurlex() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        EUNormalizePipeline,
        description="Normalize raw EUR-Lex records.",
        with_since=True,
    )
    semantic = make_pipeline_cli(
        EUArticleSemanticPipeline,
        description="Link EU instruments to national/EU articles.",
        with_since_days=True,
    )
    return [
        SourceDescriptor(
            id="eurlex",
            display_name="EUR-Lex (EU-wetgeving)",
            retrieve_main=retrieve_eurlex,
            retrieve_argv_builder=_MODE_ONLY_ARGV,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_EURLEX",
            normalize_main=normalize,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_EURLEX",
            semantic_main=semantic,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_EURLEX",
            supports_full_load=True,
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
        BwbArticlesSemanticPipeline,
        description="Detect BWB article references and store REFERS_TO_ARTICLE edges.",
        add_args=_bwb_articles_add_args,
        make_extra_kwargs=_bwb_articles_extra_kwargs,
    )
    semantic_grondslagen = make_pipeline_cli(
        BWBGrondslagenSemanticPipeline,
        description="Create DELEGATED_BY edges from BWB AMvB grondslagen.",
    )
    return [
        SourceDescriptor(
            id="bwb",
            display_name="BWB (Nederlandse wetgeving)",
            retrieve_main=retrieve_bwb,
            retrieve_argv_builder=_MODE_ONLY_ARGV,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_BWB",
            normalize_main=normalize,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_BWB",
            semantic_main=semantic,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_BWB",
            supports_full_load=True,
        ),
        SourceDescriptor(
            id="bwb_history",
            display_name="BWB (historische toestanden)",
            normalize_main=normalize_history,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_BWB_HISTORY",
        ),
        SourceDescriptor(
            id="bwb_grondslagen",
            display_name="BWB grondslagen (DELEGATED_BY)",
            semantic_main=semantic_grondslagen,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_BWB_GRONDSLAGEN",
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
        with_since=True,
    )
    return [
        SourceDescriptor(
            id="staatsblad",
            display_name="Staatsblad (NvT voor AMvBs)",
            retrieve_main=retrieve_staatsblad,
            retrieve_argv_builder=_NO_ARGV,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_STAATSBLAD",
            normalize_main=normalize,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_STAATSBLAD",
            semantic_main=semantic,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_STAATSBLAD",
            supports_full_load=True,
        ),
    ]


def _register_staatscourant() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        StaatscourantNormalizePipeline,
        description="Normalize Staatscourant ministeriele regelingen.",
    )
    semantic = make_pipeline_cli(
        StaatscourantRegelingSemanticPipeline,
        description="Create EXPLAINS_INSTRUMENT edges from Staatscourant regelingen.",
    )
    return [
        SourceDescriptor(
            id="staatscourant",
            display_name="Staatscourant (ministeriele regelingen)",
            retrieve_main=retrieve_staatscourant,
            retrieve_argv_builder=_MODE_ONLY_ARGV,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_STAATSCOURANT",
            normalize_main=normalize,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_STAATSCOURANT",
            semantic_main=semantic,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_STAATSCOURANT",
            supports_full_load=True,
        ),
    ]


def _register_eerstekamer() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        EerstekamerNormalizePipeline,
        description="Normalize Eerste Kamer Kamerstukken.",
    )
    semantic = make_pipeline_cli(
        EerstekamerDossierLinkPipeline,
        description="Create DEEL_VAN_DOSSIER edges from EK stukken to TK kamerstukdossiers.",
    )
    return [
        SourceDescriptor(
            id="eerstekamer",
            display_name="Eerste Kamer (kamerstukken & stemmingen)",
            retrieve_main=retrieve_eerstekamer,
            retrieve_argv_builder=_MODE_ONLY_ARGV,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_EERSTEKAMER",
            normalize_main=normalize,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_EERSTEKAMER",
            semantic_main=semantic,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_EERSTEKAMER",
            supports_full_load=True,
        ),
    ]


def _register_echr() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        EchrNormalizePipeline,
        description="Normalize ECHR HUDOC judgments.",
    )
    semantic = make_pipeline_cli(
        EchrCitationsPipeline,
        description="Create CITES_ARTICLE and MENTIONS_INSTRUMENT edges from ECHR judgments.",
    )
    return [
        SourceDescriptor(
            id="echr",
            display_name="ECHR HUDOC (Europees Hof voor de Rechten van de Mens)",
            retrieve_main=retrieve_echr,
            retrieve_argv_builder=_MODE_ONLY_ARGV,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_ECHR",
            normalize_main=normalize,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_ECHR",
            semantic_main=semantic,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_ECHR",
            supports_full_load=True,
        ),
    ]


def _register_verdragenbank() -> list[SourceDescriptor]:
    normalize = make_pipeline_cli(
        VerdragenbankNormalizePipeline,
        description="Normalize Verdragenbank treaty records.",
    )
    return [
        SourceDescriptor(
            id="verdragenbank",
            display_name="Verdragenbank (Nederlandse verdragen)",
            retrieve_main=retrieve_verdragenbank,
            retrieve_argv_builder=_NO_ARGV,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_VERDRAGENBANK",
            normalize_main=normalize,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_VERDRAGENBANK",
            supports_full_load=True,
        ),
    ]


def _register_cross_source_semantic() -> list[SourceDescriptor]:
    semantic_judgment_citations = make_pipeline_cli(
        JudgmentCitationsSemanticPipeline,
        description="Detect ECLI cross-references and create CITES_JUDGMENT edges.",
        with_since_days=True,
    )
    semantic_judgment_appeal = make_pipeline_cli(
        JudgmentAppealPipeline,
        description="Create APPEAL_OF edges from hoger beroep/cassatie to prior proceedings.",
    )
    semantic_instrument_relations = make_pipeline_cli(
        InstrumentRelationsPipeline,
        description="Detect AMENDS_INSTRUMENT and IMPLEMENTS_DIRECTIVE edges.",
    )
    semantic_amendment_articles = make_pipeline_cli(
        AmendmentArticlePipeline,
        description="Detect amendment language; write WIJZIGT/INTRODUCEERT/TREKT_IN edges.",
        with_since_days=True,
    )
    semantic_mvt_articles = make_pipeline_cli(
        MvtArticleSemanticPipeline,
        description="Link MvT/NvT publications to instrument articles via LICHT_TOE edges.",
        with_since=True,
    )
    semantic_dossier_law_link = make_pipeline_cli(
        DossierLawLinkPipeline,
        description="Create RESULTED_IN edges from kamerstukdossiers to BWB instruments.",
    )
    semantic_version_causes = make_pipeline_cli(
        VersionCausesSemanticPipeline,
        description="Create CAUSED_VERSION edges from publications to instrument_article_versions.",
        add_args=_version_causes_add_args,
        make_extra_kwargs=_version_causes_extra_kwargs,
    )
    return [
        SourceDescriptor(
            id="judgment_citations",
            display_name="Rechtspraak citaatanalyse (CITES_JUDGMENT)",
            semantic_main=semantic_judgment_citations,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_JUDGMENT_CITATIONS",
        ),
        SourceDescriptor(
            id="judgment_appeal",
            display_name="Rechtspraak beroepsinstanties (APPEAL_OF)",
            semantic_main=semantic_judgment_appeal,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_JUDGMENT_APPEAL",
        ),
        SourceDescriptor(
            id="instrument_relations",
            display_name="Instrumentrelaties (AMENDS / IMPLEMENTS)",
            semantic_main=semantic_instrument_relations,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_INSTRUMENT_RELATIONS",
        ),
        SourceDescriptor(
            id="amendment_articles",
            display_name="Amendement-artikel koppeling (semantisch)",
            semantic_main=semantic_amendment_articles,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_AMENDMENT_ARTICLES",
        ),
        SourceDescriptor(
            id="mvt_articles",
            display_name="MvT-artikel koppeling (LICHT_TOE)",
            semantic_main=semantic_mvt_articles,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_MVT_ARTICLES",
        ),
        SourceDescriptor(
            id="dossier_law_link",
            display_name="Dossier → wet koppeling (RESULTED_IN)",
            semantic_main=semantic_dossier_law_link,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_DOSSIER_LAW_LINK",
        ),
        SourceDescriptor(
            id="version_causes",
            display_name="Versie-oorzaken (CAUSED_VERSION)",
            semantic_main=semantic_version_causes,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_VERSION_CAUSES",
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
