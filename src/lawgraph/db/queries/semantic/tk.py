"""The reads of the semantic phase for the Tweede and Eerste Kamer: the papers a step scans,
the memoranda and their targets, and the signals of how a dossier ended."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    EXPLANATORY_KIND_MARKER,
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REPEALS,
    RELATION_SECOND_READING_OF,
    SOURCE_EERSTEKAMER,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries.semantic import slim

_CHANGE_RELATIONS = (RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS)


def second_reading_memoranda(store: Store) -> Iterator[dict[str, Any]]:
    """``{labels, text}`` of the explanatory memoranda that speak of a first reading, with
    the labels of their dossiers: a change in the Grondwet in its second reading refers to
    the papers of the first (``core.dossier_numbers.first_reading_dossiers``)."""
    aql = f"""
    FOR doc IN {COLLECTION_DOCUMENTS}
        FILTER "TK" IN doc.labels AND doc.props.text != null
        FILTER CONTAINS(LOWER(doc.props.kind || ""), @explanatory)
        FILTER CONTAINS(LOWER(doc.props.text), "eerste lezing")
        RETURN {{
            labels: (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._from == doc._id AND e.relation == @part_of
                    FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
                    RETURN DOCUMENT(e._to).props.label
            ),
            text: doc.props.text
        }}
    """
    return store.query(
        aql, {"explanatory": EXPLANATORY_KIND_MARKER, "part_of": RELATION_PART_OF}
    )


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
    """The Tweede Kamer documents with their kind, their title and, of a paper named by its own
    subject, the title of its dossier; those of *since_date* or later when it is given."""
    since_filter = ""
    bind_vars: dict[str, Any] | None = None
    if since_date is not None:
        since_filter = "FILTER doc.props.date >= @since"
        bind_vars = {"since": since_date}

    aql = (
        f"FOR doc IN {COLLECTION_DOCUMENTS}\n"
        '    FILTER "TK" IN doc.labels\n'
        f"    {since_filter}\n"
        f"    RETURN {slim('doc', 'kind', 'title', 'dossier_title', 'display_name')}"
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
  LET own_dossiers = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._from == doc._id AND e.relation == @part_of
      FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
      RETURN e._to
  )
  // a first reading explains what its second reading made law
  LET paper_dossiers = UNION_DISTINCT(own_dossiers, (
    FOR dossier IN own_dossiers
      FOR e IN {COLLECTION_EDGES}
        FILTER e._to == dossier AND e.relation == @second_reading_of
        RETURN e._from
  ))
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
    its dossier (or in the second reading of its dossier) changed, less what an edge of
    *sections_source* already explains."""
    bind_vars: dict[str, Any] = {
        "part_of": RELATION_PART_OF,
        "legislated_in": RELATION_LEGISLATED_IN,
        "second_reading_of": RELATION_SECOND_READING_OF,
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
  LET own_dossiers = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._from == doc._id AND e.relation == @part_of
      FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
      RETURN e._to
  )
  // a first reading explains what its second reading made law
  LET paper_dossiers = UNION_DISTINCT(own_dossiers, (
    FOR dossier IN own_dossiers
      FOR e IN {COLLECTION_EDGES}
        FILTER e._to == dossier AND e.relation == @second_reading_of
        RETURN e._from
  ))
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
    laws involved. The dossier of a first reading of a change in the Grondwet counts with
    the dossier of its second reading, in which the change was made law."""
    bind_vars: dict[str, Any] = {
        "qualities": qualities,
        "part_of": RELATION_PART_OF,
        "legislated_in": RELATION_LEGISLATED_IN,
        "second_reading_of": RELATION_SECOND_READING_OF,
        "change_relations": list(_CHANGE_RELATIONS),
    }
    return store.query(_MEMORANDA_WITH_SECTIONS_AQL, bind_vars, batch_size=batch_size)


def dossier_ids(store: Store) -> Iterator[str]:
    """The ``_id`` of every dossier."""
    return store.query(f"FOR dossier IN {COLLECTION_DOSSIERS} RETURN dossier._id")


# Per dossier what says how it ended: the instruments legislated in it, the letters on it
# that may withdraw its bill, and the votes on the bill itself; and what it holds now. A
# letter is a document of the dossier, directly or through a case, whose kind is a letter
# and whose subject names a withdrawal; which of them withdraw is decided by the caller.
_DOSSIER_OUTCOME_SIGNALS_AQL = f"""
FOR dossier_id IN @dossier_ids
  LET dossier = DOCUMENT(dossier_id)
  FILTER dossier != null
  LET publications = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._to == dossier_id AND e.relation == @legislated_in
      FILTER STARTS_WITH(e._from, '{COLLECTION_INSTRUMENTS}/')
      LET instrument = DOCUMENT(e._from)
      FILTER instrument != null
      RETURN {{
        date_published: instrument.props.date_published,
        date_signed: instrument.props.date_signed
      }}
  )
  LET bill_decisions = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._to == dossier_id AND e.relation == @about
      FILTER STARTS_WITH(e._from, '{COLLECTION_DECISIONS}/')
      LET decision = DOCUMENT(e._from)
      FILTER decision != null
      FILTER decision.props.primary_case_kind IN @bill_case_kinds
      RETURN KEEP(
        decision.props, "date", "passed", "decision_kind", "decision_text"
      )
  )
  LET ek_votes = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._to == dossier_id AND e.relation == @about
      FILTER STARTS_WITH(e._from, '{COLLECTION_DECISIONS}/')
      LET decision = DOCUMENT(e._from)
      FILTER decision != null AND decision.props.chamber == "EK"
      RETURN MERGE(
        {{ id: decision._id }},
        KEEP(
          decision.props, "date", "result", "method", "source_url", "retrieved_on",
          "bill_decision", "kind"
        )
      )
  )
  RETURN {{
    key: dossier._key,
    props: KEEP(
      dossier.props, "closed", "closed_on", "outcome", "tk_decision", "ek_outcome",
      "ek_rejected", "kind"
    ),
    publications: publications,
    bill_decisions: bill_decisions,
    ek_votes: ek_votes
  }}
