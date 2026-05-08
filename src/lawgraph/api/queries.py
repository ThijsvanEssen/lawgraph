"""Read-only query helpers used by the FastAPI layer."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from lawgraph.config.settings import (
    COLLECTION_EDGE_STATUS_LOG,
    COLLECTION_EDGES,
    COLLECTION_JUDGMENTS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_DEEL_VAN_DOSSIER,
    RELATION_MENTIONS_ARTICLE,
    RELATION_PART_OF_INSTRUMENT,
    RELATION_REFERS_TO_ARTICLE,
)
from lawgraph.db import ArangoStore
from lawgraph.models import make_node_key

_ALLOWED_NODE_COLLECTIONS = {
    "instruments",
    "instrument_articles",
    "judgments",
    "procedures",
    "publications",
    "topics",
    "kamerstukdossiers",
    "activiteiten",
    "stemmingen",
    "toezeggingen",
    "commissies",
    "leden",
}


# ── Shared dataclasses ─────────────────────────────────────────────────────────


@dataclass
class InstrumentStats:
    """Aggregate statistics for a single instrument (law/regulation)."""

    article_count: int = 0
    judgment_count: int = 0
    inbound_citation_count: int = 0
    outbound_citation_count: int = 0


@dataclass
class ArticleDetailData:
    article: dict[str, Any]
    instrument: dict[str, Any] | None
    judgments: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class JudgmentArticleRelation:
    article: dict[str, Any]
    instrument: dict[str, Any] | None


@dataclass
class JudgmentDetailData:
    judgment: dict[str, Any]
    articles: list[JudgmentArticleRelation]
    cited_judgments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NeighborEntry:
    doc: dict[str, Any]
    relation: str | None
    direction: Literal["outbound", "inbound"]
    confidence: float | None


@dataclass
class NodeGraphData:
    node: dict[str, Any]
    neighbors: list[NeighborEntry]


@dataclass
class ArticleCitationEntry:
    target: dict[str, Any]
    start: int | None
    end: int | None
    text: str | None
    confidence: float | None


# ── Existing query helpers ─────────────────────────────────────────────────────


def get_article_with_relations(
    store: ArangoStore,
    bwb_id: str,
    article_number: str,
) -> ArticleDetailData:
    """Fetch an article along with its parent instrument and mentioning judgments."""
    article_key = make_node_key(bwb_id, article_number)
    article_doc = store.instrument_articles.get(article_key)
    article_doc = _ensure_doc(article_doc)
    if article_doc is None:
        raise ValueError("article not found")

    article_id = article_doc["_id"]
    instrument_doc = _find_instrument_for_article(store, article_id)
    judgments = _find_judgments_for_article(store, article_id)

    metadata = {"judgment_count": len(judgments)}
    return ArticleDetailData(
        article=article_doc,
        instrument=instrument_doc,
        judgments=judgments,
        metadata=metadata,
    )


def get_article_citations(
    store: ArangoStore,
    article_doc: dict[str, Any],
) -> list[ArticleCitationEntry]:
    doc = _ensure_doc(article_doc)
    if not doc:
        return []
    article_id = doc.get("_id")
    if not article_id:
        return []

    citations: list[ArticleCitationEntry] = []
    seen: set[tuple[str, int | None, int | None, str | None]] = set()

    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._from == @article_id
        FILTER edge.relation == @relation
        RETURN edge
    """
    for edge in store.query(
        aql, {"article_id": article_id, "relation": RELATION_REFERS_TO_ARTICLE}
    ):
        target_doc = _load_document_by_ref(store, edge.get("_to"))
        if not target_doc:
            continue
        start, end, text = _extract_span(edge)
        confidence = _extract_confidence(edge)
        _record_article_citation(
            citations, seen, target_doc, start, end, text, confidence
        )

    props = doc.get("props") or {}
    raw_citations = props.get("citations")
    if isinstance(raw_citations, list):
        for entry in raw_citations:
            if not isinstance(entry, dict):
                continue
            target_doc = _resolve_target_from_entry(store, entry)
            if not target_doc:
                continue
            start = _coerce_int(entry.get("start"))
            end = _coerce_int(entry.get("end"))
            text = _coerce_text(entry.get("text"))
            confidence = _coerce_float(entry.get("confidence"))
            _record_article_citation(
                citations, seen, target_doc, start, end, text, confidence
            )

    return citations


