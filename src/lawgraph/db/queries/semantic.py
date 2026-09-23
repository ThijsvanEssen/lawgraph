"""The reads and updates of the semantic phase: the nodes a semantic step scans for what they
name (judgments, articles, papers, publications), the lookups that resolve what was found, and
the updates a step makes in place. ``slim`` projects a node onto the props a step reads."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    EXPLANATORY_KIND_MARKER,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_REPEALS,
    SEMANTIC_SOURCE_STRUCTURED,
    SOURCE_BWB,
    SOURCE_ECHR,
    SOURCE_EERSTEKAMER,
    SOURCE_RECHTSPRAAK,
    SOURCE_STAATSBLAD,
    SOURCE_STAATSCOURANT,
)
from lawgraph.db.counting import Store


def slim(var: str, *fields: str) -> str:
    """AQL for the document *var* with only *fields* of its props.

    A judgment carries its XML, its text and its paragraphs, a TK document the whole API
    payload; a pipeline that reads one of them must not have the rest sent over. The result
    has the shape of a document, so ``Node.from_document`` reads it.
    """
    names = ", ".join(f'"{field}"' for field in fields)
    return (
        f"{{_key: {var}._key, type: {var}.type, labels: {var}.labels, "
        f"props: KEEP({var}.props, {names})}}"
    )


_CHANGE_RELATIONS = (RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS)

# ── judgments ────────────────────────────────────────────────────────────────


def judgment_paragraphs(
    store: Store, *, eclis: list[str] | None, batch_size: int
) -> Iterator[dict[str, Any]]:
    """``{ecli, paragraphs}`` (as a slim document) of every Rechtspraak judgment, only those
    of *eclis* when it is given."""
    bind: dict[str, Any] = {"source": SOURCE_RECHTSPRAAK}
    recent = ""
    if eclis is not None:
        bind["eclis"] = eclis
        recent = "FILTER j.props.ecli IN @eclis"
    aql = f"""
        FOR j IN {COLLECTION_JUDGMENTS}
            FILTER j.props.source == @source
            {recent}
            RETURN {slim("j", "ecli", "paragraphs")}
        """
    return store.query(aql, bind, batch_size=batch_size)


def count_rechtspraak_judgments(store: Store) -> int | None:
    """How many Rechtspraak judgments the graph holds, from the index."""
    count_aql = f"""
            FOR j IN {COLLECTION_JUDGMENTS}
                FILTER j.props.source == @source
                COLLECT WITH COUNT INTO n
                RETURN n
            """
    count = next(iter(store.query(count_aql, {"source": SOURCE_RECHTSPRAAK})), None)
    return count if isinstance(count, int) else None


def judgment_ids_by_ecli(store: Store, eclis: list[str]) -> Iterator[dict[str, Any]]:
    """``{ecli, id}`` of the judgments with these *eclis*."""
    aql = f"""
        FOR doc IN {COLLECTION_JUDGMENTS}
            FILTER doc.props.ecli IN @eclis
            RETURN {{ ecli: doc.props.ecli, id: doc._id }}
        """
    return store.query(aql, bind_vars={"eclis": eclis})


def judgments_with_related_eclis(store: Store) -> Iterator[dict[str, Any]]:
    """``{j_id, procedure_type, related_eclis}`` of every judgment that names an earlier
    one."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.related_eclis != null
  FILTER LENGTH(j.props.related_eclis) > 0
  RETURN {{
    j_id: j._id,
    procedure_type: j.props.judgment_metadata.type,
    related_eclis: j.props.related_eclis,
  }}
"""
    return store.query(aql)


def echr_judgments(store: Store) -> Iterator[dict[str, Any]]:
    """``{j_id, j_key, articles, conclusion}`` of the ECHR judgments that cite an article
    or have a conclusion."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.source == @source
  FILTER j.props.articles != null OR j.props.conclusion != null
  RETURN {{
    j_id: j._id,
    j_key: j._key,
    articles: j.props.articles,
    conclusion: j.props.conclusion
  }}
