"""Article query helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    EDGE_STATUS_VOORGESTELD,
    ENACTING_RELATIONS,
    RELATION_ESTABLISHES,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    SOURCE_STAATSBLAD,
)
from lawgraph.core import models
from lawgraph.core.bwb_xml import article_key
from lawgraph.core.courts import CODE_ECHR
from lawgraph.core.documents import is_explanatory
from lawgraph.core.models import make_node_key
from lawgraph.core.qualifiers import Qualifier
from lawgraph.core.reference_targets import reference_targets
from lawgraph.db import GraphStore
from lawgraph.db._rows import edge_doc, node_doc
from lawgraph.db.queries import proposals
from lawgraph.db.queries._helpers import (
    _count_judgments_for_article,
    _ensure_doc,
    _extract_confidence,
    _extract_qualifier,
    _extract_span,
    _find_instrument_for_article,
    run_together,
)
from lawgraph.db.queries._json_sql import array_or_empty, first_present
from lawgraph.db.queries.dossiers import collect_dossier_numbers, get_dossier_titles
from lawgraph.db.queries.judgment_sql import listed_judgment
from lawgraph.db.queries.not_found import NotFound, require_node
from lawgraph.db.schema import CITED_BY_TABLE, dossiers_of_sql, node_of
from lawgraph.db.version_cache import cached, lasting


@dataclass
class ArticleDetailData:
    article: dict[str, Any]
    instrument: dict[str, Any] | None
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
    target_id = target_doc.get("id")
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
    store: GraphStore,
    bwb_id: str,
    article_number: str,
) -> ArticleDetailData:
    """Fetch an article with its parent instrument and the number of judgments citing it
    (``metadata.judgment_count``; ``get_article_cited_by`` pages them)."""
    article_key = make_node_key(bwb_id, article_number)
    article_doc = require_node(store, COLLECTION_ARTICLES, article_key, "Article")

    article_id = article_doc["id"]
    found = run_together(
        lambda: _find_instrument_for_article(store, article_id),
        lambda: _count_judgments_for_article(store, article_id),
    )
    instrument_doc = cast("dict[str, Any] | None", found[0])
    return ArticleDetailData(
        article=article_doc,
        instrument=instrument_doc,
        metadata={"judgment_count": cast(int, found[1])},
    )


def _version_identity(
    article: dict[str, Any], bwb_id: str, article_number: str
) -> tuple[str, dict[str, Any]]:
    """The SQL condition on ``v`` (an ArticleVersion) that selects the versions of
    *article*, and its parameters.

    The identity of an article inside its regulation is ``(bwb_id, stam_id)``; an article
    without a ``stam_id`` is matched on ``(bwb_id, article_number)``. Both conditions are
    served by an index on ``article_versions``.
    """
    props = article.get("props") or {}
    bind: dict[str, Any] = {"bwb_id": props.get("bwb_id") or bwb_id.upper()}
    stam_id = props.get("stam_id")
    if stam_id:
        bind["identity"] = stam_id
        return "v.bwb_id = %(bwb_id)s AND v.stam_id = %(identity)s", bind
    bind["identity"] = props.get("article_number") or article_number
    return "v.bwb_id = %(bwb_id)s AND v.article_number = %(identity)s", bind


def explained_targets(
    article: dict[str, Any], bwb_id: str, article_number: str
) -> tuple[str, dict[str, Any]]:
    """The SQL of what an EXPLAINS edge of *article* points at, and its parameters: the
    article itself (``rank`` 1) and its versions as ``get_article_history`` finds them
    (``rank`` 0, with their ``valid_from``), each by its ``id``."""
    identity, bind = _version_identity(article, bwb_id, article_number)
    bind["article_id"] = article["id"]
    targets = f"""
    SELECT %(article_id)s::text AS id, 1 AS rank, NULL::text AS valid_from
    UNION ALL
    SELECT v.id, 0, v.valid_from
    FROM {COLLECTION_ARTICLE_VERSIONS} v
    WHERE {identity}"""
    return targets, bind


# Of the edges ``found`` to the targets of ``explained_targets``, the one that says most
# first: a version before the article, the newest version first.
_VERSION_FIRST = "rank, valid_from DESC NULLS LAST, target_id"


def surest_per_anchor(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One passage per section anchor, the surest of its matches (the first of equal
    ones), in the order the anchors first come."""
    best: dict[str, dict[str, Any]] = {}
    for section in sections:
        known = best.get(section["section_anchor"])
        if known is None or section["confidence"] > known["confidence"]:
            best[section["section_anchor"]] = section
    return list(best.values())


def get_article_history(
    store: GraphStore,
    bwb_id: str,
    article_number: str,
) -> ArticleHistoryData:
    """All versions of one article identity, oldest first, plus dossier titles.

    The current article is resolved by key (``NotFound`` when unknown). Its
    identity inside the regulation is ``(bwb_id, stam_id)``; an article without a
    ``stam_id`` is matched on ``(bwb_id, article_number)``. Query budget: one for
    the versions and, when the publications name dossiers, one for their titles —
    independent of the number of versions.
    """
    return _versions(store, bwb_id, article_number)