"""


def dossier_outcome_signals(
    store: Store, dossier_ids: list[str], *, bill_case_kinds: list[str]
) -> Iterator[dict[str, Any]]:
    """``{key, props, publications, bill_decisions, ek_votes}`` per dossier of
    *dossier_ids*: the instruments ``LEGISLATED_IN`` it, the decisions on a case of one of
    *bill_case_kinds*, the votes of the Eerste Kamer about it, and the outcome props it
    holds now."""
    bind_vars: dict[str, Any] = {
        "dossier_ids": dossier_ids,
        "legislated_in": RELATION_LEGISLATED_IN,
        "about": RELATION_ABOUT,
        "bill_case_kinds": bill_case_kinds,
    }
    return store.query(_DOSSIER_OUTCOME_SIGNALS_AQL, bind_vars)


def dossier_refs(store: Store) -> Iterator[dict[str, Any]]:
    """``{label, number, suffix, title}`` of every dossier: what the relation rules read."""
    return store.query(
        f"""
        FOR dossier IN {COLLECTION_DOSSIERS}
            RETURN KEEP(dossier.props, "label", "number", "suffix", "title")
        """
    )


def related_cases(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, kind, dossier_numbers, related_cases}`` of every case the Kamer relates to
    another."""
    return store.query(
        f"""
        FOR case IN {COLLECTION_CASES}
            FILTER LENGTH(case.props.related_cases) > 0
            RETURN {{
                id: case.props.external_id,
                kind: case.props.kind,
                dossier_numbers: case.props.dossier_numbers,
                related_cases: case.props.related_cases
            }}
        """
    )
