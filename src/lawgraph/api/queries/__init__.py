"""lawgraph.api.queries — public re-exports from the queries sub-package.

All names that were previously importable from ``lawgraph.api.queries``
remain importable from here unchanged, so existing route and pipeline
imports require no modification.
"""

from __future__ import annotations

# ── articles ──────────────────────────────────────────────────────────────────
from lawgraph.api.queries.articles import ArticleCitationEntry as ArticleCitationEntry
from lawgraph.api.queries.articles import ArticleDetailData as ArticleDetailData
from lawgraph.api.queries.articles import get_article_citations as get_article_citations
from lawgraph.api.queries.articles import get_article_in_flux as get_article_in_flux
from lawgraph.api.queries.articles import (
    get_article_legislative_history as get_article_legislative_history,
)
from lawgraph.api.queries.articles import (
    get_article_with_relations as get_article_with_relations,
)

# ── commissies ────────────────────────────────────────────────────────────────
from lawgraph.api.queries.commissies import (
    get_actor_touched_instruments as get_actor_touched_instruments,
)
from lawgraph.api.queries.commissies import get_all_commissies as get_all_commissies
from lawgraph.api.queries.commissies import (
    get_all_commissies_with_leden as get_all_commissies_with_leden,
)
from lawgraph.api.queries.commissies import get_all_fracties as get_all_fracties
from lawgraph.api.queries.commissies import get_all_leden as get_all_leden
from lawgraph.api.queries.commissies import get_commissie_detail as get_commissie_detail
from lawgraph.api.queries.commissies import (
    get_lid_touched_instruments as get_lid_touched_instruments,
)
from lawgraph.api.queries.commissies import get_lid_votes as get_lid_votes

# ── dossiers ──────────────────────────────────────────────────────────────────
from lawgraph.api.queries.dossiers import DOSSIER_STAGES as DOSSIER_STAGES
from lawgraph.api.queries.dossiers import DOSSIER_TRAJECT_KINDS as DOSSIER_TRAJECT_KINDS
from lawgraph.api.queries.dossiers import DossierEnrichment as DossierEnrichment
from lawgraph.api.queries.dossiers import classify_doc_soort as classify_doc_soort
from lawgraph.api.queries.dossiers import classify_traject_kind as classify_traject_kind
from lawgraph.api.queries.dossiers import classify_zaak_soort as classify_zaak_soort
from lawgraph.api.queries.dossiers import count_dossier_members as count_dossier_members
from lawgraph.api.queries.dossiers import enrich_dossier_docs as enrich_dossier_docs
from lawgraph.api.queries.dossiers import (
    get_documents_for_dossiers as get_documents_for_dossiers,
)
from lawgraph.api.queries.dossiers import get_dossier_by_nummer as get_dossier_by_nummer
from lawgraph.api.queries.dossiers import get_dossier_documents as get_dossier_documents
from lawgraph.api.queries.dossiers import get_dossier_mutations as get_dossier_mutations
from lawgraph.api.queries.dossiers import get_dossier_timeline as get_dossier_timeline
from lawgraph.api.queries.dossiers import get_open_dossiers as get_open_dossiers
from lawgraph.api.queries.dossiers import get_recent_dossiers as get_recent_dossiers

# ── graph ─────────────────────────────────────────────────────────────────────
from lawgraph.api.queries.graph import GlobalGraphData as GlobalGraphData
from lawgraph.api.queries.graph import GraphEdge as GraphEdge
from lawgraph.api.queries.graph import InstrumentLayerData as InstrumentLayerData
from lawgraph.api.queries.graph import JudgmentGraphData as JudgmentGraphData
from lawgraph.api.queries.graph import get_global_graph as get_global_graph
from lawgraph.api.queries.graph import (
    get_instrument_layer_graph as get_instrument_layer_graph,
)
from lawgraph.api.queries.graph import get_judgment_graph as get_judgment_graph

# ── instruments ───────────────────────────────────────────────────────────────
from lawgraph.api.queries.instruments import INSTRUMENT_SORTS as INSTRUMENT_SORTS
from lawgraph.api.queries.instruments import InstrumentStats as InstrumentStats
from lawgraph.api.queries.instruments import (
    get_instrument_article_history as get_instrument_article_history,
)
from lawgraph.api.queries.instruments import (
    get_instrument_articles as get_instrument_articles,
)
from lawgraph.api.queries.instruments import (
    get_instrument_articles_at as get_instrument_articles_at,
)
from lawgraph.api.queries.instruments import (
    get_instrument_dossiers as get_instrument_dossiers,
)
from lawgraph.api.queries.instruments import (
    get_instrument_edges_bundle as get_instrument_edges_bundle,
)
from lawgraph.api.queries.instruments import (
    get_instrument_judgments as get_instrument_judgments,
)
from lawgraph.api.queries.instruments import (
    get_instrument_related_instruments as get_instrument_related_instruments,
)
from lawgraph.api.queries.instruments import (
    get_instrument_versions as get_instrument_versions,
)
from lawgraph.api.queries.instruments import (
    get_instruments_list as get_instruments_list,
)

# ── judgments ─────────────────────────────────────────────────────────────────
from lawgraph.api.queries.judgments import JUDGMENT_SORTS as JUDGMENT_SORTS
from lawgraph.api.queries.judgments import (
    JudgmentArticleRelation as JudgmentArticleRelation,
)
from lawgraph.api.queries.judgments import JudgmentDetailData as JudgmentDetailData
from lawgraph.api.queries.judgments import derive_judgment_tier as derive_judgment_tier
from lawgraph.api.queries.judgments import (
    get_judgment_with_relations as get_judgment_with_relations,
)
from lawgraph.api.queries.judgments import get_judgments_list as get_judgments_list

# ── nodes ─────────────────────────────────────────────────────────────────────
from lawgraph.api.queries.nodes import NeighborEntry as NeighborEntry
from lawgraph.api.queries.nodes import NodeGraphData as NodeGraphData
from lawgraph.api.queries.nodes import get_node_neighborhood as get_node_neighborhood
from lawgraph.api.queries.nodes import (
    get_node_with_neighbors as get_node_with_neighbors,
)

# ── overlay ───────────────────────────────────────────────────────────────────
from lawgraph.api.queries.overlay import get_heat_counts as get_heat_counts
from lawgraph.api.queries.overlay import get_in_flux_counts as get_in_flux_counts

# ── search ────────────────────────────────────────────────────────────────────
from lawgraph.api.queries.search import build_search_clause as build_search_clause
from lawgraph.api.queries.search import (
    load_instrument_alias_map as load_instrument_alias_map,
)
from lawgraph.api.queries.search import parse_search_query as parse_search_query
from lawgraph.api.queries.search import search_all as search_all
from lawgraph.api.queries.search import tokenize_search_query as tokenize_search_query

# ── stats ─────────────────────────────────────────────────────────────────────
from lawgraph.api.queries.stats import get_db_stats as get_db_stats
from lawgraph.api.queries.stats import get_edge_status_log as get_edge_status_log

# ── stemmingen ────────────────────────────────────────────────────────────────
from lawgraph.api.queries.stemmingen import get_stemming_detail as get_stemming_detail
from lawgraph.api.queries.stemmingen import (
    get_stemming_publication as get_stemming_publication,
)
from lawgraph.api.queries.stemmingen import get_stemmingen as get_stemmingen

# ── watches ───────────────────────────────────────────────────────────────────
from lawgraph.api.queries.watches import create_watch as create_watch
from lawgraph.api.queries.watches import delete_watch as delete_watch
from lawgraph.api.queries.watches import list_watches as list_watches
