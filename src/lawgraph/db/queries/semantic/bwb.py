"""The reads and updates of the semantic phase for BWB: the aliases and articles of the
instruments, the annexes, the amending versions and the Staatsblad and Staatscourant
publications a step resolves against them."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    RELATION_REFERS_TO,
    SOURCE_BWB,
    SOURCE_STAATSBLAD,
    SOURCE_STAATSCOURANT,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries._aql import sorted_merge
from lawgraph.db.queries.semantic import slim


def law_articles(store: Store, field: str, law_id: str) -> Iterator[dict[str, Any]]:
    """``{key, number, last_number, stub}`` of every article of one law; *field* is
    ``bwb_id`` or ``celex``. A historical article has only ``last_number``."""
    aql = f"""
FOR a IN {COLLECTION_ARTICLES}
  FILTER a.props.@field == @law_id
  RETURN {{
    key: a._key,
    number: a.props.article_number,
    last_number: a.props.last_article_number,
    stub: a.props.stub == true
  }}
"""
    return store.query(aql, {"field": field, "law_id": law_id})


# The abbreviations of the instruments: ``core.aliases.code_aliases`` reads them.
CODE_ALIAS_AQL = f"""
    FOR inst IN {COLLECTION_INSTRUMENTS}
        FILTER inst.props.bwb_id != null OR inst.props.celex != null
        RETURN {{
            short_title: inst.props.short_title,
            aliases: inst.props.aliases,
            bwb_id: inst.props.bwb_id,
            celex: inst.props.celex
        }}
    """


def code_alias_rows(store: Store) -> Iterator[dict[str, Any]]:
    """``{short_title, aliases, bwb_id, celex}`` of the instruments with a BWB id or a
    CELEX number."""
    return store.query(CODE_ALIAS_AQL)


def instrument_alias_rows(store: Store) -> Iterator[dict[str, Any]]:
    """``{bwb_id, celex, title, citation_title}`` of the instruments with a BWB id or a
    CELEX number."""
    aql = f"""
        FOR inst IN {COLLECTION_INSTRUMENTS}
            FILTER inst.props.bwb_id != null OR inst.props.celex != null
            RETURN {{
                bwb_id: inst.props.bwb_id,
                celex: inst.props.celex,
                title: inst.props.title,
                citation_title: inst.props.citation_title
            }}
        """
    return store.query(aql)


_BASIS_AQL = f"""
FOR regulation IN {COLLECTION_INSTRUMENTS}
  FILTER regulation.props.source == @source
  FILTER LENGTH(regulation.props.basis) > 0
  RETURN {{
    key: regulation._key,
    bwb_id: regulation.props.bwb_id,
    basis: regulation.props.basis
  }}
"""


def regulations_with_basis(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, bwb_id, basis}`` of the BWB regulations that state a legal basis."""
    return store.query(_BASIS_AQL, {"source": SOURCE_BWB})


def instrument_keys_by_bwb_id(
    store: Store, bwb_ids: list[str]
) -> Iterator[dict[str, Any]]:
    """``{_key, props: {bwb_id}}`` of the instruments with these *bwb_ids*."""
    batch_aql = f"""
FOR inst IN {COLLECTION_INSTRUMENTS}
  FILTER inst.props.bwb_id IN @bwb_ids
  RETURN {{_key: inst._key, props: {{bwb_id: inst.props.bwb_id}}}}
"""
    bind = {"bwb_ids": bwb_ids}
    return store.query(batch_aql, bind)


def instrument_ids_by_bwb_id(store: Store, bwb_ids: list[str]) -> Iterator[Any]:
    """``{bwb_id, inst_id, inst_key}`` of the instruments with these *bwb_ids*."""
    inst_aql = f"""
FOR inst IN {COLLECTION_INSTRUMENTS}
  FILTER inst.props.bwb_id IN @bwb_ids
  RETURN {{ bwb_id: inst.props.bwb_id, inst_id: inst._id, inst_key: inst._key }}
"""
    return store.query(inst_aql, {"bwb_ids": bwb_ids})