def get_article_version(
    store: GraphStore,
    bwb_id: str,
    article_number: str,
    version_key: str,
) -> ArticleHistoryData:
    """The version *version_key* of one article identity, as ``get_article_history``
    finds the versions, plus the titles of its dossiers. ``NotFound`` when the article
    is unknown or the version is not one of it."""
    data = _versions(store, bwb_id, article_number, version_key)
    if not data.versions:
        raise NotFound("Article version", version_key)
    return data


def get_article_versions_light(
    store: GraphStore, article: dict[str, Any], bwb_id: str, article_number: str
) -> ArticleHistoryData:
    """The versions of *article* (read already) as ``get_article_history`` finds them, each
    without what it holds beside its wording, its dates and what made it (its parts, its
    tables, its references): what the head of a reader names of them. Query budget as
    ``get_article_history``."""
    return _versions(store, bwb_id, article_number, article=article, light=True)


# What a version holds beside its wording, its dates and the publications that made it.
_VERSION_BULK = (
    "parts",
    "tables",
    "headings",
    "footnote_marks",
    "footnotes",
    "references",
)


def _versions(
    store: GraphStore,
    bwb_id: str,
    article_number: str,
    version_key: str | None = None,
    *,
    article: dict[str, Any] | None = None,
    light: bool = False,
) -> ArticleHistoryData:
    """The versions of the article identity, oldest first; only *version_key* when
    given. *article* when it is read already; *light* without ``_VERSION_BULK``."""
    if article is None:
        article_key = make_node_key(bwb_id, article_number)
        article = require_node(store, COLLECTION_ARTICLES, article_key, "Article")
    if (article.get("props") or {}).get("source") == SOURCE_STAATSBLAD:
        versions = [
            v
            for v in [_enacted_version(store, article)]
            if version_key is None or v["key"] == version_key
        ]
        return _with_titles(store, article, versions)

    identity, bind = _version_identity(article, bwb_id, article_number)
    if version_key is not None:
        identity += " AND v.key = %(version_key)s"
        bind["version_key"] = version_key
    props = "(v.props::jsonb - %(bulk)s::text[])::json" if light else "v.props"
    if light:
        bind["bulk"] = list(_VERSION_BULK)
    rows = store.query(
        f"""
        SELECT v.id, v.key, v.type, v.labels, {props} AS props
        FROM {COLLECTION_ARTICLE_VERSIONS} v
        WHERE {identity}
        ORDER BY v.valid_from NULLS FIRST, v.key
        """,
        bind,
    )
    return _with_titles(store, article, [node_doc(row) for row in rows])


def _with_titles(
    store: GraphStore, article: dict[str, Any], versions: list[dict[str, Any]]
) -> ArticleHistoryData:
    """*versions* of *article* with the titles of the dossiers of their publications."""
    publications = [
        (v.get("props") or {}).get(field)
        for v in versions
        for field in ("origin_publication", "commencement_publication")
    ]
    titles = get_dossier_titles(store, collect_dossier_numbers(publications))
    return ArticleHistoryData(article=article, versions=versions, dossier_titles=titles)


# What a publication of the Staatsblad did to an article of a law the BWB does not hold
# (``normalize staatsblad-laws``), as a version names its change (``effect_kind``).
_CHANGE_OF_RELATION = {
    RELATION_ESTABLISHES: "establishes",
    RELATION_INTRODUCES: "introduces",
}

# The publication the text of an article comes from: the law that gave it a text in place
# (``INTRODUCES``) before the law that enacted it.
_ENACTING_PUBLICATION = f"""
SELECT e.relation, p.props
FROM edges e JOIN {COLLECTION_INSTRUMENTS} p ON p.id = e.from_id
WHERE e.to_id = %(article)s AND e.relation = ANY(%(relations)s)
  AND e.from_collection = '{COLLECTION_INSTRUMENTS}'
ORDER BY e.relation = '{RELATION_INTRODUCES}' DESC, e.from_id
LIMIT 1
"""


def _enacted_version(store: GraphStore, article: dict[str, Any]) -> dict[str, Any]:
    """The one version of an article of a law of the Staatsblad: its text as enacted (not
    in force, so without a validity), made by the publication its text comes from."""
    rows = store.query(
        _ENACTING_PUBLICATION,
        {"article": article["id"], "relations": list(_CHANGE_OF_RELATION)},
    )
    found = next(iter(rows), None)
    props = dict(article.get("props") or {})
    if found is not None:
        publication = found["props"] or {}
        props["change"] = _CHANGE_OF_RELATION[found["relation"]]
        props["origin_publication"] = {
            "id": publication.get("official_id"),
            "url_identifier": publication.get("official_id"),
            "kind": publication.get("publication_kind"),
            "year": publication.get("publication_year"),
            "number": publication.get("publication_number"),
            "signed": publication.get("date_signed"),
            "published": publication.get("date_published"),
            "dossiers": publication.get("dossier_numbers") or [],
        }
    return {"id": article["id"], "key": article["key"], "props": props}