def get_judgment_with_relations(store: ArangoStore, ecli: str) -> JudgmentDetailData:
    """Fetch a judgment and related articles via edges."""
    judgment_doc = _load_judgment(store, ecli)
    if judgment_doc is None:
        raise ValueError("judgment not found")

    article_relations: list[JudgmentArticleRelation] = []
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._from == @jid
        FILTER edge.relation == @relation
        RETURN edge
    """
    for edge in store.query(
        aql, {"jid": judgment_doc["_id"], "relation": RELATION_MENTIONS_ARTICLE}
    ):
        article_doc = _load_document_by_ref(store, edge.get("_to"))
        if not article_doc:
            continue
        instrument_doc = _find_instrument_for_article(store, article_doc["_id"])
        article_relations.append(
            JudgmentArticleRelation(article=article_doc, instrument=instrument_doc)
        )

    metadata = {"article_count": len(article_relations)}
    return JudgmentDetailData(
        judgment=judgment_doc, articles=article_relations, metadata=metadata
    )


def get_node_with_neighbors(
    store: ArangoStore,
    collection: str,
    key: str,
) -> NodeGraphData:
    """Retrieve a node together with its unified-edge neighbors."""
    if collection not in _ALLOWED_NODE_COLLECTIONS:
        raise ValueError("unsupported collection")
    if not store.db.has_collection(collection):
        raise ValueError(f"collection {collection} not found")

    coll = store.db.collection(collection)
    raw_node = coll.get(key)
    if raw_node is None:
        raise ValueError("node not found")
    node_doc = _ensure_doc(raw_node)
    if node_doc is None:
        raise ValueError("node not found")

    neighbors = _collect_neighbors(store, node_doc["_id"])
    return NodeGraphData(node=node_doc, neighbors=neighbors)


# ── Parliamentary dossier query helpers ────────────────────────────────────────


def get_dossier_by_nummer(
    store: ArangoStore, kamerstuknummer: str
) -> dict[str, Any] | None:
    """Fetch a Kamerstukdossier by its kamerstuknummer (e.g. '36558')."""
    aql = """
    FOR doc IN kamerstukdossiers
        FILTER doc.props.kamerstuknummer == @nummer
        LIMIT 1
        RETURN doc
    """
    for doc in store.query(aql, {"nummer": kamerstuknummer}):
        return doc
    return None


def get_dossier_timeline(
    store: ArangoStore,
    dossier_id: str,
    *,
    order: Literal["desc", "asc"] = "desc",
    soort_filter: list[str] | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> list[dict[str, Any]]:
    """Return ordered timeline entries (pubs, activiteiten, stemmingen, toezeggingen) for a dossier.

    Each entry has shape: {datum, soort, titel, body, _cursor_key}.
    """
    sort_dir = "DESC" if order == "desc" else "ASC"

    soort_clause = ""
    bind_vars: dict[str, Any] = {"dossier_id": dossier_id, "limit": limit}
    if soort_filter:
        soort_clause = "FILTER LOWER(item.soort) IN @soort_filter"
        bind_vars["soort_filter"] = [s.lower() for s in soort_filter]

    cursor_clause = ""
    if cursor:
        op = "<" if order == "desc" else ">"
        cursor_clause = f"FILTER item.datum {op} @cursor"
        bind_vars["cursor"] = cursor

    aql = f"""
    LET docs = (
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._to == @dossier_id OR edge._from == @dossier_id
            FILTER edge.relation == "{RELATION_DEEL_VAN_DOSSIER}"
            LET node_id = (edge._to == @dossier_id ? edge._from : edge._to)
            LET col = SPLIT(node_id, '/')[0]
            FILTER col IN ['publications', 'activiteiten', 'stemmingen', 'toezeggingen']
            LET doc = DOCUMENT(node_id)
            FILTER doc != null
            RETURN doc
    )
    FOR item IN docs
        LET soort = (item.props.soort != null ? item.props.soort :
                     item.type == 'activiteit' ? 'Activiteit' :
                     item.type == 'stemming' ? 'Stemming' :
                     item.type == 'toezegging' ? 'Toezegging' : 'Document')
        LET datum = (item.props.datum != null ? item.props.datum :
                     item.props.gedaan_op != null ? item.props.gedaan_op : null)
        FILTER datum != null
        {soort_clause}
        {cursor_clause}
        SORT datum {sort_dir}
        LIMIT @limit
        RETURN {{
            datum: datum,
            soort: soort,
            titel: item.props.display_name,
            body: item.props,
            node_id: item._id,
            node_type: item.type
        }}
    """
    return list(store.query(aql, bind_vars))


def get_dossier_documents(
    store: ArangoStore,
    dossier_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return publications (Kamerstuk documents) linked to this dossier.

    Looks for publications connected via DEEL_VAN_DOSSIER edges, either directly
    or indirectly via the procedure chain (publication → procedure → dossier).
    Returns a paginated list sorted by datum descending.
    """
    aql = f"""
    LET direct = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @dossier_id AND e.relation == '{RELATION_DEEL_VAN_DOSSIER}'
            LET node = DOCUMENT(e._from)
            FILTER node != null AND SPLIT(e._from, '/')[0] == 'publications'
            RETURN node
    )
    LET via_procedure = (
        FOR e1 IN {COLLECTION_EDGES}
            FILTER e1._to == @dossier_id AND e1.relation == '{RELATION_DEEL_VAN_DOSSIER}'
            FILTER SPLIT(e1._from, '/')[0] == 'procedures'
            FOR e2 IN {COLLECTION_EDGES}
                FILTER e2._to == e1._from AND e2.relation == 'PART_OF_PROCEDURE'
                LET pub = DOCUMENT(e2._from)
                FILTER pub != null AND SPLIT(e2._from, '/')[0] == 'publications'
                RETURN pub
    )
    LET all_docs = UNIQUE(APPEND(direct, via_procedure))
    LET total = LENGTH(all_docs)
    LET items = (
        FOR doc IN all_docs
            SORT doc.props.datum DESC
            LIMIT @offset, @limit
            RETURN {{
                id: doc._id,
                key: doc._key,
                soort: doc.props.soort,
                titel: (doc.props.title != null ? doc.props.title : doc.props.display_name),
                datum: doc.props.datum,
                display_name: doc.props.display_name
            }}
    )
    RETURN {{ total: total, items: items }}
    """  # noqa: E501
    rows = list(
        store.query(aql, {"dossier_id": dossier_id, "limit": limit, "offset": offset})
    )
    if not rows:
        return {"total": 0, "items": []}
    return rows[0]