def article_bwb_ids(store: Store) -> Iterator[Any]:
    """Every distinct BWB id that has article nodes in the graph."""
    aql = f"""
        FOR doc IN {COLLECTION_ARTICLES}
            FILTER doc.props.bwb_id != null
            RETURN DISTINCT doc.props.bwb_id
        """
    return store.query(aql)


def articles_with_references(
    store: Store, bwb_ids: list[str]
) -> Iterator[dict[str, Any]]:
    """The articles of *bwb_ids* that carry structured references."""
    aql = f"""
        FOR doc IN {COLLECTION_ARTICLES}
            FILTER doc.props.bwb_id IN @bwb_ids
            FILTER doc.props.references != null
        RETURN {slim("doc", "bwb_id", "article_number", "references")}
        """
    return store.query(aql, bind_vars={"bwb_ids": bwb_ids})


def annex_keys(store: Store) -> Iterator[Any]:
    """The key of every annex."""
    return store.query(f"FOR a IN {COLLECTION_ANNEXES} RETURN a._key")


def titled_annexes(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, bwb_id, label, title}`` of every annex with a title, by key."""
    aql = f"""
        FOR annex IN {COLLECTION_ANNEXES}
            FILTER annex.props.title != null AND annex.props.bwb_id != null
            SORT annex._key
            RETURN {{
                key: annex._key,
                bwb_id: annex.props.bwb_id,
                label: annex.props.label,
                title: annex.props.title
            }}
        """
    return store.query(aql)


def articles_naming_annexes(
    store: Store, names: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """Per ``{key, bwb_id, name}`` of *names*: the articles of that regulation whose text
    contains the name, as ``{annex, article}``."""
    aql = f"""
        FOR n IN @names
            FOR doc IN {COLLECTION_ARTICLES}
                FILTER doc.props.bwb_id == n.bwb_id AND doc.props.bwb_id != null
                FILTER doc.props.text != null AND CONTAINS(doc.props.text, n.name)
                RETURN {{
                    annex: n.key,
                    article: {slim("doc", "bwb_id", "text", "article_number")}
                }}
        """
    return store.query(aql, {"names": names})


def articles_mentioning_annex(store: Store) -> Iterator[dict[str, Any]]:
    """The articles whose text contains the word "bijlage"."""
    aql = f"""
        FOR doc IN {COLLECTION_ARTICLES}
            FILTER doc.props.text != null
            FILTER CONTAINS(LOWER(doc.props.text), 'bijlage')
            RETURN {slim("doc", "bwb_id", "text")}
        """
    return store.query(aql)


# Sorted by article identity so that all versions of one article end up in the
# same chunk (needed to keep the earliest effective date per publication).
_AMENDING_VERSIONS_AQL = f"""
FOR v IN {COLLECTION_ARTICLE_VERSIONS}
  FILTER v.props.origin_publication != null AND v.props.stam_id != null
  SORT v.props.bwb_id, v.props.stam_id, v._key
  RETURN {{
    key: v._key,
    bwb_id: v.props.bwb_id,
    stam_id: v.props.stam_id,
    effect: v.props.effect,
    valid_from: v.props.valid_from,
    source_publication: v.props.source_publication,
    origin: v.props.origin_publication,
    commencement: v.props.commencement_publication
  }}
"""


# One row per stored article; matched to the wanted (bwb_id, stam_id) pairs in Python.
_ARTICLES_BY_IDENTITY_AQL = f"""
FOR a IN {COLLECTION_ARTICLES}
  FILTER a.props.bwb_id IN @bwb_ids AND a.props.stam_id IN @stam_ids
  RETURN {{key: a._key, bwb_id: a.props.bwb_id, stam_id: a.props.stam_id}}
"""


_REGULATION_DOSSIERS_AQL = f"""
FOR i IN {COLLECTION_INSTRUMENTS}
  FILTER i.props.bwb_id != null
  SORT i._key
  RETURN {{
    key: i._key,
    dossiers: IS_ARRAY(i.props.dossier_numbers) ? i.props.dossier_numbers : []
  }}