def present_targets(
    store: GraphStore, wanted: dict[str, set[str]]
) -> set[tuple[str, str]]:
    """The ``(collection, key)`` of *wanted* (keys per collection) the data holds: one
    lookup by primary key per collection."""
    return {
        (collection, key)
        for collection, keys in wanted.items()
        if keys
        for key in store.existing_keys(collection, keys)
    }


def get_article_citations(
    store: GraphStore,
    article_doc: dict[str, Any],
) -> list[ArticleCitationEntry]:
    doc = _ensure_doc(article_doc)
    article_id = doc.get("id") if doc else None
    if not article_id:
        return []
    return get_citations_of(store, [article_id]).get(article_id, [])


_CITATIONS = f"""
SELECT e.key, e.from_id, e.to_id, e.doc,
       n.id AS node_id, n.key AS node_key, n.type, n.labels, n.props
FROM {COLLECTION_EDGES} e CROSS JOIN {node_of("e.to_id", "e.to_collection")} n
WHERE e.from_id = ANY(%(ids)s) AND e.relation = %(relation)s
ORDER BY e.from_id, (e.doc -> 'meta' ->> 'start')::numeric ASC NULLS FIRST, e.key
"""


def get_citations_of(
    store: GraphStore, article_ids: list[str]
) -> dict[str, list[ArticleCitationEntry]]:
    """The citations (``REFERS_TO``) of each of *article_ids*, in text order, in one
    query: the edges out of them by their index, each with the node it points at. The key
    settles which of two equal spans is kept; an edge to a node that is not there is
    skipped."""
    if not article_ids:
        return {}
    found: dict[str, list[ArticleCitationEntry]] = {}
    seen: dict[str, set[tuple[str, int | None, int | None, str | None]]] = {}
    rows = store.query(
        _CITATIONS, {"ids": list(article_ids), "relation": RELATION_REFERS_TO}
    )
    for row in rows:
        edge = edge_doc(row)
        target_doc = node_doc({**row, "id": row["node_id"], "key": row["node_key"]})
        start, end, text = _extract_span(edge)
        qualifier, reference_kind = _extract_qualifier(edge)
        citations = found.setdefault(row["from_id"], [])
        _record_article_citation(
            citations,
            seen.setdefault(row["from_id"], set()),
            target_doc,
            start,
            end,
            text,
            _extract_confidence(edge),
            qualifier,
            reference_kind,
        )
    return found


@dataclass
class CurrentReferences:
    """The references and citations of the articles whose current version is among a page
    of versions, and the targets of those references the data holds."""

    # per version key: the references stored on its article
    references: dict[str, list[dict[str, Any]]]
    # per version key: the citations of its article
    citations: dict[str, list[ArticleCitationEntry]]
    present: set[tuple[str, str]]


def get_current_references(
    store: GraphStore, versions: list[dict[str, Any]]
) -> CurrentReferences:
    """Of each version in *versions* that is the current version of its article (its
    ``versie_id`` that of the article), the references and citations of the article: those
    are spans of the current text. Three queries at most and one per collection of the
    targets, whatever the number of versions."""
    keys: dict[str, str] = {}
    for version in versions:
        props = version.get("props") or {}
        if not props.get("current") or not props.get("bwb_id"):
            continue
        key = article_key(
            str(props["bwb_id"]), props.get("article_number"), props.get("stam_id")
        )
        if key:
            keys[key] = version["key"]
    versie = {v["key"]: (v.get("props") or {}).get("versie_id") for v in versions}
    rows = (
        store.query(
            f"""
            SELECT id, key, lg_str(props -> 'versie_id') AS versie_id,
                   props -> 'references' AS refs
            FROM {COLLECTION_ARTICLES} WHERE key = ANY(%(keys)s)
            """,
            {"keys": list(keys)},
        )
        if keys
        else []
    )
    of_version = {
        row["id"]: (
            keys[row["key"]],
            row["refs"] if isinstance(row["refs"], list) else [],
        )
        for row in rows
        if row["versie_id"] == versie.get(keys[row["key"]])
    }
    citations = get_citations_of(store, list(of_version))
    wanted: dict[str, set[str]] = {}
    for _, refs in of_version.values():
        for collection, found in reference_targets(refs).items():
            wanted.setdefault(collection, set()).update(found)
    return CurrentReferences(
        references=dict(of_version.values()),
        citations={
            version: citations.get(article_id, [])
            for article_id, (version, _) in of_version.items()
        },
        present=present_targets(store, wanted),
    )


# The key of a dossier from its id (``PARSE_IDENTIFIER(id).key``).
_DOSSIER_KEY_FROM = len(COLLECTION_DOSSIERS) + 2

