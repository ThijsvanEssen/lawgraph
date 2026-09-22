"""Article query helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lawgraph.api.queries._helpers import (
    _coerce_float,
    _coerce_int,
    _coerce_text,
    _ensure_doc,
    _extract_confidence,
    _extract_qualifier,
    _extract_span,
    _find_instrument_for_article,
    _find_judgments_for_article,
    _load_document_by_ref,
    _resolve_target_from_entry,
)
from lawgraph.api.queries.dossiers import collect_dossier_numbers, get_dossier_titles
from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_REPEALS,
)
from lawgraph.core.models import make_node_key
from lawgraph.core.qualifiers import Qualifier
from lawgraph.db import ArangoStore


@dataclass
class ArticleDetailData:
    article: dict[str, Any]
    instrument: dict[str, Any] | None
    judgments: list[dict[str, Any]]
    metadata: dict[str, Any]


@dataclass
class ArticleHistoryData:
    article: dict[str, Any]
    versions: list[dict[str, Any]]
    dossier_titles: dict[str, str | None]


@dataclass
class ArticleCitationEntry:
    target: dict[str, Any]
    start: int | None
    end: int | None
    text: str | None
    confidence: float | None
    qualifier: Qualifier = field(default_factory=Qualifier)
    reference_kind: str | None = None


def _record_article_citation(
    citations: list[ArticleCitationEntry],
    seen: set[tuple[str, int | None, int | None, str | None]],
    target_doc: dict[str, Any],
    start: int | None,
    end: int | None,
    text: str | None,
    confidence: float | None,
    qualifier: Qualifier | None = None,
    reference_kind: str | None = None,
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
            target=target_doc,
            start=start,
            end=end,
            text=text,
            confidence=confidence,
            qualifier=qualifier or Qualifier(),
            reference_kind=reference_kind,
        )
    )


def get_article_with_relations(
    store: ArangoStore,
    bwb_id: str,
    article_number: str,
) -> ArticleDetailData:
    """Fetch an article with its parent instrument and the judgments citing it."""
    article_key = make_node_key(bwb_id, article_number)
    article_doc = store.articles.get(article_key)
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


def _version_identity(
    article: dict[str, Any], bwb_id: str, article_number: str
) -> tuple[str, dict[str, Any]]:
    """The AQL filter on ``v`` (an ArticleVersion) that selects the versions of *article*,
    and its bind variables.

    The identity of an article inside its regulation is ``(bwb_id, stam_id)``; an article
    without a ``stam_id`` is matched on ``(bwb_id, article_number)``. Both filters are
    served by an index on ``article_versions``.
    """
    props = article.get("props") or {}
    bind: dict[str, Any] = {"bwb_id": props.get("bwb_id") or bwb_id.upper()}
    stam_id = props.get("stam_id")
    if stam_id:
        bind["identity"] = stam_id
        return "FILTER v.props.stam_id == @identity", bind
    bind["identity"] = props.get("article_number") or article_number
    return "FILTER v.props.article_number == @identity", bind


def get_article_history(
    store: ArangoStore,
    bwb_id: str,
    article_number: str,
) -> ArticleHistoryData:
    """All versions of one article identity, oldest first, plus dossier titles.

    The current article is resolved by key (``ValueError`` when unknown). Its
    identity inside the regulation is ``(bwb_id, stam_id)``; an article without a
    ``stam_id`` is matched on ``(bwb_id, article_number)``. Query budget: one for
    the versions and, when the publications name dossiers, one for their titles —
    independent of the number of versions.
    """
    article_key = make_node_key(bwb_id, article_number)
    article = _ensure_doc(store.articles.get(article_key))
    if article is None:
        raise ValueError("article not found")

    identity_filter, bind = _version_identity(article, bwb_id, article_number)
    aql = f"""
    FOR v IN {COLLECTION_ARTICLE_VERSIONS}
        FILTER v.props.bwb_id == @bwb_id
        {identity_filter}
        SORT v.props.valid_from ASC, v._key ASC
        RETURN v
    """
    versions = list(store.query(aql, bind))

    publications = [
        (v.get("props") or {}).get(field)
        for v in versions
        for field in ("origin_publication", "commencement_publication")
    ]
    titles = get_dossier_titles(store, collect_dossier_numbers(publications))
    return ArticleHistoryData(article=article, versions=versions, dossier_titles=titles)


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
        aql, {"article_id": article_id, "relation": RELATION_REFERS_TO}
    ):
        target_doc = _load_document_by_ref(store, edge.get("_to"))
        if not target_doc:
            continue
        start, end, text = _extract_span(edge)
        confidence = _extract_confidence(edge)
        qualifier, reference_kind = _extract_qualifier(edge)
        _record_article_citation(
            citations,
            seen,
            target_doc,
            start,
            end,
            text,
            confidence,
            qualifier,
            reference_kind,
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


def get_article_legislative_history(
    store: ArangoStore,
    bwb_id: str,
    article_number: str,
    article_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return dossiers/documents that introduced, amended, or propose to amend an article.

    Each entry: {dossier_id, dossier_number, dossier_title, date, kind, status,
    summary, document_id}. The explanatory documents are not among them: they
    explain a dossier's changes as a whole and are found by
    ``get_article_explanations``.
    """
    if article_id is None:
        article_key = make_node_key(bwb_id, article_number)
        article_id = f"{COLLECTION_ARTICLES}/{article_key}"

    # Every edge pointing at this article that says something about its text.
    mutation_relations = [
        RELATION_AMENDS,
        RELATION_INTRODUCES,
        RELATION_REPEALS,
        RELATION_REFERS_TO,
    ]
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._to == @article_id
        FILTER edge.relation IN @relations
        LET doc = DOCUMENT(edge._from)
        FILTER doc != null
        LET dossier = FIRST(
            FOR e2 IN {COLLECTION_EDGES}
                FILTER e2._from == edge._from AND e2.relation == '{RELATION_PART_OF}'
                FILTER STARTS_WITH(e2._to, '{COLLECTION_DOSSIERS}/')
                LET d = DOCUMENT(e2._to)
                FILTER d != null
                LIMIT 1 RETURN d
        )
        SORT edge.status == '{EDGE_STATUS_VOORGESTELD}' ? 0 : 1, doc.props.date DESC
        RETURN {{
            dossier_id: (dossier != null ? dossier._id : null),
            dossier_number: (dossier != null ? dossier.props.number : null),
            dossier_title: (dossier != null ? dossier.props.title : null),
            date: doc.props.date,
            kind: doc.props.kind,
            status: edge.status,
            summary: doc.props.display_name,
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


def get_article_explanations(
    store: ArangoStore,
    bwb_id: str,
    article_number: str,
    *,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """A page of the documents that EXPLAIN an article, and how many there are in all.

    An explanation is an EXPLAINS edge whose target is the article, one of its versions
    (found as ``get_article_history`` finds them) or its instrument; the edge of an
    explanatory memorandum usually points at a version. The rows say at which level
    they matched: level 0 for the article and its versions, level 1 for the instrument
    (an edge written only for a law that changed no articles, so no evidence about this
    article), sorted after the first. Per document and level one edge is kept, the one
    that says most (a version before the article, the newest version first); edges that
    carry a ``meta.section_anchor`` are kept apart from those that do not.

    An unknown article has no explanations: the answer is empty. Query budget: one
    lookup of the article and one query, driven by the ``(_to, relation)`` index of
    the edges, that reads the documents of the page only.
    """
    article = _ensure_doc(store.articles.get(make_node_key(bwb_id, article_number)))
    if article is None:
        return {"total": 0, "items": []}

    identity_filter, bind = _version_identity(article, bwb_id, article_number)
    aql = f"""
    LET targets = UNION(
        [{{ id: @article_id, level: 0, rank: 1, valid_from: null }}],
        (
            FOR v IN {COLLECTION_ARTICLE_VERSIONS}
                FILTER v.props.bwb_id == @bwb_id
                {identity_filter}
                RETURN {{ id: v._id, level: 0, rank: 0, valid_from: v.props.valid_from }}
        ),
        (
            FOR e IN {COLLECTION_EDGES}
                FILTER e._from == @article_id AND e.relation == @part_of
                FILTER STARTS_WITH(e._to, '{COLLECTION_INSTRUMENTS}/')
                RETURN {{ id: e._to, level: 1, rank: 0, valid_from: null }}
        )
    )
    LET found = (
        FOR t IN targets
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == t.id AND e.relation == @explains
                FILTER STARTS_WITH(e._from, '{COLLECTION_DOCUMENTS}/')
                LET document = DOCUMENT(e._from)
                FILTER document != null
                RETURN {{
                    document_id: document._id,
                    key: document._key,
                    date: document.props.date,
                    level: t.level,
                    rank: t.rank,
                    valid_from: t.valid_from,
                    target_id: t.id,
                    confidence: e.confidence,
                    section_anchor: e.meta.section_anchor
                }}
    )
    LET picked = (
        FOR f IN found
            COLLECT document_id = f.document_id, level = f.level,
                    section_anchor = f.section_anchor INTO grouped = f
            RETURN FIRST(
                FOR g IN grouped
                    SORT g.rank ASC, g.valid_from DESC, g.target_id ASC
                    LIMIT 1
                    RETURN g
            )
    )
    LET items = (
        FOR p IN picked
            SORT p.level ASC, p.date DESC, p.key ASC, p.section_anchor ASC
            LIMIT @offset, @limit
            LET document = DOCUMENT(p.document_id)
            LET dossier_number = FIRST(
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._from == p.document_id AND e.relation == @part_of
                    FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
                    LET dossier = DOCUMENT(e._to)
                    FILTER dossier != null AND dossier.props.number != null
                    SORT dossier.props.number
                    LIMIT 1
                    RETURN dossier.props.number
            )
            RETURN {{
                document_id: p.document_id,
                key: p.key,
                kind: document.props.kind,
                title: document.props.title,
                date: document.props.date,
                source: document.props.source,
                labels: document.labels,
                dossier_number: dossier_number,
                target_id: p.target_id,
                confidence: p.confidence,
                section_anchor: p.section_anchor
            }}
    )
    RETURN {{ total: LENGTH(picked), items: items }}
    """
    bind.update(
        {
            "article_id": article["_id"],
            "part_of": RELATION_PART_OF,
            "explains": RELATION_EXPLAINS,
            "limit": limit,
            "offset": offset,
        }
    )
    rows = list(store.query(aql, bind))
    return rows[0] if rows else {"total": 0, "items": []}


def get_article_in_flux(
    store: ArangoStore, bwb_id: str, article_number: str, article_id: str | None = None
) -> dict[str, Any]:
    """In-flux status for an article: a flag plus the number of proposed edges."""
    if article_id is None:
        article_key = make_node_key(bwb_id, article_number)
        article_id = f"{COLLECTION_ARTICLES}/{article_key}"

    aql = f"""
    LET proposed = LENGTH(
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._to == @article_id
            FILTER edge.status == '{EDGE_STATUS_VOORGESTELD}'
            RETURN 1
    )
    RETURN {{ in_flux: proposed > 0, open_dossier_count: proposed }}
    """
    rows = list(store.query(aql, {"article_id": article_id}))
    if rows:
        return rows[0]
    return {"in_flux": False, "open_dossier_count": 0}


def get_article_cited_by(
    store: ArangoStore,
    article_id: str,
    *,
    court: str | None = None,
    tier: str | None = None,
    lid: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """The passages of judgments that cite an article: one row per mention, newest first.

    ``(rows, total)`` with ``{judgment, mention}`` rows; ``total`` counts every mention that
    passes the filters, whatever the page. Filters: the ``court`` (ECLI court code) and
    ``tier`` of the judgment, and a ``lid`` number that the mention names.

    A much cited article has thousands of judgments (Sr 287, Awb 6:2) and a judgment is
    its text and its paragraphs. The first pass reads the edges of the article by
    ``(_to, relation)`` and keeps only what filters and sorts a mention (the edge, its
    position, the date and the ECLI); the mentions of the page, with their snippets, are
    read after the ``LIMIT``, for ``limit`` rows and not for all of them.

    The judgment is joined through its primary index, not ``DOCUMENT()``: the join reads
    the few attributes used, where ``DOCUMENT()`` holds the whole judgment in the memory of
    the query, for every judgment of the article at once.
    """
    aql = f"""
    LET hits = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @article_id AND e.relation == @relation
            FILTER STARTS_WITH(e._from, '{COLLECTION_JUDGMENTS}/')
            FOR j IN {COLLECTION_JUDGMENTS}
                FILTER j._id == e._from
                FILTER @court == null OR j.props.court_code == @court
                FILTER @tier == null OR j.props.tier == @tier
                LET count = LENGTH(e.meta.mentions)
                FILTER count > 0
                FOR position IN 0..count - 1
                    FILTER @lid == null OR @lid IN e.meta.mentions[position].leden
                    RETURN {{
                        edge: e._id,
                        position: position,
                        date: j.props.date_eff,
                        ecli: j.props.ecli
                    }}
    )
    LET page = (
        FOR hit IN hits
            SORT hit.date DESC, hit.ecli ASC, hit.edge ASC, hit.position ASC
            LIMIT @offset, @limit
            RETURN hit
    )
    RETURN {{
        total: LENGTH(hits),
        items: (
            FOR hit IN page
                LET e = DOCUMENT(hit.edge)
                FOR j IN {COLLECTION_JUDGMENTS}
                    FILTER j._id == e._from
                    RETURN {{
                        judgment: {{
                            _id: j._id,
                            _key: j._key,
                            props: {{
                                ecli: j.props.ecli,
                                display_name: j.props.display_name,
                                court_code: j.props.court_code,
                                tier: j.props.tier,
                                date_eff: j.props.date_eff
                            }}
                        }},
                        mention: e.meta.mentions[hit.position]
                    }}
        )
    }}
    """
    bind = {
        "article_id": article_id,
        "relation": RELATION_REFERS_TO,
        "court": court.upper() if court else None,
        "tier": tier,
        "lid": lid.lower() if lid else None,
        "limit": limit,
        "offset": offset,
    }
    answer = next(iter(store.query(aql, bind)), None) or {"total": 0, "items": []}
    return list(answer["items"]), int(answer["total"])