"""


def amending_article_versions(store: Store) -> Iterator[dict[str, Any]]:
    """The article versions that name the publication they came from, sorted by article
    identity."""
    return store.query(_AMENDING_VERSIONS_AQL)


def articles_by_identity(
    store: Store, bwb_ids: list[str], stam_ids: list[str]
) -> Iterator[dict[str, Any]]:
    """``{key, bwb_id, stam_id}`` of the articles with a BWB id in *bwb_ids* and a stam id in
    *stam_ids*: every combination, not only the wanted pairs."""
    return store.query(
        _ARTICLES_BY_IDENTITY_AQL, {"bwb_ids": bwb_ids, "stam_ids": stam_ids}
    )


def regulation_dossier_numbers(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, dossiers}`` of every BWB regulation, with the parliamentary dossiers it
    lists (none too: its edges to dossiers it no longer lists go)."""
    return store.query(_REGULATION_DOSSIERS_AQL)


def articles_with_classifiable_edges(store: Store) -> Iterator[dict[str, Any]]:
    """Articles with their classifiable outgoing reference edges.

    Grouped per article so each article text crosses the wire once.
    """
    aql = f"""
        FOR art IN {COLLECTION_ARTICLES}
            FILTER art.props.text != null
            LET es = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._from == art._id
                    FILTER e.relation == @relation
                    RETURN {{ key: e._key, start: e.meta.start, end: e.meta.end }}
            )
            FILTER LENGTH(es) > 0
            RETURN {{ text: art.props.text, edges: es }}
        """
    return store.query(aql, {"relation": RELATION_REFERS_TO})


def update_edge_classifications(
    store: Store, batch: list[dict[str, Any]], now: str | None
) -> int:
    """Write the classifications of *batch* that differ from the stored ones; how many.

    ``updated_at`` says when a classification changed. Set on every run it made every
    edge differ from itself: 330,000 edges written again each time.
    """
    aql = f"""
        FOR u IN @updates
            LET stored = DOCUMENT({COLLECTION_EDGES}, u.key)
            FILTER stored != null
            FILTER stored.semantic_type != u.semantic_type
                OR stored.explanation != u.explanation
                OR stored.meta.semantic_pattern != u.pattern
                OR stored.meta.semantic_confidence != u.semantic_confidence
            UPDATE u.key WITH {{
                semantic_type: u.semantic_type,
                explanation: u.explanation,
                updated_at: @now,
                meta: {
        sorted_merge(
            "stored.meta",
            "{semantic_pattern: u.pattern, semantic_confidence: u.semantic_confidence}",
        )
    }
            }} IN {COLLECTION_EDGES} OPTIONS {{ mergeObjects: false }}
            RETURN 1
        """
    bind = {"updates": batch, "now": now}
    return len(list(store.query(aql, bind)))


# Strategy 1: publications with explicit bwb_id stored during normalization
_STAATSBLAD_BY_BWB_ID_AQL = f"""
FOR pub IN {COLLECTION_DOCUMENTS}
  FILTER pub.props.source == @source
  FILTER pub.props.text != null AND LENGTH(pub.props.text) > 50
  FILTER pub.props.bwb_id != null
  LET inst = (
    FOR i IN {COLLECTION_INSTRUMENTS}
      // != null lets the sparse index on props.bwb_id serve the join (else: a full scan)
      FILTER i.props.bwb_id != null AND i.props.bwb_id == pub.props.bwb_id
      SORT i._key
      LIMIT 1
      RETURN i
  )[0]
  FILTER inst != null
  RETURN {{ pub_id: pub._id, pub_key: pub._key, inst_id: inst._id, inst_key: inst._key,
           match_type: 'bwb_id' }}
"""


# Strategy 2: title matching for publications without bwb_id
_STAATSBLAD_BY_TITLE_AQL = f"""
FOR pub IN {COLLECTION_DOCUMENTS}
  FILTER pub.props.source == @source
  FILTER pub.props.text != null AND LENGTH(pub.props.text) > 50
  FILTER pub.props.bwb_id == null
  LET inst = (
    FOR i IN {COLLECTION_INSTRUMENTS}
      FILTER i.props.citation_title != null
      FILTER CONTAINS(LOWER(pub.props.title), LOWER(i.props.citation_title))
      // the longest title the publication names wins (the key settles a tie)
      SORT LENGTH(i.props.citation_title) DESC, i._key
      LIMIT 1
      RETURN i
  )[0]
  FILTER inst != null
  RETURN {{ pub_id: pub._id, pub_key: pub._key, inst_id: inst._id, inst_key: inst._key,
           match_type: 'title' }}
"""