def get_dossier_mutations(store: ArangoStore, dossier_id: str) -> dict[str, Any]:
    """Return the pending-mutation subgraph for this dossier.

    'Mutations' are edges with status='voorgesteld' that originated from
    documents that are DEEL_VAN_DOSSIER this dossier.  Returns nodes + edges
    in the same shape as the existing graph endpoint.
    """
    aql = f"""
    LET member_ids = (
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._to == @dossier_id OR edge._from == @dossier_id
            FILTER edge.relation == "{RELATION_DEEL_VAN_DOSSIER}"
            RETURN (edge._to == @dossier_id ? edge._from : edge._to)
    )
    FOR e IN {COLLECTION_EDGES}
        FILTER e._from IN member_ids OR e._to IN member_ids
        FILTER e.status == "{EDGE_STATUS_VOORGESTELD}"
        LET from_node = DOCUMENT(e._from)
        LET to_node = DOCUMENT(e._to)
        RETURN {{
            edge: e,
            from_node: from_node,
            to_node: to_node
        }}
    """
    rows = list(store.query(aql, {"dossier_id": dossier_id}))
    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges_out: list[dict[str, Any]] = []
    for row in rows:
        e = row.get("edge") or {}
        fn = row.get("from_node")
        tn = row.get("to_node")
        if fn:
            nodes_by_id[fn["_id"]] = fn
        if tn:
            nodes_by_id[tn["_id"]] = tn
        edges_out.append(
            {
                "from_id": e.get("_from"),
                "to_id": e.get("_to"),
                "relation": e.get("relation"),
                "status": e.get("status"),
                "meta": e.get("meta"),
            }
        )
    return {"nodes": list(nodes_by_id.values()), "edges": edges_out}


def get_open_dossiers(
    store: ArangoStore,
    *,
    commissie_slug: str | None = None,
    onderwerp: str | None = None,
    fase: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return all open (non-afgedaan) dossiers with optional filters."""
    filters = [
        "doc.props.afgedaan == false OR doc.props.afgedaan == null",
        "doc.props.gesloten_op == null",
    ]
    bind_vars: dict[str, Any] = {"limit": limit}

    if fase:
        filters.append("doc.props.huidige_fase == @fase")
        bind_vars["fase"] = fase
    if onderwerp:
        filters.append("CONTAINS(LOWER(doc.props.titel), LOWER(@onderwerp))")
        bind_vars["onderwerp"] = onderwerp

    filter_clause = "\n        ".join(f"FILTER {f}" for f in filters)

    # commissie filter: dossiers that have an activiteit BEHANDELD_DOOR that commissie
    commissie_join = ""
    if commissie_slug:
        bind_vars["commissie_slug"] = commissie_slug
        commissie_join = f"""
        LET commissie_match = FIRST(
            FOR c IN commissies FILTER c.props.slug == @commissie_slug LIMIT 1 RETURN c
        )
        FILTER commissie_match != null
        FILTER LENGTH(
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == commissie_match._id AND e.relation == 'BEHANDELD_DOOR'
                FOR e2 IN {COLLECTION_EDGES}
                    FILTER e2._from == e._from AND e2._to == doc._id
                    AND e2.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                    RETURN 1
        ) > 0
        """

    aql = f"""
    FOR doc IN kamerstukdossiers
        {filter_clause}
        {commissie_join}
        SORT doc.props.geopend_op DESC
        LIMIT @limit
        RETURN doc
    """
    return list(store.query(aql, bind_vars))


def get_recent_dossiers(
    store: ArangoStore, *, days: int = 30, limit: int = 50
) -> list[dict[str, Any]]:
    """Return dossiers that had activity in the last N days."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime(
        "%Y-%m-%d"
    )
    aql = f"""
    LET recent = (
        FOR doc IN activiteiten
            FILTER doc.props.datum >= @cutoff
            FOR edge IN {COLLECTION_EDGES}
                FILTER edge._from == doc._id AND edge.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                LET dossier = DOCUMENT(edge._to)
                FILTER dossier != null AND SPLIT(edge._to, '/')[0] == 'kamerstukdossiers'
                RETURN DISTINCT dossier
    )
    FOR d IN recent
        LIMIT @limit
        RETURN d
    """
    return list(store.query(aql, {"cutoff": cutoff, "limit": limit}))