"""
    return store.query(aql, {"source": SOURCE_ECHR})


# ── instruments ──────────────────────────────────────────────────────────────


def code_alias_rows(store: Store) -> Iterator[dict[str, Any]]:
    """``{short_title, bwb_id, celex}`` of the instruments with a short title."""
    aql = f"""
        FOR inst IN {COLLECTION_INSTRUMENTS}
            FILTER inst.props.short_title != null
            FILTER inst.props.bwb_id != null OR inst.props.celex != null
            RETURN {{
                short_title: inst.props.short_title,
                bwb_id: inst.props.bwb_id,
                celex: inst.props.celex
            }}
        """
    return store.query(aql)


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


def celex_references(store: Store) -> Iterator[list[Any]]:
    """``[bwb_id, celex_refs]`` of the BWB regulations that name an EU act."""
    aql = f"""
        FOR regulation IN {COLLECTION_INSTRUMENTS}
            FILTER regulation.props.source == @source
            FILTER LENGTH(regulation.props.celex_refs) > 0
            RETURN [regulation.props.bwb_id, regulation.props.celex_refs]
        """
    return store.query(aql, {"source": SOURCE_BWB})


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


# ── BWB articles and their versions ──────────────────────────────────────────


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
  SORT v.props.bwb_id, v.props.stam_id
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
  FILTER i.props.bwb_id != null AND IS_ARRAY(i.props.dossier_numbers)
  FILTER LENGTH(i.props.dossier_numbers) > 0
  RETURN {{key: i._key, dossiers: i.props.dossier_numbers}}
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
    """``{key, dossiers}`` of the BWB regulations that list parliamentary dossiers."""
    return store.query(_REGULATION_DOSSIERS_AQL)


def articles_with_classifiable_edges(store: Store) -> Iterator[dict[str, Any]]:
    """Articles with their classifiable outgoing reference edges.

    Grouped per article so each article text crosses the wire once.
    Excludes expert/community-curated edges.
    """
    aql = f"""
        FOR art IN {COLLECTION_ARTICLES}
            FILTER art.props.text != null
            LET es = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._from == art._id
                    FILTER e.relation == @relation
                    FILTER e.semantic_source == null
                        OR e.semantic_source == @structured
                    RETURN {{ key: e._key, start: e.meta.start, end: e.meta.end }}
            )
            FILTER LENGTH(es) > 0
            RETURN {{ text: art.props.text, edges: es }}
        """
    return store.query(
        aql,
        {
            "relation": RELATION_REFERS_TO,
            "structured": SEMANTIC_SOURCE_STRUCTURED,
        },
    )


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
                OR stored.semantic_source != @structured
                OR stored.explanation != u.explanation
                OR stored.meta.semantic_pattern != u.pattern
                OR stored.meta.semantic_confidence != u.semantic_confidence
            UPDATE u.key WITH {{
                semantic_type: u.semantic_type,
                semantic_source: @structured,
                explanation: u.explanation,
                expert_badge: false,
                updated_at: @now,
                meta: {{
                    semantic_pattern: u.pattern,
                    semantic_confidence: u.semantic_confidence
                }}
            }} IN {COLLECTION_EDGES} OPTIONS {{ mergeObjects: true }}
            RETURN 1
        """
    bind = {
        "updates": batch,
        "structured": SEMANTIC_SOURCE_STRUCTURED,
        "now": now,
    }
    return len(list(store.query(aql, bind)))


# ── EU articles ──────────────────────────────────────────────────────────────


def eu_articles_of(store: Store, celex_list: list[str]) -> Iterator[dict[str, Any]]:
    """The articles of the EU acts in *celex_list*, with their text."""
    aql = f"""
            FOR doc IN {COLLECTION_ARTICLES}
                FILTER doc.props.celex IN @celex_list
                RETURN {slim("doc", "celex", "article_number", "text", "display_name")}
            """
    return store.query(aql, bind_vars={"celex_list": celex_list})


def eu_articles(store: Store) -> Iterator[dict[str, Any]]:
    """The articles of every EU act, with their text."""
    aql = f"""
            FOR doc IN {COLLECTION_ARTICLES}
                FILTER doc.props.celex != null
                RETURN {slim("doc", "celex", "article_number", "text", "display_name")}
            """
    return store.query(aql)


# ── publications ─────────────────────────────────────────────────────────────

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


# ── parliamentary papers ─────────────────────────────────────────────────────