_CHANGES_SQL = f"""
SELECT
    ARRAY(
        SELECT substr(found.id, {_DOSSIER_KEY_FROM}) AS k FROM (
            {dossiers_of_sql("e.from_id")}
            UNION
            SELECT e2.to_id
            FROM {COLLECTION_EDGES} e2
            WHERE e2.from_id = e.from_id AND e2.relation = %(legislated_in)s
              AND e2.to_collection = '{COLLECTION_DOSSIERS}'
        ) found(id)
        ORDER BY k
    ) AS dossier_keys,
    CASE WHEN s.collection = '{COLLECTION_INSTRUMENTS}'
        THEN s.props -> 'dossier_numbers' END AS numbers,
    {first_present("s.props -> 'date'", "s.props -> 'date_published'", "s.props -> 'date_signed'")}
        AS date,
    {first_present("s.props -> 'kind'", "s.props -> 'publication_kind'")} AS kind,
    lower(e.relation) AS change,
    e.doc -> 'status' AS status,
    s.props -> 'display_name' AS summary,
    s.id AS document_id
FROM {COLLECTION_EDGES} e
CROSS JOIN {node_of("e.from_id", "e.from_collection")} s
WHERE e.to_id = %(article_id)s AND e.relation = ANY(%(changes)s)
  AND (e.from_collection <> '{COLLECTION_DOCUMENTS}' OR {proposals.pending_sql("e.from_id")})
-- The sorts in Python are stable: the edge key and the sorted dossier keys settle ties.
ORDER BY e.key
"""


def get_article_legislative_history(
    store: GraphStore,
    bwb_id: str,
    article_number: str,
    article_id: str | None = None,
) -> list[dict[str, Any]]:
    """The dossiers that established, introduced, amended or repealed an article, or
    propose to.

    A change is an ``ESTABLISHES`` (the publication that enacted its regulation),
    ``AMENDS``, ``INTRODUCES`` or ``REPEALS`` edge to the article: from a publication
    (enacted, ``canoniek``), whose dossiers are those it is
    ``LEGISLATED_IN`` and those its ``dossier_numbers`` name (a dossier that is not in the
    graph has no ``dossier_id``), or from a bill (``voorgesteld``), whose dossier it is
    ``PART_OF``, directly or through its case, while it is pending (``queries.proposals``:
    its dossier open, no amendment rejected, withdrawn or replaced). One entry per change
    and dossier; a change without a dossier is none, and what only cites the article (a
    judgment, another article) is no change.

    Each entry: {dossier_id, dossier_number, dossier_title, date, kind, change, status,
    summary, document_id}; proposed changes first, then newest first. The explanatory
    documents are found by ``get_article_explanations``.
    """
    if article_id is None:
        article_id = models.article_id(bwb_id, article_number)

    changes = list(
        store.query(
            _CHANGES_SQL,
            {
                "article_id": article_id,
                "changes": list(ENACTING_RELATIONS),
                "legislated_in": RELATION_LEGISLATED_IN,
            },
        )
    )
    # A number names the dossier whose key it makes; one lookup for every dossier.
    for change in changes:
        change["numbers"] = {make_node_key(n): n for n in change["numbers"] or []}
        change["dossier_keys"] += [
            key for key in change["numbers"] if key not in change["dossier_keys"]
        ]
    keys = sorted({k for change in changes for k in change["dossier_keys"]})
    dossiers = (
        {
            row["key"]: row
            for row in store.query(
                f"""
                SELECT key, id, props -> 'label' AS label, props -> 'title' AS title
                FROM {COLLECTION_DOSSIERS}
                WHERE key = ANY(%(keys)s)
                ORDER BY key
                """,
                {"keys": keys},
            )
        }
        if keys
        else {}
    )
    entries = []
    for change in changes:
        numbers = change.pop("numbers")
        for key in change.pop("dossier_keys"):
            dossier = dossiers.get(key)
            entries.append(
                {
                    **change,
                    "dossier_id": dossier["id"] if dossier else None,
                    "dossier_number": dossier["label"] if dossier else numbers[key],
                    "dossier_title": dossier["title"] if dossier else None,
                }
            )
    entries.sort(key=lambda e: e["dossier_number"] or "")
    entries.sort(key=lambda e: e["date"] or "", reverse=True)
    entries.sort(key=lambda e: e["status"] != EDGE_STATUS_VOORGESTELD)
    return entries


