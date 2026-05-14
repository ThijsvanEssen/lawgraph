"""lawgraph.api.queries — public re-exports from the queries sub-package.

All names that were previously importable from ``lawgraph.api.queries``
remain importable from here unchanged, so existing route and pipeline
imports require no modification.
"""

from __future__ import annotations

# ── articles ──────────────────────────────────────────────────────────────────
from lawgraph.api.queries.articles import (
    ArticleCitationEntry,
    ArticleDetailData,
    get_article_citations,
    get_article_in_flux,
    get_article_legislative_history,
    get_article_with_relations,
)

# ── commissies ────────────────────────────────────────────────────────────────
from lawgraph.api.queries.commissies import (
    get_actor_touched_instruments,
    get_all_commissies,
    get_all_commissies_with_leden,
    get_all_fracties,
    get_all_leden,
    get_commissie_detail,
    get_lid_touched_instruments,
    get_lid_votes,
)

# ── dossiers ──────────────────────────────────────────────────────────────────
from lawgraph.api.queries.dossiers import (
    DOSSIER_STAGES,
    DOSSIER_TRAJECT_KINDS,
    DossierEnrichment,
    classify_doc_soort,
    classify_traject_kind,
    classify_zaak_soort,
    enrich_dossier_docs,
    get_documents_for_dossiers,
    get_dossier_by_nummer,
    get_dossier_documents,
    get_dossier_mutations,
    get_dossier_timeline,
    get_open_dossiers,
    get_recent_dossiers,
)

# ── graph ─────────────────────────────────────────────────────────────────────
from lawgraph.api.queries.graph import (
    GlobalGraphData,
    InstrumentLayerData,
    JudgmentGraphData,
    _GraphEdge,
    get_global_graph,
    get_instrument_layer_graph,
    get_judgment_graph,
)

# ── instruments ───────────────────────────────────────────────────────────────
from lawgraph.api.queries.instruments import (
    INSTRUMENT_SORTS,
    InstrumentStats,
    get_instrument_article_history,
    get_instrument_articles,
    get_instrument_articles_at,
    get_instrument_dossiers,
    get_instrument_edges_bundle,
    get_instrument_judgments,
    get_instrument_related_instruments,
    get_instrument_versions,
    get_instruments_list,
)

# ── judgments ─────────────────────────────────────────────────────────────────
from lawgraph.api.queries.judgments import (
    JUDGMENT_SORTS,
    JudgmentArticleRelation,
    JudgmentDetailData,
    derive_judgment_tier,
    get_judgment_with_relations,
    get_judgments_list,
)

# ── nodes ─────────────────────────────────────────────────────────────────────
from lawgraph.api.queries.nodes import (
    NeighborEntry,
    NodeGraphData,
    get_node_neighborhood,
    get_node_with_neighbors,
)

# ── overlay ───────────────────────────────────────────────────────────────────
from lawgraph.api.queries.overlay import get_heat_counts, get_in_flux_counts

# ── search ────────────────────────────────────────────────────────────────────
from lawgraph.api.queries.search import (
    _build_search_clause,
    _load_instrument_alias_map,
    _parse_search_query,
    _tokenize_search_query,
    search_all,
)

# ── stats ─────────────────────────────────────────────────────────────────────
from lawgraph.api.queries.stats import get_db_stats, get_edge_status_log

# ── stemmingen ────────────────────────────────────────────────────────────────
from lawgraph.api.queries.stemmingen import (
    get_stemming_detail,
    get_stemming_publication,
    get_stemmingen,
)

# ── watches ───────────────────────────────────────────────────────────────────
from lawgraph.api.queries.watches import create_watch, delete_watch, list_watches

__all__ = [
    # dossiers
    "DOSSIER_STAGES",
    "DOSSIER_TRAJECT_KINDS",
    "DossierEnrichment",
    "classify_doc_soort",
    "classify_traject_kind",
    "classify_zaak_soort",
    "enrich_dossier_docs",
    "get_documents_for_dossiers",
    "get_dossier_by_nummer",
    "get_dossier_documents",
    "get_dossier_mutations",
    "get_dossier_timeline",
    "get_open_dossiers",
    "get_recent_dossiers",
    # articles
    "ArticleCitationEntry",
    "ArticleDetailData",
    "get_article_citations",
    "get_article_in_flux",
    "get_article_legislative_history",
    "get_article_with_relations",
    # instruments
    "INSTRUMENT_SORTS",
    "InstrumentStats",
    "get_instrument_article_history",
    "get_instrument_articles",
    "get_instrument_articles_at",
    "get_instrument_dossiers",
    "get_instrument_edges_bundle",
    "get_instrument_judgments",
    "get_instrument_related_instruments",
    "get_instrument_versions",
    "get_instruments_list",
    # judgments
    "JUDGMENT_SORTS",
    "JudgmentArticleRelation",
    "JudgmentDetailData",
    "derive_judgment_tier",
    "get_judgment_with_relations",
    "get_judgments_list",
    # nodes
    "NeighborEntry",
    "NodeGraphData",
    "get_node_neighborhood",
    "get_node_with_neighbors",
    # commissies
    "get_actor_touched_instruments",
    "get_all_commissies",
    "get_all_commissies_with_leden",
    "get_all_fracties",
    "get_all_leden",
    "get_commissie_detail",
    "get_lid_touched_instruments",
    "get_lid_votes",
    # stats
    "get_db_stats",
    "get_edge_status_log",
    # search
    "_build_search_clause",
    "_load_instrument_alias_map",
    "_parse_search_query",
    "_tokenize_search_query",
    "search_all",
    # stemmingen
    "get_stemming_detail",
    "get_stemming_publication",
    "get_stemmingen",
    # overlay
    "get_heat_counts",
    "get_in_flux_counts",
    # watches
    "create_watch",
    "delete_watch",
    "list_watches",
    # graph
    "GlobalGraphData",
    "InstrumentLayerData",
    "JudgmentGraphData",
    "_GraphEdge",
    "get_global_graph",
    "get_instrument_layer_graph",
    "get_judgment_graph",
]