def get_article_legislative_history(
    store: ArangoStore,
    bwb_id: str,
    article_number: str,
) -> list[dict[str, Any]]:
    """Return dossiers/documents that introduced, amended, or propose to amend an article.

    Each entry: {dossier_id, dossier_titel, datum, soort, status, samenvatting}.
    """
    article_key = make_node_key(bwb_id, article_number)
    article_id = f"instrument_articles/{article_key}"

    # Edges pointing TO this article from publications (wijzigt/introduceert/trekt_in)
    # plus edges from the unified collection
    mutation_relations = [
        "WIJZIGT",
        "INTRODUCEERT",
        "TREKT_IN",
        "LICHT_TOE",
        "MENTIONS_ARTICLE",
    ]
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._to == @article_id
        FILTER edge.relation IN @relations
        LET doc = DOCUMENT(edge._from)
        FILTER doc != null
        LET col = SPLIT(edge._from, '/')[0]
        LET dossier = FIRST(
            FOR e2 IN {COLLECTION_EDGES}
                FILTER e2._from == edge._from AND e2.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                LET d = DOCUMENT(e2._to)
                FILTER d != null AND SPLIT(e2._to, '/')[0] == 'kamerstukdossiers'
                LIMIT 1 RETURN d
        )
        SORT edge.status == '{EDGE_STATUS_VOORGESTELD}' ? 0 : 1, doc.props.datum DESC
        RETURN {{
            dossier_id: (dossier != null ? dossier._id : null),
            dossier_nummer: (dossier != null ? dossier.props.kamerstuknummer : null),
            dossier_titel: (dossier != null ? dossier.props.titel : null),
            datum: doc.props.datum,
            soort: doc.props.soort,
            status: edge.status,
            samenvatting: doc.props.display_name,
            document_id: doc._id
        }}
    """
    return list(
        store.query(
            aql,
            {
                "article_id": article_id,
                "relations": mutation_relations,
            },
        )
    )


def get_article_in_flux(
    store: ArangoStore, bwb_id: str, article_number: str
) -> dict[str, Any]:
    """Return in-flux status for an article: boolean + count of open dossiers targeting it."""
    article_key = make_node_key(bwb_id, article_number)
    article_id = f"instrument_articles/{article_key}"

    aql = f"""
    LET voorgesteld_count = LENGTH(
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._to == @article_id
            FILTER edge.status == '{EDGE_STATUS_VOORGESTELD}'
            RETURN 1
    )
    RETURN {{ in_flux: voorgesteld_count > 0, open_dossier_count: voorgesteld_count }}
    """
    rows = list(store.query(aql, {"article_id": article_id}))
    if rows:
        return rows[0]
    return {"in_flux": False, "open_dossier_count": 0}


def get_commissie_by_slug(store: ArangoStore, slug: str) -> dict[str, Any] | None:
    aql = """
    FOR doc IN commissies
        FILTER doc.props.slug == @slug
        LIMIT 1
        RETURN doc
    """
    for doc in store.query(aql, {"slug": slug}):
        return doc
    return None


def get_commissie_detail(store: ArangoStore, slug: str) -> dict[str, Any] | None:
    """Return commissie with leden (via LID_VAN edges) and recent dossiers (via BEHANDELD_DOOR)."""
    aql = f"""
    FOR commissie IN commissies
        FILTER commissie.props.slug == @slug
        LIMIT 1

        LET leden = (
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == commissie._id AND e.relation == 'LID_VAN'
                LET lid = DOCUMENT(e._from)
                FILTER lid != null
                SORT lid.props.naam ASC
                RETURN lid
        )

        LET dossiers = (
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == commissie._id AND e.relation == 'BEHANDELD_DOOR'
                FOR e2 IN {COLLECTION_EDGES}
                    FILTER e2._from == e._from AND e2.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                    LET dossier = DOCUMENT(e2._to)
                    FILTER dossier != null AND SPLIT(dossier._id, "/")[0] == "kamerstukdossiers"
                    RETURN DISTINCT dossier
        )

        RETURN MERGE(commissie, {{ leden: leden, dossiers: dossiers }})
    """
    for doc in store.query(aql, {"slug": slug}):
        return doc
    return None


def get_all_commissies(store: ArangoStore) -> list[dict[str, Any]]:
    aql = f"""
    FOR doc IN commissies
        LET naam = doc.props.naam
        FILTER naam != null AND naam != ""
        FILTER NOT REGEX_TEST(naam, "^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$", true)
        LET active_dossier_count = LENGTH(
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == doc._id AND e.relation == 'BEHANDELD_DOOR'
                FOR e2 IN {COLLECTION_EDGES}
                    FILTER e2._from == e._from AND e2.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                    LET d = DOCUMENT(e2._to)
                    FILTER d != null AND d.props.afgedaan == false
                    RETURN 1
        )
        SORT doc.props.naam ASC
        RETURN MERGE(doc, {{ active_dossier_count: active_dossier_count }})
    """
    return list(store.query(aql))


def get_lid_votes(
    store: ArangoStore, lid_id: str, *, limit: int = 100
) -> list[dict[str, Any]]:
    """Return a paginated voting record for a parliamentary member.

    Matches by partij (party label) stored on the Lid node. Returns stemmingen
    where the member's party appears in voor, tegen, or onthouding, together
    with the soort (Voor/Tegen/Onthouden) and the number of seats.
    """
    aql = """
    LET lid = DOCUMENT(@lid_id)
    LET partij = lid != null ? lid.props.partij : null
    FILTER partij != null AND partij != ""

    FOR stemming IN stemmingen
        LET voor_match = FIRST(
            FOR v IN (stemming.props.voor != null ? stemming.props.voor : [])
                FILTER v.partij == partij
                RETURN v
        )
        LET tegen_match = FIRST(
            FOR v IN (stemming.props.tegen != null ? stemming.props.tegen : [])
                FILTER v.partij == partij
                RETURN v
        )
        LET onthouding_match = FIRST(
            FOR v IN (stemming.props.onthouding != null ? stemming.props.onthouding : [])
                FILTER v.partij == partij
                RETURN v
        )
        LET match = voor_match != null ? voor_match
                  : tegen_match != null ? tegen_match
                  : onthouding_match
        FILTER match != null

        LET soort = voor_match != null ? "Voor"
                  : tegen_match != null ? "Tegen"
                  : "Onthouden"

        SORT stemming.props.datum DESC
        LIMIT @limit
        RETURN {
            stemming_id:  stemming._id,
            besluit_id:   stemming.props.besluit_id,
            datum:        stemming.props.datum,
            onderwerp:    stemming.props.onderwerp,
            aangenomen:   stemming.props.aangenomen,
            soort:        soort,
            aantal_zetels: match.aantal_zetels
        }
    """
    return list(store.query(aql, {"lid_id": lid_id, "limit": limit}))


def get_db_stats(store: ArangoStore) -> dict[str, Any]:
    """Return document counts per collection and edge counts per relation type."""
    node_collections = [
        "instruments",
        "instrument_articles",
        "judgments",
        "publications",
        "procedures",
        "topics",
        "kamerstukdossiers",
        "activiteiten",
        "stemmingen",
        "toezeggingen",
        "commissies",
        "leden",
    ]
    nodes: dict[str, int] = {}
    for name in node_collections:
        if store.db.has_collection(name):
            nodes[name] = store.db.collection(name).count()
        else:
            nodes[name] = 0

    edges_total = store.edges.count() if store.db.has_collection("edges") else 0

    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        COLLECT relation = edge.relation WITH COUNT INTO n
        RETURN {{ relation: relation, count: n }}
    """
    by_relation: dict[str, int] = {}
    for row in store.query(aql):
        key = row.get("relation") or "unknown"
        by_relation[key] = row.get("count", 0)

    return {
        "nodes": nodes,
        "edges": {"total": edges_total, "by_relation": by_relation},
    }


def get_edge_status_log(
    store: ArangoStore, *, limit: int = 200
) -> list[dict[str, Any]]:
    """Return recent edge-status flip audit entries, newest first."""
    aql = f"""
    FOR entry IN {COLLECTION_EDGE_STATUS_LOG}
        SORT entry.timestamp DESC
        LIMIT @limit
        RETURN entry
    """
    return list(store.query(aql, {"limit": limit}))


