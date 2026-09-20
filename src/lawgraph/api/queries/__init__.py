"""lawgraph.api.queries — the public names of the queries sub-package.

Routes import query helpers from here rather than from the individual
modules, so a helper can move between modules without touching its callers.
"""

from __future__ import annotations

# ── helpers ───────────────────────────────────────────────────────────────────
from lawgraph.api.queries._helpers import props as props

# ── annexes ───────────────────────────────────────────────────────────────────
from lawgraph.api.queries.annexes import get_annex as get_annex
from lawgraph.api.queries.annexes import (
    get_annex_referenced_by as get_annex_referenced_by,
)
from lawgraph.api.queries.annexes import (
    get_shared_annexes_for_law as get_shared_annexes_for_law,
)
from lawgraph.api.queries.annexes import list_annexes as list_annexes

# ── articles ──────────────────────────────────────────────────────────────────
from lawgraph.api.queries.articles import ArticleCitationEntry as ArticleCitationEntry
from lawgraph.api.queries.articles import ArticleDetailData as ArticleDetailData
from lawgraph.api.queries.articles import get_article_citations as get_article_citations
from lawgraph.api.queries.articles import get_article_history as get_article_history
from lawgraph.api.queries.articles import get_article_in_flux as get_article_in_flux
from lawgraph.api.queries.articles import (
    get_article_legislative_history as get_article_legislative_history,
)
from lawgraph.api.queries.articles import (
    get_article_with_relations as get_article_with_relations,
)

# ── committees, members, factions ─────────────────────────────────────────────
from lawgraph.api.queries.committees import (
    get_actor_touched_instruments as get_actor_touched_instruments,
)
from lawgraph.api.queries.committees import get_committee_detail as get_committee_detail
from lawgraph.api.queries.committees import get_committees as get_committees
from lawgraph.api.queries.committees import (
    get_committees_with_members as get_committees_with_members,
)
from lawgraph.api.queries.committees import get_factions as get_factions
from lawgraph.api.queries.committees import get_member_votes as get_member_votes
from lawgraph.api.queries.committees import get_members as get_members

# ── decisions ─────────────────────────────────────────────────────────────────
from lawgraph.api.queries.decisions import get_decision_detail as get_decision_detail
from lawgraph.api.queries.decisions import (
    get_decision_document as get_decision_document,
)
from lawgraph.api.queries.decisions import get_decisions as get_decisions

# ── dossiers ──────────────────────────────────────────────────────────────────
from lawgraph.api.queries.dossiers import DossierEnrichment as DossierEnrichment
from lawgraph.api.queries.dossiers import count_dossier_members as count_dossier_members
from lawgraph.api.queries.dossiers import enrich_dossier_docs as enrich_dossier_docs
from lawgraph.api.queries.dossiers import (
    get_documents_for_dossiers as get_documents_for_dossiers,
)
from lawgraph.api.queries.dossiers import get_dossier_by_number as get_dossier_by_number
from lawgraph.api.queries.dossiers import get_dossier_documents as get_dossier_documents
from lawgraph.api.queries.dossiers import get_dossier_mutations as get_dossier_mutations
from lawgraph.api.queries.dossiers import (
    get_dossier_number_to_id_map as get_dossier_number_to_id_map,
)
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
from lawgraph.api.queries.instruments import get_articles as get_articles
from lawgraph.api.queries.instruments import get_articles_at as get_articles_at
from lawgraph.api.queries.instruments import (
    get_instrument_amended_by as get_instrument_amended_by,
)
from lawgraph.api.queries.instruments import (
    get_instrument_article_history as get_instrument_article_history,
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

# ── relationships ─────────────────────────────────────────────────────────────
from lawgraph.api.queries.relationships import (
    get_article_relationship_data as get_article_relationship_data,
)
from lawgraph.api.queries.relationships import (
    get_cross_law_dependencies as get_cross_law_dependencies,
)
from lawgraph.api.queries.relationships import resolve_article_id as resolve_article_id
from lawgraph.api.queries.relationships import (
    search_relationships as search_relationships,
)
from lawgraph.api.queries.relationships import tag_relationship as tag_relationship
from lawgraph.api.queries.relationships import vote_relationship as vote_relationship

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

# ── watches ───────────────────────────────────────────────────────────────────
from lawgraph.api.queries.watches import create_watch as create_watch
from lawgraph.api.queries.watches import delete_watch as delete_watch
from lawgraph.api.queries.watches import list_watches as list_watches