def tk_documents(store: Store, ids: list[str] | None) -> Iterator[dict[str, Any]]:
    """The whole Tweede Kamer documents, only those with an external id in *ids* when it is
    given: ``semantic tk`` scans every text prop of a paper and its API payload."""
    bind_vars: dict[str, Any] | None = None
    id_filter = ""
    if ids is not None:
        id_filter = "    FILTER doc.props.external_id IN @ids\n"
        bind_vars = {"ids": ids}

    aql = (
        f"FOR doc IN {COLLECTION_DOCUMENTS}\n"
        '    FILTER "TK" IN doc.labels\n'
        f"{id_filter}"
        "    RETURN doc"
    )
    return store.query(aql, bind_vars=bind_vars)


def tk_document_titles(
    store: Store, since_date: str | None
) -> Iterator[dict[str, Any]]:
    """The Tweede Kamer documents with their title, those of *since_date* or later when it is
    given."""
    since_filter = ""
    bind_vars: dict[str, Any] | None = None
    if since_date is not None:
        since_filter = "FILTER doc.props.date >= @since"
        bind_vars = {"since": since_date}

    aql = (
        f"FOR doc IN {COLLECTION_DOCUMENTS}\n"
        '    FILTER "TK" IN doc.labels\n'
        f"    {since_filter}\n"
        f"    RETURN {slim('doc', 'title', 'display_name')}"
    )
    return store.query(aql, bind_vars)


def tk_documents_to_scan_for_amendments(
    store: Store, amending: list[str]
) -> Iterator[dict[str, Any]]:
    """The Tweede Kamer documents with a text and a law to amend: their own ``bwb_id``, or
    their id in *amending*."""
    aql = f"""
        FOR doc IN {COLLECTION_DOCUMENTS}
            FILTER "TK" IN doc.labels
            FILTER doc.props.text != null AND doc.props.text != ""
            FILTER doc.props.bwb_id != null OR doc._id IN @amending
            RETURN {slim("doc", "bwb_id", "text")}
        """
    return store.query(aql, {"amending": amending})


def amended_instruments(store: Store) -> Iterator[dict[str, Any]]:
    """``{document_id, bwb_id}`` per AMENDS edge from a document to an instrument with a BWB
    id."""
    aql = f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == @relation
            FILTER STARTS_WITH(e._from, "{COLLECTION_DOCUMENTS}/")
            FILTER STARTS_WITH(e._to, "{COLLECTION_INSTRUMENTS}/")
            LET inst = DOCUMENT(e._to)
            FILTER inst != null AND inst.props.bwb_id != null
            RETURN {{ document_id: e._from, bwb_id: inst.props.bwb_id }}
        """
    return store.query(aql, {"relation": RELATION_AMENDS})


def ek_papers_in_tk_dossiers(store: Store) -> Iterator[dict[str, Any]]:
    """``{document_key, dossier_key, dossier_number, dossier_suffix}`` of the Eerste Kamer
    papers whose dossier number is a Tweede Kamer dossier in the graph."""
    aql = f"""
FOR document IN {COLLECTION_DOCUMENTS}
  FILTER document.props.source == @source
  FILTER document.props.dossier_number != null
  LET dossier = FIRST(
    FOR d IN {COLLECTION_DOSSIERS}
      FILTER d.props.number == TO_STRING(document.props.dossier_number)
      FILTER (d.props.suffix || "") == (document.props.dossier_suffix || "")
      LIMIT 1
      RETURN d
  )
  FILTER dossier != null
  RETURN {{
    document_key: document._key,
    dossier_key: dossier._key,
    dossier_number: document.props.dossier_number,
    dossier_suffix: document.props.dossier_suffix
  }}
"""
    return store.query(aql, {"source": SOURCE_EERSTEKAMER})


# One pass: per explanatory document, the nodes it explains.
#
# Those are the article versions (or articles, or the instrument itself) that
# the instrument legislated in the document's dossier introduced or changed.
MEMORANDUM_TARGETS_AQL = f"""
FOR doc IN {COLLECTION_DOCUMENTS}
  FILTER CONTAINS(LOWER(doc.props.kind || ''), '{EXPLANATORY_KIND_MARKER}')
  LET paper_dossiers = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._from == doc._id AND e.relation == @part_of
      FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
      RETURN e._to
  )
  LET legislated = (
    FOR dossier IN paper_dossiers
      FOR e IN {COLLECTION_EDGES}
        FILTER e._to == dossier AND e.relation == @legislated_in
        FILTER STARTS_WITH(e._from, '{COLLECTION_INSTRUMENTS}/')
        RETURN DISTINCT e._from
  )
  FILTER LENGTH(legislated) > 0
  LET upgraded = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._from == doc._id AND e.relation == @explains AND e.source == @sections_source
      RETURN e._to
  )
  LET changed = (
    FOR instrument IN legislated
      FOR e IN {COLLECTION_EDGES}
        FILTER e._from == instrument AND e.relation IN @change_relations
        FILTER STARTS_WITH(e._to, '{COLLECTION_ARTICLES}/')
        RETURN DISTINCT e.meta.article_version == null
          ? e._to
          : CONCAT('{COLLECTION_ARTICLE_VERSIONS}/', e.meta.article_version)
  )
  RETURN {{
    document: doc._id,
    targets: MINUS(LENGTH(changed) > 0 ? changed : legislated, upgraded)
  }}