def search_all(
    store: ArangoStore,
    *,
    q: str,
    types: list[str],
    soort: list[str] | None = None,
    limit: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """Full-text search across requested entity types.

    Returns a dict keyed by type name with a list of hit dicts each containing
    {id, key, collection, type, display_name, snippet, extra}.

    Uses simple CONTAINS/LIKE matching — no dedicated search index required.
    """
    results: dict[str, list[dict[str, Any]]] = {}
    term = q.strip().lower()
    if not term:
        return {t: [] for t in types}

    if "articles" in types:
        aql = """
        FOR doc IN instrument_articles
            FILTER
                CONTAINS(LOWER(doc.props.display_name), @term)
                OR CONTAINS(LOWER(doc.props.text), @term)
                OR CONTAINS(LOWER(doc.props.article_number), @term)
                OR CONTAINS(LOWER(doc.props.bwb_id), @term)
            SORT doc.props.display_name ASC
            LIMIT @limit
            RETURN {
                id: doc._id,
                key: doc._key,
                collection: 'instrument_articles',
                type: doc.type,
                display_name: doc.props.display_name,
                snippet: LEFT(doc.props.text, 200),
                extra: {
                    bwb_id: doc.props.bwb_id,
                    article_number: doc.props.article_number
                }
            }
        """
        results["articles"] = list(store.query(aql, {"term": term, "limit": limit}))

    if "judgments" in types:
        aql = """
        FOR doc IN judgments
            FILTER
                CONTAINS(LOWER(doc.props.display_name), @term)
                OR CONTAINS(LOWER(doc.props.ecli), @term)
                OR CONTAINS(LOWER(doc.props.summary), @term)
            SORT doc.props.display_name ASC
            LIMIT @limit
            RETURN {
                id: doc._id,
                key: doc._key,
                collection: 'judgments',
                type: doc.type,
                display_name: doc.props.display_name,
                snippet: LEFT(doc.props.summary, 200),
                extra: { ecli: doc.props.ecli }
            }
        """
        results["judgments"] = list(store.query(aql, {"term": term, "limit": limit}))

    if "dossiers" in types:
        soort_clause = ""
        bind_vars: dict[str, Any] = {"term": term, "limit": limit}
        if soort:
            soort_clause = "FILTER LOWER(doc.props.huidige_fase) IN @soort_filter"
            bind_vars["soort_filter"] = [s.lower() for s in soort]

        aql = f"""
        FOR doc IN kamerstukdossiers
            FILTER
                CONTAINS(LOWER(doc.props.titel), @term)
                OR CONTAINS(LOWER(doc.props.kamerstuknummer), @term)
                OR CONTAINS(LOWER(doc.props.display_name), @term)
            {soort_clause}
            SORT doc.props.geopend_op DESC
            LIMIT @limit
            RETURN {{
                id: doc._id,
                key: doc._key,
                collection: 'kamerstukdossiers',
                type: doc.type,
                display_name: (doc.props.titel != null ? doc.props.titel : doc.props.display_name),
                snippet: doc.props.kamerstuknummer,
                extra: {{
                    kamerstuknummer: doc.props.kamerstuknummer,
                    huidige_fase: doc.props.huidige_fase,
                    afgedaan: doc.props.afgedaan
                }}
            }}
        """
        results["dossiers"] = list(store.query(aql, bind_vars))

    if "commissies" in types:
        aql = """
        FOR doc IN commissies
            FILTER
                CONTAINS(LOWER(doc.props.naam), @term)
                OR CONTAINS(LOWER(doc.props.afkorting), @term)
            SORT doc.props.naam ASC
            LIMIT @limit
            RETURN {
                id: doc._id,
                key: doc._key,
                collection: 'commissies',
                type: doc.type,
                display_name: doc.props.naam,
                snippet: doc.props.afkorting,
                extra: { slug: doc.props.slug, afkorting: doc.props.afkorting }
            }
        """
        results["commissies"] = list(store.query(aql, {"term": term, "limit": limit}))

    if "publications" in types:
        soort_clause = ""
        bind_vars_pub: dict[str, Any] = {"term": term, "limit": limit}
        if soort:
            soort_clause = "FILTER LOWER(doc.props.soort) IN @soort_filter"
            bind_vars_pub["soort_filter"] = [s.lower() for s in soort]

        aql = f"""
        FOR doc IN publications
            FILTER
                CONTAINS(LOWER(doc.props.display_name), @term)
                OR CONTAINS(LOWER(doc.props.title), @term)
                OR CONTAINS(LOWER(doc.props.external_id), @term)
            {soort_clause}
            SORT doc.props.display_name ASC
            LIMIT @limit
            RETURN {{
                id: doc._id,
                key: doc._key,
                collection: 'publications',
                type: doc.type,
                display_name: (doc.props.title != null ? doc.props.title : doc.props.display_name),
                snippet: doc.props.soort,
                extra: {{
                    soort: doc.props.soort,
                    external_id: doc.props.external_id
                }}
            }}
        """
        results["publications"] = list(store.query(aql, bind_vars_pub))

    return results


# ── Stemmingen browser queries ────────────────────────────────────────────────


def get_stemmingen(
    store: ArangoStore,
    *,
    aangenomen: bool | None = None,
    partij: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return a paginated list of stemmingen, newest first.

    Optional filters: aangenomen (bool), partij (party name match in voor/tegen/onthouding).
    """
    bind_vars: dict[str, Any] = {"limit": limit, "offset": offset}
    aangenomen_filter = ""
    if aangenomen is not None:
        aangenomen_filter = "FILTER doc.props.aangenomen == @aangenomen"
        bind_vars["aangenomen"] = aangenomen

    partij_filter = ""
    if partij:
        bind_vars["partij"] = partij.strip().lower()
        partij_filter = """
        FILTER LENGTH(
            FOR p IN APPEND(
                doc.props.voor != null ? doc.props.voor : [],
                APPEND(
                    doc.props.tegen != null ? doc.props.tegen : [],
                    doc.props.onthouding != null ? doc.props.onthouding : []
                )
            )
            FILTER CONTAINS(LOWER(p.partij), @partij)
            LIMIT 1
            RETURN 1
        ) > 0"""

    aql = f"""
    LET total = LENGTH(
        FOR doc IN stemmingen
            {aangenomen_filter}
            {partij_filter}
            RETURN 1
    )
    LET items = (
        FOR doc IN stemmingen
            {aangenomen_filter}
            {partij_filter}
            SORT doc.props.datum DESC
            LIMIT @offset, @limit
            RETURN {{
                id: doc._id,
                key: doc._key,
                datum: doc.props.datum,
                onderwerp: doc.props.onderwerp,
                aangenomen: doc.props.aangenomen,
                voor_count: LENGTH(doc.props.voor != null ? doc.props.voor : []),
                tegen_count: LENGTH(doc.props.tegen != null ? doc.props.tegen : []),
                onthouding_count: LENGTH(doc.props.onthouding != null ? doc.props.onthouding : [])
            }}
    )
    RETURN {{ total: total, items: items }}
    """  # noqa: E501
    rows = list(store.query(aql, bind_vars))
    if not rows:
        return {"total": 0, "items": []}
    return rows[0]


def get_stemming_detail(store: ArangoStore, key: str) -> dict[str, Any] | None:
    """Return a single stemming with full voor/tegen/onthouding breakdown."""
    aql = """
    LET doc = DOCUMENT(CONCAT('stemmingen/', @key))
    FILTER doc != null
    RETURN {
        id: doc._id,
        key: doc._key,
        datum: doc.props.datum,
        onderwerp: doc.props.onderwerp,
        aangenomen: doc.props.aangenomen,
        besluit_id: doc.props.besluit_id,
        voor: doc.props.voor,
        tegen: doc.props.tegen,
        onthouding: doc.props.onthouding
    }
    """
    for row in store.query(aql, {"key": key}):
        return row
    return None


# ── Bulk node overlay queries ──────────────────────────────────────────────────


def get_in_flux_counts(store: ArangoStore) -> dict[str, int]:
    """Return a map of node_id → count of VOORGESTELD edges targeting that node.

    Only nodes with at least one open mutation are included, so the frontend
    can efficiently decide which nodes to ring without iterating everything.
    """
    aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.status == '{EDGE_STATUS_VOORGESTELD}'
        COLLECT target = e._to WITH COUNT INTO cnt
        RETURN {{ id: target, count: cnt }}
    """
    return {row["id"]: row["count"] for row in store.query(aql)}


def get_heat_counts(store: ArangoStore, *, months: int = 6) -> dict[str, int]:
    """Return a map of node_id → activity count over the past *months* months.

    Activity is measured as the number of edges created within the time window
    pointing *to* each node (i.e. how often something referenced it recently).
    """
    cutoff = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * months)
    ).isoformat()
    aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.created_at >= @cutoff
        COLLECT target = e._to WITH COUNT INTO cnt
        RETURN {{ id: target, count: cnt }}
    """
    return {row["id"]: row["count"] for row in store.query(aql, {"cutoff": cutoff})}


# ── Watch helpers ──────────────────────────────────────────────────────────────


def list_watches(store: ArangoStore) -> list[dict[str, Any]]:
    """Return all watches, newest first."""
    aql = """
    FOR doc IN watches
        SORT doc.created_at DESC
        RETURN doc
    """
    return list(store.query(aql))


def create_watch(
    store: ArangoStore, *, node_id: str, label: str | None, collection: str | None
) -> dict[str, Any]:
    """Insert a new watch document and return it with its generated _key."""
    import uuid

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    doc = {
        "_key": str(uuid.uuid4()).replace("-", ""),
        "node_id": node_id,
        "label": label,
        "collection": collection,
        "created_at": now,
    }
    store.db.collection("watches").insert(doc)
    return doc


def delete_watch(store: ArangoStore, watch_id: str) -> bool:
    """Delete a watch by its _key. Returns True if found and deleted."""
    try:
        store.db.collection("watches").delete(watch_id)
        return True
    except Exception:
        return False


# ── Private helpers ────────────────────────────────────────────────────────────


def _find_instrument_for_article(
    store: ArangoStore, article_id: str
) -> dict[str, Any] | None:
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._from == @article_id AND edge.relation == @relation
        LIMIT 1
        RETURN DOCUMENT(edge._to)
    """
    for doc in store.query(
        aql, {"article_id": article_id, "relation": RELATION_PART_OF_INSTRUMENT}
    ):
        return doc
    return None