def staatsblad_instrument_matches(store: Store) -> list[dict[str, Any]]:
    """``{pub_id, pub_key, inst_id, inst_key, match_type}`` per Staatsblad publication and
    the instrument it explains: by its BWB id, then by title for those without one."""
    bind_vars = {"source": SOURCE_STAATSBLAD}
    rows: list[dict[str, Any]] = []
    rows.extend(store.query(_STAATSBLAD_BY_BWB_ID_AQL, bind_vars=bind_vars))
    rows.extend(store.query(_STAATSBLAD_BY_TITLE_AQL, bind_vars=bind_vars))
    return rows


def staatscourant_instrument_matches(
    store: Store, since_date: str | None
) -> list[dict[str, Any]]:
    """``{pub_id, pub_key, inst_id, inst_key, match_type}`` per Staatscourant regulation and
    the instrument it explains: by its BWB id, then by title for those without one. With
    *since_date* only the publications of that date or later."""
    since_filter = "FILTER pub.props.date >= @since_iso" if since_date else ""

    # Strategy 1: explicit bwb_id stored during normalization
    aql_bwb = f"""
FOR pub IN {COLLECTION_DOCUMENTS}
  FILTER pub.props.source == @source
  FILTER pub.props.bwb_id != null
  {since_filter}
  LET inst = FIRST(
    FOR i IN {COLLECTION_INSTRUMENTS}
      // != null lets the sparse index on props.bwb_id serve the join (else: a full scan)
      FILTER i.props.bwb_id != null AND i.props.bwb_id == pub.props.bwb_id
      SORT i._key
      LIMIT 1
      RETURN i
  )
  FILTER inst != null
  RETURN {{
    pub_id: pub._id, pub_key: pub._key,
    inst_id: inst._id, inst_key: inst._key,
    match_type: 'bwb_id'
  }}
"""

    # Strategy 2: title match against citation_title
    aql_title = f"""
FOR pub IN {COLLECTION_DOCUMENTS}
  FILTER pub.props.source == @source
  FILTER pub.props.bwb_id == null
  FILTER pub.props.title != null AND LENGTH(pub.props.title) > 5
  {since_filter}
  LET inst = FIRST(
    FOR i IN {COLLECTION_INSTRUMENTS}
      FILTER i.props.citation_title != null AND LENGTH(i.props.citation_title) > 5
      FILTER CONTAINS(LOWER(pub.props.title), LOWER(i.props.citation_title))
      // the longest title the publication names wins (the key settles a tie)
      SORT LENGTH(i.props.citation_title) DESC, i._key
      LIMIT 1
      RETURN i
  )
  FILTER inst != null
  RETURN {{
    pub_id: pub._id, pub_key: pub._key,
    inst_id: inst._id, inst_key: inst._key,
    match_type: 'title'
  }}
"""

    bind: dict[str, Any] = {"source": SOURCE_STAATSCOURANT}
    if since_date:
        bind["since_iso"] = since_date
    rows: list[dict[str, Any]] = []
    for aql in (aql_bwb, aql_title):
        rows.extend(store.query(aql, bind_vars=bind))
    return rows


def staatscourant_texts(store: Store, since_date: str | None) -> Iterator[Any]:
    """``{pub_id, pub_key, text}`` of the Staatscourant publications with a text, of
    *since_date* or later when it is given."""
    since_filter = "FILTER pub.props.date >= @since_iso" if since_date else ""
    aql = f"""
FOR pub IN {COLLECTION_DOCUMENTS}
  FILTER pub.props.source == @source
  FILTER pub.props.text != null AND LENGTH(pub.props.text) > 100
  {since_filter}
  RETURN {{ pub_id: pub._id, pub_key: pub._key, text: pub.props.text }}
"""
    bind: dict[str, Any] = {"source": SOURCE_STAATSCOURANT}
    if since_date:
        bind["since_iso"] = since_date
    return store.query(aql, bind)