"""


def memorandum_targets(store: Store, *, sections_source: str) -> Iterator[Any]:
    """``{document, targets}`` per explanatory memorandum: what the instrument legislated in
    its dossier changed, less what an edge of *sections_source* already explains."""
    bind_vars: dict[str, Any] = {
        "part_of": RELATION_PART_OF,
        "legislated_in": RELATION_LEGISLATED_IN,
        "explains": RELATION_EXPLAINS,
        "sections_source": sections_source,
        "change_relations": list(_CHANGE_RELATIONS),
    }
    return store.query(MEMORANDUM_TARGETS_AQL, bind_vars)


# One pass: per memorandum with sections, what its dossier legislated and changed.
#
# A budget paper explains policy articles and a paper without article headings has no sections
# to read; a dossier that legislated nothing has nothing to link to.
_MEMORANDA_WITH_SECTIONS_AQL = f"""
FOR doc IN {COLLECTION_DOCUMENTS}
  FILTER CONTAINS(LOWER(doc.props.kind || ''), '{EXPLANATORY_KIND_MARKER}')
  FILTER doc.props.budget != true
  FILTER doc.props.structure_quality IN @qualities
  FILTER doc.props.text != null
  LET paper_dossiers = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._from == doc._id AND e.relation == @part_of
      FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
      RETURN e._to
  )
  LET legislated = (
    FOR dossier IN paper_dossiers
      FOR e IN {COLLECTION_EDGES}
        FILTER e._to == dossier AND e.relation == @legislated_in
        FILTER STARTS_WITH(e._from, '{COLLECTION_INSTRUMENTS}/')
        RETURN DISTINCT e._from
  )
  FILTER LENGTH(legislated) > 0
  LET own = (
    FOR instrument IN legislated
      LET bwb_id = DOCUMENT(instrument).props.bwb_id
      FILTER bwb_id != null
      RETURN bwb_id
  )
  LET changes = (
    FOR instrument IN legislated
      FOR e IN {COLLECTION_EDGES}
        FILTER e._from == instrument AND e.relation IN @change_relations
        FILTER STARTS_WITH(e._to, '{COLLECTION_ARTICLES}/')
        LET article = DOCUMENT(e._to)
        FILTER article.props.bwb_id != null AND article.props.article_number != null
        RETURN DISTINCT {{
          bwb_id: article.props.bwb_id,
          number: article.props.article_number,
          article: e._to,
          version: e.meta.article_version,
          relation: e.relation
        }}
  )
  LET wanted = UNIQUE(APPEND(own, changes[*].bwb_id))
  LET laws = (
    FOR law IN {COLLECTION_INSTRUMENTS}
      FILTER law.props.bwb_id != null AND law.props.bwb_id IN wanted
      RETURN {{
        bwb_id: law.props.bwb_id,
        names: [law.props.title, law.props.citation_title],
        codes: [law.props.short_title]
      }}
  )
  RETURN {{
    document: doc._id,
    text: doc.props.text,
    sections: doc.props.sections,
    own: own,
    changes: changes,
    laws: laws
  }}
"""


def memoranda_with_sections(
    store: Store, *, qualities: list[str], batch_size: int
) -> Iterator[dict[str, Any]]:
    """Per memorandum of a structure quality in *qualities*: its text and sections, the
    laws its dossier legislated (``own``), the articles they changed and the names of the
    laws involved."""
    bind_vars: dict[str, Any] = {
        "qualities": qualities,
        "part_of": RELATION_PART_OF,
        "legislated_in": RELATION_LEGISLATED_IN,
        "change_relations": list(_CHANGE_RELATIONS),
    }
    return store.query(_MEMORANDA_WITH_SECTIONS_AQL, bind_vars, batch_size=batch_size)