def _find_judgments_for_article(
    store: ArangoStore, article_id: str
) -> list[dict[str, Any]]:
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._to == @article_id AND edge.relation == @relation
        LET j = DOCUMENT(edge._from)
        FILTER j != null
        RETURN j
    """
    return list(
        store.query(
            aql, {"article_id": article_id, "relation": RELATION_MENTIONS_ARTICLE}
        )
    )


def _load_judgment(store: ArangoStore, ecli: str) -> dict[str, Any] | None:
    key = make_node_key(ecli)
    raw_doc = store.judgments.get(key)
    doc = _ensure_doc(raw_doc)
    if doc is not None:
        return doc
    aql = f"""
    FOR candidate IN {COLLECTION_JUDGMENTS}
        FILTER candidate.props.ecli == @ecli
        LIMIT 1
        RETURN candidate
    """
    for result in store.query(aql, {"ecli": ecli}):
        return result
    return None


def _collect_neighbors(store: ArangoStore, node_id: str) -> list[NeighborEntry]:
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._from == @node_id OR edge._to == @node_id
        LET neighbor_id = (edge._from == @node_id ? edge._to : edge._from)
        LET direction = (edge._from == @node_id ? 'outbound' : 'inbound')
        LET neighbor = DOCUMENT(neighbor_id)
        FILTER neighbor != null
        RETURN {{ edge: edge, neighbor: neighbor, direction: direction }}
    """
    neighbors: list[NeighborEntry] = []
    for row in store.query(aql, {"node_id": node_id}):
        neighbors.append(
            NeighborEntry(
                doc=row["neighbor"],
                relation=row["edge"].get("relation"),
                direction=row["direction"],
                confidence=_extract_confidence(row["edge"]),
            )
        )
    return neighbors


