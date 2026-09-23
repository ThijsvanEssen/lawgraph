"""Resolve a typed citation, identifier or law name to the node it names.

``core.notation`` reads the text; this module asks the graph whether the thing exists and
answers with one best match and the others that fit. Every lookup is a key or an index
lookup, except an article without a law, which is one query on the search view.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
)
from lawgraph.core.models import collection_from_id, make_node_key
from lawgraph.core.notation import LawMatch, Notation
from lawgraph.db import ArangoStore
from lawgraph.db.queries.dossiers import _dossier_documents_aql
from lawgraph.db.queries.search import load_notation_parser

# What a confidence means: how sure the resolver is that the match is what the query meant.
CONFIDENCE_IDENTIFIER = 1.0  # an ECLI, BWB id or CELEX id that names one node
CONFIDENCE_CITATION = 0.95  # a citation read whole: article of a law, dossier, paper
CONFIDENCE_NAME = 0.9  # a law by its exact abbreviation or full name
CONFIDENCE_PARTIAL = 0.6  # the dossier of a paper that is not in the graph; a law by the start of its name
CONFIDENCE_AMBIGUOUS = 0.5  # the ceiling when several nodes fit equally well
CONFIDENCE_CONTAINS = 0.4  # a law by part of its name
CONFIDENCE_ONE_LAW = 0.5  # an article without a law, found in one law only
CONFIDENCE_SEVERAL_LAWS = 0.3  # an article without a law, found in several

ALTERNATIVES = 5  # the other matches an answer lists
_ARTICLE_POOL = (
    500  # the articles of one number read from the view before the best are picked
)

_LAW_CONFIDENCE = {
    "code": CONFIDENCE_NAME,
    "title": CONFIDENCE_NAME,
    "prefix": CONFIDENCE_PARTIAL,
    "contains": CONFIDENCE_CONTAINS,
}

_NAME_OF = {
    COLLECTION_INSTRUMENTS: (
        "NOT_NULL(doc.props.citation_title, doc.props.display_name, doc.props.title)"
    ),
}
_DEFAULT_NAME = "NOT_NULL(doc.props.display_name, doc.props.title)"

NO_MATCH: dict[str, Any] = {
    "kind": "none",
    "confidence": 0.0,
    "match": None,
    "alternatives": [],
    "qualifier": None,
}


def _target(row: dict[str, Any], kind: str, confidence: float) -> dict[str, Any]:
    return {
        "id": row["id"],
        "key": row["key"],
        "collection": collection_from_id(row["id"], ""),
        "kind": kind,
        "display_name": row.get("display_name"),
        "confidence": confidence,
    }


def _capped(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Several nodes that fit equally well: none of them is surely the one."""
    if len(targets) > 1:
        for target in targets:
            target["confidence"] = min(target["confidence"], CONFIDENCE_AMBIGUOUS)
    return targets


def _by_keys(
    store: ArangoStore, collection: str, keys: list[str]
) -> list[dict[str, Any]]:
    """The nodes with these keys, in the order of *keys*."""
    aql = f"""
    FOR doc IN {collection}
        FILTER doc._key IN @keys
        RETURN {{
            id: doc._id, key: doc._key,
            display_name: {_NAME_OF.get(collection, _DEFAULT_NAME)}
        }}
    """
    rows = list(store.query(aql, {"keys": keys}))
    return sorted(rows, key=lambda row: keys.index(row["key"]))


# ── identifiers and law names ─────────────────────────────────────────────────


def _identified(store: ArangoStore, notation: Notation) -> list[dict[str, Any]]:
    """An ECLI, BWB id or CELEX id: the node with that key."""
    identifier = notation.identifier or ""
    if notation.kind == "ecli":
        keys = [make_node_key(identifier), make_node_key("echr", identifier)]
        rows = _by_keys(store, COLLECTION_JUDGMENTS, keys)
        kind = "judgment"
    else:
        rows = _by_keys(store, COLLECTION_INSTRUMENTS, [make_node_key(identifier)])
        kind = "instrument"
    return [_target(row, kind, CONFIDENCE_IDENTIFIER) for row in rows[:1]]


def _laws_named(store: ArangoStore, matches: list[LawMatch]) -> list[dict[str, Any]]:
    """The instruments for the laws a text may name, each with the confidence of its tier."""
    keys = {make_node_key(m.law_id): m for m in matches}
    rows = _by_keys(store, COLLECTION_INSTRUMENTS, list(keys))
    targets = [
        _target(row, "instrument", _LAW_CONFIDENCE[keys[row["key"]].tier])
        for row in rows
    ]
    whole = [t for t in targets if t["confidence"] == CONFIDENCE_NAME]
    _capped(whole)
    return targets


# ── articles ──────────────────────────────────────────────────────────────────


def _articles(store: ArangoStore, notation: Notation) -> list[dict[str, Any]]:
    named = [a for a in notation.articles if a.law_id]
    if named:
        keys = [make_node_key(a.law_id, a.number) for a in named]
        rows = _by_keys(store, COLLECTION_ARTICLES, keys)
        return [_target(row, "article", CONFIDENCE_CITATION) for row in rows]
    return _articles_without_law(store, [a.number for a in notation.articles])