# The explanations of an article. ``found``: an EXPLAINS edge from a document to the
# article (rank 1) or one of its versions (rank 0); ``picked``: per document and section
# anchor the edge that says most (a version before the article, the newest version
# first); ``ranked``: the order of the answer, newest document first.
def _explanations_sql(targets: str, importance: bool = False) -> str:
    """The statement of ``get_article_explanations``, of the *targets* of
    ``explained_targets``; with *importance* the passages that name the article come before
    the explanations written for a whole dossier, then the most confident."""
    first = (
        "(p.section_anchor IS NULL) ASC NULLS LAST, lg_num(p.confidence) DESC NULLS LAST,"
        if importance
        else ""
    )
    return f"""
WITH targets AS ({targets}
),
found AS (
    SELECT d.id AS document_id, d.key, d.date, t.rank, t.valid_from,
           t.id AS target_id, e.doc -> 'confidence' AS confidence,
           -- a missing anchor and a json null are one group, as in a COLLECT
           nullif((e.doc -> 'meta' -> 'section_anchor')::jsonb, 'null'::jsonb)
               AS section_anchor,
           e.doc -> 'meta' -> 'heading' AS heading,
           lg_num(e.doc -> 'meta' -> 'char_start')::int AS char_start,
           lg_num(e.doc -> 'meta' -> 'char_end')::int AS char_end
    FROM targets t
    JOIN {COLLECTION_EDGES} e
      ON e.to_id = t.id AND e.relation = %(explains)s
     AND e.from_collection = '{COLLECTION_DOCUMENTS}'
    JOIN {COLLECTION_DOCUMENTS} d ON d.id = e.from_id
),
picked AS (
    SELECT DISTINCT ON (document_id, section_anchor) *
    FROM found
    ORDER BY document_id, section_anchor, {_VERSION_FIRST}
),
ranked AS (
    SELECT p.*, row_number() OVER (
        ORDER BY {first} p.date DESC NULLS LAST, p.key NULLS FIRST,
                 lg_str(p.section_anchor::json) NULLS FIRST
    ) AS n
    FROM picked p
)
SELECT
    (SELECT count(*)::int FROM picked) AS total,
    (
        SELECT coalesce(json_agg(json_build_object(
            'document_id', r.document_id,
            'key', r.key,
            -- columns where there are, so the props (the whole text) are read once
            'kind', to_json(d.kind),
            'title', d.props -> 'title',
            'date', to_json(d.date),
            'source', to_json(d.source),
            'labels', to_json(d.labels),
            'dossier_number', (
                SELECT ds.label
                FROM {COLLECTION_EDGES} e
                JOIN {COLLECTION_DOSSIERS} ds ON ds.id = e.to_id
                WHERE e.from_id = r.document_id AND e.relation = %(part_of)s
                  AND e.to_collection = '{COLLECTION_DOSSIERS}'
                  AND ds.label IS NOT NULL
                ORDER BY ds.label
                LIMIT 1
            ),
            -- its own number, which its address is made of
            'paper', json_build_object(
                'dossier_number', d.props -> 'dossier_number',
                'dossier_suffix', d.props -> 'dossier_suffix',
                'sequence', d.props -> 'sequence'),
            'target_id', r.target_id,
            'confidence', r.confidence,
            'section_anchor', r.section_anchor,
            'heading', r.heading,
            'char_start', r.char_start,
            'char_end', r.char_end,
            -- the start of the passage, which the answer cuts to an excerpt
            'opening', CASE WHEN r.char_start IS NOT NULL AND r.char_end > r.char_start
                THEN substr(d.props ->> 'text', r.char_start + 1,
                            least(r.char_end - r.char_start, %(opening)s)) END
        ) ORDER BY r.n), '[]'::json)
        FROM ranked r JOIN {COLLECTION_DOCUMENTS} d ON d.id = r.document_id
        WHERE r.n > %(offset)s AND r.n <= %(offset)s + %(limit)s
    ) AS items
"""


# The characters of a passage read for its excerpt: its heading and some 300 after it.
EXPLANATION_OPENING = 600


def get_article_explanations(
    store: GraphStore,
    bwb_id: str,
    article_number: str,
    *,
    limit: int,
    offset: int,
    importance: bool = False,
) -> dict[str, Any]:
    """A page of the documents that EXPLAIN an article, and how many there are in all.

    An explanation is an EXPLAINS edge whose target is the article or one of its versions
    (found as ``get_article_history`` finds them); the edge of an explanatory memorandum
    usually points at a version. An edge to the article's law is no explanation of the
    article: it is written for a law that changed no articles, and says nothing about this
    one. Per document one edge is kept, the one that says most (a version before the
    article, the newest version first); edges that carry a ``meta.section_anchor`` are kept
    apart from those that do not.

    An unknown article has no explanations: the answer is empty. Query budget: one
    lookup of the article and one query, driven by the ``(to_id, relation)`` index of
    the edges, that reads the documents of the page only.
    """
    article = _ensure_doc(
        store.get_document(COLLECTION_ARTICLES, make_node_key(bwb_id, article_number))
    )
    if article is None:
        return {"total": 0, "items": []}

    targets, bind = explained_targets(article, bwb_id, article_number)
    bind.update(
        {
            "part_of": RELATION_PART_OF,
            "explains": RELATION_EXPLAINS,
            "limit": limit,
            "offset": offset,
            "opening": EXPLANATION_OPENING,
        }
    )
    rows = list(store.query(_explanations_sql(targets, importance), bind))
    return rows[0] if rows else {"total": 0, "items": []}