def _load_document_by_ref(store: ArangoStore, ref: str | None) -> dict[str, Any] | None:
    if not ref or "/" not in ref:
        return None
    collection_name, key = ref.split("/", 1)
    if not store.db.has_collection(collection_name):
        return None
    collection = store.db.collection(collection_name)
    raw_doc = collection.get(key)
    return _ensure_doc(raw_doc)


def _extract_span(edge: dict[str, Any]) -> tuple[int | None, int | None, str | None]:
    meta = edge.get("meta")
    if isinstance(meta, dict):
        return (
            _coerce_int(meta.get("start")),
            _coerce_int(meta.get("end")),
            _coerce_text(meta.get("text")),
        )
    return None, None, None


def _extract_confidence(edge: dict[str, Any]) -> float | None:
    raw = edge.get("confidence")
    if isinstance(raw, (int, float)):
        return float(raw)
    meta = edge.get("meta")
    if isinstance(meta, dict):
        conf = meta.get("confidence")
        if isinstance(conf, (int, float)):
            return float(conf)
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_text(value: Any) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed if trimmed else None
    return None


def _record_article_citation(
    citations: list[ArticleCitationEntry],
    seen: set[tuple[str, int | None, int | None, str | None]],
    target_doc: dict[str, Any],
    start: int | None,
    end: int | None,
    text: str | None,
    confidence: float | None,
) -> None:
    target_id = target_doc.get("_id")
    if not target_id:
        return
    key = (target_id, start, end, text)
    if key in seen:
        return
    seen.add(key)
    citations.append(
        ArticleCitationEntry(
            target=target_doc, start=start, end=end, text=text, confidence=confidence
        )
    )


def _resolve_target_from_entry(
    store: ArangoStore, entry: dict[str, Any]
) -> dict[str, Any] | None:
    bwb_id = entry.get("target_bwb_id")
    article_number = entry.get("target_article_number")
    if not bwb_id or not article_number:
        return None
    key = make_node_key(str(bwb_id), str(article_number))
    doc = store.instrument_articles.get(key)
    return _ensure_doc(doc)


def _ensure_doc(doc: Any) -> dict[str, Any] | None:
    if not doc:
        return None
    return cast(dict[str, Any], doc)


# ── Graph layer query results ─────────────────────────────────────────────────


@dataclass
class _GraphEdge:
    from_id: str
    to_id: str
    relation_type: str
    weight: float | None = None
    confidence: float | None = None
    start: int | None = None
    end: int | None = None
    text: str | None = None


@dataclass
class InstrumentLayerData:
    instruments: list[dict[str, Any]]
    edges: list[_GraphEdge]
    stats: dict[str, dict[str, Any]]
    metadata: dict[str, Any] | None = None


@dataclass
class JudgmentGraphData:
    judgments: list[dict[str, Any]]
    instruments: list[dict[str, Any]]
    edges: list[_GraphEdge]
    metadata: dict[str, Any] | None = None


@dataclass
class GlobalGraphData:
    instruments: list[dict[str, Any]]
    articles: list[dict[str, Any]]
    judgments: list[dict[str, Any]]
    edges: list[_GraphEdge]
    metadata: dict[str, Any] | None = None


def get_instrument_layer_graph(store: ArangoStore) -> InstrumentLayerData:
    """Return all non-stub instruments and aggregated inter-instrument citation edges."""
    instruments: list[dict[str, Any]] = list(
        store.query(
            """
        FOR inst IN instruments
            FILTER inst.props.stub != true OR inst.props.stub == null
            RETURN inst
    """
        )
    )

    bwb_to_id: dict[str, str] = {}
    for inst in instruments:
        bwb = (inst.get("props") or {}).get("bwb_id")
        if bwb:
            bwb_to_id[bwb] = inst["_id"]

    # Aggregate article-level citations into instrument-level weighted edges.
    # REFERS_TO_ARTICLE is the primary article→article cross-reference relation.
    rows: list[dict[str, Any]] = list(
        store.query(
            f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == "REFERS_TO_ARTICLE"
            LET fa = DOCUMENT(e._from)
            LET ta = DOCUMENT(e._to)
            FILTER fa != null AND ta != null
            FILTER fa.props.bwb_id != null AND ta.props.bwb_id != null
            FILTER fa.props.bwb_id != ta.props.bwb_id
            COLLECT fbwb = fa.props.bwb_id, tbwb = ta.props.bwb_id WITH COUNT INTO cnt
            FILTER cnt >= 2
            RETURN {{from_bwb: fbwb, to_bwb: tbwb, weight: cnt}}
    """
        )
    )

    graph_edges: list[_GraphEdge] = []
    for row in rows:
        fid = bwb_to_id.get(row["from_bwb"])
        tid = bwb_to_id.get(row["to_bwb"])
        if fid and tid:
            graph_edges.append(
                _GraphEdge(
                    from_id=fid,
                    to_id=tid,
                    relation_type="verwijst_naar",
                    weight=float(row["weight"]),
                )
            )

    # Direct instrument-to-instrument edges.
    direct: list[dict[str, Any]] = list(
        store.query(
            f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation IN ["IMPLEMENTS_DIRECTIVE", "AMENDS_INSTRUMENT", "MENTIONS_INSTRUMENT"]
            FILTER SPLIT(e._from, "/")[0] IN ["instruments", "instrument_articles"]
            FILTER SPLIT(e._to, "/")[0] == "instruments"
            RETURN {{from_id: e._from, to_id: e._to, relation_type: e.relation}}
    """
        )
    )
    for de in direct:
        graph_edges.append(
            _GraphEdge(
                from_id=de["from_id"],
                to_id=de["to_id"],
                relation_type=de["relation_type"],
            )
        )

    # Compute in-degree as citation_count per instrument.
    stats: dict[str, dict[str, Any]] = {
        inst["_id"]: {"citation_count": 0} for inst in instruments
    }
    for e in graph_edges:
        if e.to_id in stats:
            stats[e.to_id]["citation_count"] = stats[e.to_id][  # noqa: E501
                "citation_count"
            ] + (int(e.weight or 1))

    return InstrumentLayerData(instruments=instruments, edges=graph_edges, stats=stats)