def _articles_without_law(
    store: ArangoStore, numbers: list[str]
) -> list[dict[str, Any]]:
    """The articles with this number in any law, the most cited first.

    Read from the search view (the ``lawgraph_norm`` analyzer makes the number match in any
    case): a number alone has no index of its own, and a scan of every article is not an
    answer to a keystroke. A number that every law has (``1``) is read up to a pool.
    """
    clause = " OR ".join(
        f"ANALYZER(hit.props.article_number == @number_{i}, 'lawgraph_norm')"
        for i in range(len(numbers))
    )
    aql = f"""
    FOR doc IN (
        FOR hit IN search_articles
            SEARCH {clause}
            LIMIT @pool
            RETURN hit
    )
        SORT doc.props.inbound_citation_count DESC, doc.props.bwb_id ASC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            display_name: {_DEFAULT_NAME}
        }}
    """
    bind: dict[str, Any] = {f"number_{i}": n for i, n in enumerate(numbers)}
    bind.update(pool=_ARTICLE_POOL, limit=ALTERNATIVES + 1)
    rows = list(store.query(aql, bind))
    confidence = CONFIDENCE_ONE_LAW if len(rows) == 1 else CONFIDENCE_SEVERAL_LAWS
    return [_target(row, "article", confidence) for row in rows]


# ── dossiers and papers ───────────────────────────────────────────────────────


def _dossiers(store: ArangoStore, notation: Notation) -> list[dict[str, Any]]:
    """The dossiers with this number: the one with the suffix asked for first."""
    aql = f"""
    FOR doc IN {COLLECTION_DOSSIERS}
        FILTER doc.props.number == @number
        SORT doc.props.suffix ASC
        RETURN {{
            id: doc._id, key: doc._key,
            display_name: {_DEFAULT_NAME},
            suffix: doc.props.suffix
        }}
    """
    rows = list(store.query(aql, {"number": notation.dossier}))
    wanted = notation.suffix or ""
    return sorted(rows, key=lambda row: (row["suffix"] or "").upper() != wanted)


def _dossier_targets(
    rows: list[dict[str, Any]], notation: Notation, kind: str = "dossier"
) -> list[dict[str, Any]]:
    """The dossier asked for at citation confidence; other suffixes of its number below."""
    wanted = notation.suffix or ""
    exact = [r for r in rows if (r["suffix"] or "").upper() == wanted]
    others = [r for r in rows if r not in exact]
    return [_target(r, kind, CONFIDENCE_CITATION) for r in exact] + [
        _target(r, kind, CONFIDENCE_AMBIGUOUS) for r in others
    ]


def _dossier(store: ArangoStore, notation: Notation) -> list[dict[str, Any]]:
    return _dossier_targets(_dossiers(store, notation), notation)


def _document(store: ArangoStore, notation: Notation) -> list[dict[str, Any]]:
    """Paper *sequence* of a dossier, or the dossier when the graph has not that paper."""
    rows = _dossiers(store, notation)
    if not rows:
        return []
    wanted = notation.suffix or ""
    exact = [r for r in rows if (r["suffix"] or "").upper() == wanted]
    body = """
        // the tail of the documents query of a dossier: the paper with this number
        FOR document IN all_documents
            FILTER (@sequence != null AND document.props.sequence == @sequence)
                OR UPPER(document.props.number) == @text
            LIMIT @limit
            RETURN {
                id: document._id, key: document._key,
                display_name: NOT_NULL(document.props.display_name, document.props.title)
            }
    """
    sequence = notation.sequence or ""
    aql = f"FOR dossier_id IN @ids\n{_dossier_documents_aql(body)}"
    bind = {
        "ids": [r["id"] for r in exact or rows],
        "sequence": int(sequence) if sequence.isdigit() else None,
        "text": sequence,
        "limit": ALTERNATIVES + 1,
        "part_of": RELATION_PART_OF,
    }
    found = [
        _target(r, "document", CONFIDENCE_CITATION) for r in store.query(aql, bind)
    ]
    if found:
        return _capped(found)
    return [_target(r, "dossier", CONFIDENCE_PARTIAL) for r in exact or rows]


# ── the answer ────────────────────────────────────────────────────────────────


def _candidates(store: ArangoStore, q: str) -> tuple[list[dict[str, Any]], str | None]:
    """What the query may mean, and the qualifier (``derde lid``) of a citation."""
    parser = load_notation_parser(store)
    notation = parser.parse(q)
    if notation is None:
        return _laws_named(store, parser.law_matches(q)), None
    if notation.kind == "article":
        return _articles(store, notation), notation.qualifier
    if notation.kind == "dossier":
        return _dossier(store, notation), None
    if notation.kind == "document":
        return _document(store, notation), None
    return _identified(store, notation), None


def resolve(store: ArangoStore, q: str) -> dict[str, Any]:
    """The best match for *q* and up to ``ALTERNATIVES`` others, best first.

    ``kind`` and ``confidence`` are those of the match; ``qualifier`` is the ``lid`` or
    ``onder`` of an article citation. Nothing that fits is ``NO_MATCH``, not an error.
    """
    candidates, qualifier = _candidates(store, q)
    ordered = sorted(candidates, key=lambda c: -c["confidence"])  # stable
    if not ordered:
        return dict(NO_MATCH)
    best = ordered[0]
    return {
        "kind": best["kind"],
        "confidence": best["confidence"],
        "match": best,
        "alternatives": ordered[1 : ALTERNATIVES + 1],
        "qualifier": qualifier if best["kind"] == "article" else None,
    }