# Per document that explains the article in a passage (``meta.sections`` of its EXPLAINS
# edges to the article or a version): the version it explains (the newest, as
# ``_explanations_sql`` picks it), and the sections of all those edges with their text.
# The props of a document (its whole text) are read once, and only the passages leave.
def _passages_sql(targets: str) -> str:
    """The statement of ``get_article_explanation_passages``, of the *targets* of
    ``explained_targets``."""
    return f"""
WITH targets AS ({targets}
),
found AS (
    SELECT e.from_id AS document_id, t.id AS target_id, t.rank, t.valid_from,
           e.doc -> 'meta' -> 'sections' AS sections
    FROM targets t
    JOIN {COLLECTION_EDGES} e
      ON e.to_id = t.id AND e.relation = %(explains)s
     AND e.from_collection = '{COLLECTION_DOCUMENTS}'
    WHERE json_typeof(e.doc -> 'meta' -> 'sections') = 'array'
),
picked AS (
    SELECT DISTINCT ON (document_id) document_id, target_id, valid_from
    FROM found
    ORDER BY document_id, {_VERSION_FIRST}
)
SELECT json_build_object(
    'document_id', p.document_id,
    'key', d.key,
    'kind', to_json(d.kind),
    'date', to_json(d.date),
    'source', to_json(d.source),
    'labels', to_json(d.labels),
    -- what names the paper (DocumentEntryDTO), without its text
    'props', (
        SELECT coalesce(json_object_agg(j.key, j.value ORDER BY j.key), '{{}}'::json)
        FROM json_each(c.p) j WHERE j.key NOT IN ('text', 'sections')
    ),
    'target_id', p.target_id,
    'valid_from', to_json(p.valid_from),
    'passages', (
        SELECT coalesce(json_agg(json_build_object(
            'section_anchor', s -> 'section_anchor',
            'heading', s -> 'heading',
            'level', (
                SELECT x -> 'level' FROM json_array_elements(c.sections) x
                WHERE x ->> 'id' = s ->> 'section_anchor' LIMIT 1
            ),
            'char_start', s -> 'char_start',
            'char_end', s -> 'char_end',
            'text', substr(c.text, (s ->> 'char_start')::int + 1,
                           (s ->> 'char_end')::int - (s ->> 'char_start')::int),
            'confidence', s -> 'confidence',
            'match_type', s -> 'match_type',
            'changed', s -> 'changed',
            'explanation', s -> 'explanation'
        )), '[]'::json)
        FROM found f
        CROSS JOIN LATERAL json_array_elements(f.sections) s
        WHERE f.document_id = p.document_id
          AND (s ->> 'char_end')::int <= length(c.text)
    )
)
FROM picked p
JOIN {COLLECTION_DOCUMENTS} d ON d.id = p.document_id
CROSS JOIN LATERAL (
    SELECT k.p, k.p ->> 'text' AS text,
           {array_or_empty("k.p -> 'sections'")} AS sections
    FROM (
        SELECT json_object_agg(j.key, j.value) AS p
        FROM json_each(d.props) j
        WHERE j.key IN ('title', 'text', 'sections', 'dossier_number',
                        'dossier_suffix', 'number', 'sequence', 'session_year',
                        'document_number', 'actors')
    ) k
    OFFSET 0
) c
WHERE c.text IS NOT NULL
"""


def _explanation_passages(
    store: GraphStore, bwb_id: str, article_number: str
) -> list[dict[str, Any]]:
    article = _ensure_doc(
        store.get_document(COLLECTION_ARTICLES, make_node_key(bwb_id, article_number))
    )
    if article is None:
        return []
    targets, bind = explained_targets(article, bwb_id, article_number)
    bind["explains"] = RELATION_EXPLAINS
    rows = []
    for row in store.query(_passages_sql(targets), bind):
        # in the order of the text
        row["passages"] = sorted(
            surest_per_anchor(row["passages"]),
            key=lambda s: (s["char_start"], s["section_anchor"]),
        )
        if row["passages"]:
            rows.append(row)
    # of one version the memoranda before the amendments, then by date; the newest
    # version first and the article itself (no version) last (both sorts keep order)
    rows.sort(key=lambda r: (not is_explanatory(r["kind"]), r["date"] or "", r["key"]))
    rows.sort(key=lambda r: r["valid_from"] or "", reverse=True)
    return rows


def get_article_explanation_passages(
    store: GraphStore, bwb_id: str, article_number: str
) -> list[dict[str, Any]]:
    """The documents that explain an article in a passage, each with its passages: the
    sections of its EXPLAINS edges to the article or one of its versions
    (``meta.sections``, written by ``semantic tk-mvt-articles``), one per section, the
    surest of its matches, in the order of the text, with their text. A section beyond
    the end of the document's text is left out, and so is a document without passages;
    an explanation of the whole dossier (no sections) is none. The newest version first
    (the article itself, no version, last); of one version the memoranda before the
    amendments. Kept per data version of the tables it reads; an unknown article has
    none."""
    return cached(
        store,
        ("article explanation passages", bwb_id, article_number),
        lambda: _explanation_passages(store, bwb_id, article_number),
        tables=(
            COLLECTION_ARTICLES,
            COLLECTION_ARTICLE_VERSIONS,
            COLLECTION_EDGES,
            COLLECTION_DOCUMENTS,
        ),
    )


@dataclass(frozen=True)
class CitedBy:
    """A page of the passages that cite an article: ``{judgment, mention, origin}`` rows, the
    passages that match the filters and the judgments they are in, and ``facets``: per ``year``,
    ``tier`` and ``subject_area`` the judgments under the other filters (``{value, count}``)."""

    rows: list[dict[str, Any]]
    total: int
    judgment_total: int
    echr_judgment_total: int = 0
    facets: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {"year": [], "tier": [], "subject_area": []}
    )