def get_judgment_graph(
    store: ArangoStore,
    *,
    max_judgments: int = 1000,
    include_stubs: bool = False,
) -> JudgmentGraphData:
    """Return judgments, their cited instruments, and aggregated citation edges."""
    stub_filter = (
        "" if include_stubs else "FILTER j.props.stub != true OR j.props.stub == null"
    )
    judgments: list[dict[str, Any]] = list(
        store.query(
            f"""
        FOR j IN {COLLECTION_JUDGMENTS}
            {stub_filter}
            LIMIT @limit
            RETURN j
    """,
            {"limit": max_judgments},
        )
    )

    if not judgments:
        return JudgmentGraphData(judgments=[], instruments=[], edges=[])

    judgment_ids = {j["_id"] for j in judgments}

    # For each judgment, aggregate how many articles it cites per instrument.
    # CITES_ARTICLE is the judgment → article relation.
    rows = list(
        store.query(
            f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == "CITES_ARTICLE"
            FILTER SPLIT(e._from, "/")[0] == "judgments"
            FILTER SPLIT(e._to, "/")[0] == "instrument_articles"
            LET art = DOCUMENT(e._to)
            FILTER art != null AND art.props.bwb_id != null
            RETURN {{judgment_id: e._from, bwb_id: art.props.bwb_id}}
    """
        )
    )

    # Aggregate: (judgment_id, bwb_id) → count
    edge_weights: dict[tuple[str, str], int] = {}
    cited_bwb: set[str] = set()
    for row in rows:
        if row["judgment_id"] not in judgment_ids:
            continue
        key = (row["judgment_id"], row["bwb_id"])
        edge_weights[key] = edge_weights.get(key, 0) + 1
        cited_bwb.add(row["bwb_id"])

    instruments: list[dict[str, Any]] = []
    bwb_to_id: dict[str, str] = {}
    if cited_bwb:
        instruments = list(
            store.query(
                """
            FOR i IN instruments
                FILTER i.props.bwb_id IN @bwb_ids
                RETURN i
        """,
                {"bwb_ids": list(cited_bwb)},
            )
        )
        bwb_to_id = {
            (i.get("props") or {}).get("bwb_id"): i["_id"] for i in instruments
        }

    graph_edges: list[_GraphEdge] = []
    for (jid, bwb), weight in edge_weights.items():
        iid = bwb_to_id.get(bwb)
        if iid:
            graph_edges.append(
                _GraphEdge(
                    from_id=jid,
                    to_id=iid,
                    relation_type="citeert_wet",
                    weight=float(weight),
                )
            )

    return JudgmentGraphData(
        judgments=judgments, instruments=instruments, edges=graph_edges
    )


def get_global_graph(
    store: ArangoStore,
    *,
    include_judgments: bool = True,
    max_judgments: int = 500,
) -> GlobalGraphData:
    """Return a sample global graph: all instruments, stub articles, and optional judgments."""
    instruments: list[dict[str, Any]] = list(
        store.query(
            """
        FOR inst IN instruments
            FILTER inst.props.stub != true OR inst.props.stub == null
            RETURN inst
    """
        )
    )
    articles: list[dict[str, Any]] = list(
        store.query(
            """
        FOR art IN instrument_articles
            LIMIT 5000
            RETURN art
    """
        )
    )
    judgments: list[dict[str, Any]] = []
    if include_judgments:
        judgments = list(
            store.query(
                f"""
            FOR j IN {COLLECTION_JUDGMENTS}
                FILTER j.props.stub != true OR j.props.stub == null
                LIMIT @limit
                RETURN j
        """,
                {"limit": max_judgments},
            )
        )

    all_ids = (
        {inst["_id"] for inst in instruments}
        | {art["_id"] for art in articles}
        | {j["_id"] for j in judgments}
    )

    edges: list[dict[str, Any]] = list(
        store.query(
            f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation IN [
                "CITES_ARTICLE", "MENTIONS_ARTICLE", "EXPLAINS_ARTICLE",
                "PART_OF_INSTRUMENT", "IMPLEMENTS_DIRECTIVE", "AMENDS_INSTRUMENT"
            ]
            LIMIT 10000
            RETURN {{from_id: e._from, to_id: e._to, relation_type: e.relation, confidence: e.confidence}}
    """
        )
    )

    graph_edges = [
        _GraphEdge(
            from_id=e["from_id"],
            to_id=e["to_id"],
            relation_type=e["relation_type"],
            confidence=e.get("confidence"),
        )
        for e in edges
        if e["from_id"] in all_ids and e["to_id"] in all_ids
    ]

    return GlobalGraphData(
        instruments=instruments,
        articles=articles,
        judgments=judgments,
        edges=graph_edges,
    )