# ``hits``: per judgment that cites the article (a row of ``lg_cited_by``), one row per
# mention that passes the court and lid filters, with only what sorts and counts it; ``kept``:
# those of the tiers, the year and the main area of law asked for; ``page``: those of the page, cut by a limit (so
# the planner reads their edges by key, not every edge). The mentions of the page are read
# whole from their edges after the cut. Each facet counts the judgments of ``hits`` under
# the other filter.
_TIERS_KEPT = "(%(tiers)s::text[] IS NULL OR h.tier = ANY(%(tiers)s::text[]))"
_YEAR_KEPT = "(%(year)s::text IS NULL OR h.year = %(year)s::text)"
_AREA_KEPT = "(%(area)s::text IS NULL OR h.areas @> ARRAY[%(area)s::text])"


def _cited_by_facet(value: str, where: str, order: str, *, many: bool = False) -> str:
    """SQL: the judgments of ``hits`` under *where*, counted per *value*, in *order*; with
    *many*, *value* is an array and a judgment counts for each of its values."""
    source = (
        f"hits h CROSS JOIN LATERAL unnest(h.{value}) AS u(value)" if many else "hits h"
    )
    column = "u.value" if many else f"h.{value}"
    return f"""(
            SELECT coalesce(json_agg(json_build_object('value', f.value, 'count', f.n)
                                     ORDER BY {order}), '[]'::json)
            FROM (
                SELECT {column} AS value, count(DISTINCT h.edge)::int AS n
                FROM {source} WHERE {where} GROUP BY {column}
            ) f
        )"""


# The mentions of a row ``c`` of ``lg_cited_by`` as ``m.position`` (from 0): every one by
# its number, read from the index alone; under a ``lid`` those that name it, read from the
# leden kept with the row.
_EVERY_MENTION = "generate_series(0, c.mentions - 1) AS m(position)"
_MENTIONS_OF_LID = """(
            SELECT x.n - 1 AS position
            FROM json_array_elements(c.leden) WITH ORDINALITY AS x(leden, n)
            WHERE %(lid)s::text = ANY(lg_text_array(x.leden))
        ) m"""


def _cited_by_sql(order: str, *, lid: bool) -> str:
    """The statement of ``get_article_cited_by``, its passages in *order*; with *lid*, of
    the passages that name ``%(lid)s`` alone."""
    return f"""
    WITH hits AS MATERIALIZED (
        SELECT c.edge_key AS edge, m.position, c.date_eff AS date, c.ecli, c.cited, c.tier,
               c.areas, substr(c.date_eff, 1, 4) AS year
        FROM {CITED_BY_TABLE} c
        CROSS JOIN LATERAL {_MENTIONS_OF_LID if lid else _EVERY_MENTION}
        WHERE c.article_id = %(article_id)s
          AND (%(court)s::text IS NULL OR c.court_code = %(court)s::text)
    ),
    kept AS (
        SELECT h.* FROM hits h WHERE {_TIERS_KEPT} AND {_YEAR_KEPT} AND {_AREA_KEPT}
    ),
    page AS (
        SELECT h.edge, h.position, row_number() OVER (ORDER BY {order}) AS n
        FROM kept h
        ORDER BY n
        LIMIT %(limit)s OFFSET %(offset)s
    )
    SELECT
        (SELECT count(*)::int FROM kept) AS total,
        -- one edge per judgment and article
        (SELECT count(DISTINCT edge)::int FROM kept) AS judgment_total,
        json_build_object(
            'year', {
        _cited_by_facet(
            "year", f"{_TIERS_KEPT} AND {_AREA_KEPT}", "f.value ASC NULLS FIRST"
        )
    },
            'tier', {
        _cited_by_facet(
            "tier", f"{_YEAR_KEPT} AND {_AREA_KEPT}", "f.n DESC, f.value ASC"
        )
    },
            'subject_area', {
        _cited_by_facet(
            "areas",
            f"{_TIERS_KEPT} AND {_YEAR_KEPT}",
            "f.n DESC, f.value ASC",
            many=True,
        )
    }
        ) AS facets,
        -- the ECHR judgments that cite it: HUDOC names the article (and its leden), no passage
        (
            SELECT count(DISTINCT c.judgment_id)::int FROM {CITED_BY_TABLE} c
            WHERE c.article_id = %(article_id)s AND c.court_code = '{CODE_ECHR}'
        ) AS echr_judgment_total,
        (
            SELECT coalesce(json_agg(json_build_object(
                'judgment', {
        listed_judgment(
            "j",
            "l",
            "'inbound_citation_count', j.pj_inbound_citation_count",
            "'subjects', j.subjects",
        )
    },
                'mention', (e.doc -> 'meta' -> 'mentions') -> r.position::int,
                'origin', e.doc -> 'meta' -> 'origin'
            ) ORDER BY r.n), '[]'::json)
            FROM page r
            JOIN {COLLECTION_EDGES} e ON e.key = r.edge
            JOIN {COLLECTION_JUDGMENTS} j ON j.id = e.from_id
            LEFT JOIN lg_judgment_light l ON l.id = j.id
        ) AS items
    """


# How long the list of the most cited articles is kept (seconds): it reads the citation
# count of every article, and it changes with a weekly run.
MOST_CITED_MAX_AGE = 86400.0


def most_cited_articles(store: GraphStore, at_least: int) -> list[dict[str, Any]]:
    """``{id, key}`` of the articles with *at_least* citations (``inbound_citation_count``),
    the most cited first, kept ``MOST_CITED_MAX_AGE``."""
    return lasting(
        store,
        ("most cited articles", at_least),
        lambda: list(
            store.query(
                """
                SELECT id, key FROM articles
                WHERE inbound_citation_count >= %(at_least)s
                ORDER BY inbound_citation_count DESC NULLS LAST, key
                """,
                {"at_least": max(at_least, 1)},
            )
        ),
        MOST_CITED_MAX_AGE,
    )


# How long the passages citing an article are kept per request (seconds), whatever the data
# does: of a much cited article (6:162 BW, Awb 1:3) they are thousands; a poll adds a handful. A newer answer computes in the background while the kept one is
# served.
CITED_BY_MAX_AGE = 3600.0

# The orders of the passages: the newest judgment first, or the most cited one (a
# standard judgment) first and then the newest.
CITED_BY_SORTS: dict[str, str] = {
    "date_desc": "h.date DESC NULLS LAST, h.ecli NULLS FIRST, h.edge, h.position",
    "citation_count": (
        "h.cited DESC NULLS LAST, h.date DESC NULLS LAST, h.ecli NULLS FIRST, h.edge,"
        " h.position"
    ),
}


# An article cited fewer times than this has a range of the index of ``lg_cited_by`` of a few
# thousand rows at most: its passages are read in milliseconds, in the request (``inline``),
# not queued behind the workers of the cache, which a warm-up holds for minutes (an article
# without a citation took 7 s on prod on 26 Oct, cold). One cited so often is warmed
# (``warm``).
CITED_BY_INLINE_BELOW = 1500


def citation_count(store: GraphStore, key: str) -> int | None:
    """How often the article *key* is cited (``inbound_citation_count``); none for an
    unknown article. A primary-key lookup."""
    row = next(
        store.query(
            f"SELECT coalesce(inbound_citation_count, 0)::int FROM {COLLECTION_ARTICLES}"
            " WHERE key = %(key)s",
            {"key": key},
        ),
        None,
    )
    return None if row is None else int(row)


def get_article_cited_by(
    store: GraphStore,
    article_id: str,
    *,
    sort: str = "date_desc",
    court: str | None = None,
    tiers: tuple[str, ...] = (),
    year: str | None = None,
    area: str | None = None,
    lid: str | None = None,
    limit: int = 50,
    offset: int = 0,
    inline: bool = False,
) -> CitedBy:
    """The passages of judgments that cite an article: one row per mention, newest first.

    ``total`` counts every mention that passes the filters, whatever the page, and
    ``judgment_total`` the judgments they are in; ``echr_judgment_total`` the ECHR
    judgments that cite the article, whatever the filters: HUDOC names the article they
    apply, not a passage, so they have no row. Filters: the ``court`` (ECLI court code),
    any of the ``tiers``, the ``year`` (of its date) and the main ``area`` of law (the part
    of a subject of the source before its first ';': ``Strafrecht``) of the judgment, and
    a ``lid`` number that the mention names. ``facets`` counts the judgments, each under
    the other filters: per ``year`` (oldest first, none first), per ``tier`` (most first)
    and per main area of law (``subject_area``, most first; a judgment counts for each of
    its areas). ``sort`` (``CITED_BY_SORTS``): the newest judgment first, or the most
    cited first. With *inline* an answer not kept is computed in the caller's thread
    (``CITED_BY_INLINE_BELOW``).

    A much cited article has thousands of judgments (6:162 BW: 10,500), each an edge with
    its mentions and a judgment with its text. The first pass reads only what filters,
    sorts and counts a mention, from the range of the article in the index of
    ``lg_cited_by`` (its leden from the rows, under a ``lid``); the mentions of the page,
    with their snippets, are read from their edges after the cut, for ``limit`` rows and
    not for all of them.
    """
    chosen = tuple(dict.fromkeys(tiers))
    bind = {
        "article_id": article_id,
        "court": court.upper() if court else None,
        "tiers": list(chosen) or None,
        "year": year,
        "area": area,
        "lid": lid.lower() if lid else None,
        "limit": limit,
        "offset": offset,
    }
    key = {**bind, "tiers": chosen}
    answer = lasting(
        store,
        ("cited-by", sort, *sorted(key.items())),
        lambda: (
            next(
                iter(
                    store.query(
                        _cited_by_sql(CITED_BY_SORTS[sort], lid=bool(lid)), bind
                    )
                ),
                None,
            )
            or {}
        ),
        CITED_BY_MAX_AGE,
        inline=inline,
    )
    facets = answer.get("facets") or {}
    return CitedBy(
        rows=list(answer.get("items") or []),
        total=int(answer.get("total") or 0),
        judgment_total=int(answer.get("judgment_total") or 0),
        echr_judgment_total=int(answer.get("echr_judgment_total") or 0),
        facets={
            name: list(facets.get(name) or [])
            for name in ("year", "tier", "subject_area")
        },
    )
