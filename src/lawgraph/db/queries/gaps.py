"""The graph reads of the retrieve phase: what the graph refers to and does not hold (the
work list of ``retrieve <source> --mode gaps`` and the report of ``lawgraph gaps``), and the
identifiers a retrieve command takes from the graph."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_RAW_SOURCES,
    RAW_KIND_EU_CELEX,
    RELATION_ANSWERS,
    SOURCE_BWB,
    SOURCE_EURLEX,
)
from lawgraph.core.judgments import PROCEDURE_PRELIMINARY_RULING
from lawgraph.db.counting import Store

# ── laws ─────────────────────────────────────────────────────────────────────


def basis_bwb_ids(store: Store) -> Iterator[Any]:
    """BWB ids named as the basis of a loaded regulation, the most named first."""
    aql = f"""
    FOR regulation IN {COLLECTION_INSTRUMENTS}
      FILTER regulation.props.source == @source AND LENGTH(regulation.props.basis) > 0
      FOR basis IN regulation.props.basis
        FILTER basis.bwb_id != null
        COLLECT bwb_id = UPPER(basis.bwb_id) WITH COUNT INTO named
        SORT named DESC, bwb_id
        RETURN bwb_id
    """
    return store.query(aql, {"source": SOURCE_BWB})


def loaded_bwb_ids(store: Store) -> Iterator[Any]:
    """The BWB ids (upper case) of the regulations that are loaded, not stubs."""
    aql = f"""
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.bwb_id != null
      FILTER inst.props.stub != true
      RETURN UPPER(inst.props.bwb_id)
    """
    return store.query(aql)


def stub_article_counts(store: Store) -> Iterator[dict[str, Any]]:
    """``{bwb_id, count}`` of the stub articles per law, the most referred to first."""
    aql = f"""
    FOR doc IN {COLLECTION_ARTICLES}
      FILTER doc.props.stub == true AND doc.props.bwb_id != null
      COLLECT bwb_id = doc.props.bwb_id WITH COUNT INTO cnt
      SORT cnt DESC, bwb_id
      RETURN {{ bwb_id, count: cnt }}
    """
    return store.query(aql)


def instrument_titles(store: Store) -> Iterator[dict[str, Any]]:
    """``{bwb_id, title}`` of every instrument with a BWB id: its best available title."""
    aql = f"""
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.bwb_id != null
      RETURN {{
        bwb_id: inst.props.bwb_id,
        title: inst.props.citation_title OR inst.props.title OR inst.props.display_name
      }}
    """
    return store.query(aql)


# ── judgments, EU acts, treaties ─────────────────────────────────────────────


def stub_dutch_eclis(store: Store) -> Iterator[Any]:
    """ECLIs of the Dutch stub judgments, sorted."""
    aql = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
      FILTER j.props.stub == true AND j.props.ecli != null
      FILTER STARTS_WITH(j.props.ecli, "ECLI:NL:")
      SORT j.props.ecli
      RETURN j.props.ecli
    """
    return store.query(aql)


def unanswered_preliminary_rulings(
    store: Store, *, paragraphs: int
) -> Iterator[dict[str, Any]]:
    """``{ecli, paragraphs}`` of the preliminary rulings without an ANSWERS edge, with their
    first *paragraphs* paragraphs (where they say who asked their questions)."""
    aql = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
      FILTER j.props.judgment_metadata.type == @procedure AND j.props.ecli != null
      FILTER LENGTH(
        FOR e IN {COLLECTION_EDGES}
          FILTER e._from == j._id AND e.relation == @answers
          LIMIT 1
          RETURN 1
      ) == 0
      SORT j.props.ecli
      RETURN {{ecli: j.props.ecli, paragraphs: SLICE(j.props.paragraphs OR [], 0, @paragraphs)}}
    """
    return store.query(
        aql,
        {
            "procedure": PROCEDURE_PRELIMINARY_RULING,
            "answers": RELATION_ANSWERS,
            "paragraphs": paragraphs,
        },
    )


def unretrieved_celex_refs(store: Store) -> Iterator[Any]:
    """The EU acts BWB regulations name (``props.celex_refs``) or implement by their
    considerans (``props.implements_celex``) that were not retrieved, sorted."""
    aql = f"""
    LET retrieved = (
      FOR r IN {COLLECTION_RAW_SOURCES}
        FILTER r.source == @source AND r.kind == @kind
        RETURN UPPER(r.external_id)
    )
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.celex_refs != null OR inst.props.implements_celex != null
      FOR celex IN UNION_DISTINCT(
          inst.props.celex_refs || [], inst.props.implements_celex || []
      )
        FILTER celex NOT IN retrieved
        COLLECT named = celex
        SORT named
        RETURN named
    """
    bind = {"source": SOURCE_EURLEX, "kind": RAW_KIND_EU_CELEX}
    return store.query(aql, bind)


def known_celex_ids(store: Store) -> Iterator[Any]:
    """The CELEX number of every instrument that has one."""
    aql = (
        f"FOR inst IN {COLLECTION_INSTRUMENTS} "
        "FILTER inst.props.celex != null RETURN inst.props.celex"
    )
    return store.query(aql)


def stub_echr_eclis(store: Store) -> Iterator[Any]:
    """ECLIs (or HUDOC app numbers) of the stub ECHR judgments, sorted."""
    aql = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
      FILTER j.props.stub == true AND STARTS_WITH(j.props.ecli, "ECLI:CE:ECHR:")
      SORT j.props.ecli
      RETURN j.props.ecli
    """
    return store.query(aql)


def stub_treaty_ids(store: Store) -> Iterator[Any]:
    """External ids of the stub treaty instruments."""
    aql = f"""
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.stub == true
        AND inst.props.kind IN ["verdrag", "bilateraalverdrag", "multilateraalverdrag"]
      SORT inst._key
      RETURN inst.props.external_id
    """
    return store.query(aql)


# ── Kamerstukken ─────────────────────────────────────────────────────────────


def papers_with_dossier(store: Store, kinds: list[str]) -> Iterator[dict[str, Any]]:
    """The Tweede Kamer papers whose kind contains one of *kinds* (lower case), with the
    dossier they are numbered in and their number there: ``{key, title, number, suffix,
    sequence, date}``."""
    aql = f"""
    FOR pub IN {COLLECTION_DOCUMENTS}
      FILTER "TK" IN pub.labels
      FILTER pub.props.dossier_number != null AND pub.props.sequence != null
      LET kind = LOWER(pub.props.kind || "")
      FILTER LENGTH(FOR word IN @kinds FILTER CONTAINS(kind, word) LIMIT 1 RETURN 1) > 0
      SORT pub._key
      RETURN {{
        key: pub._key,
        title: pub.props.title || pub.props.display_name || pub._key,
        number: pub.props.dossier_number,
        suffix: pub.props.dossier_suffix,
        sequence: pub.props.sequence,
        date: pub.props.date
      }}
    """
    return store.query(aql, {"kinds": kinds})


def existing_raw_keys(
    store: Store, keys: list[str], *, retry_after_iso: str | None = None
) -> Iterator[Any]:
    """Which of the raw record *keys* exist; with *retry_after_iso* only those whose
    ``retry_after`` lies after it (a missing document not to be asked for again yet)."""
    retry = "FILTER r.meta.retry_after > @now" if retry_after_iso else ""
    aql = f"""
    FOR r IN {COLLECTION_RAW_SOURCES}
      FILTER r._key IN @keys
      {retry}
      RETURN r._key
    """
    bind: dict[str, Any] = {}
    if retry_after_iso:
        bind["now"] = retry_after_iso
    return store.query(aql, {**bind, "keys": keys})


def dossiers_named_by_publications(store: Store) -> list[str]:
    """The dossier numbers that an amending or commencing publication names (on an article
    version, or on the publication or regulation itself) and that no dossier has."""
    aql = f"""
    LET named = UNIQUE(UNION(
        (FOR v IN {COLLECTION_ARTICLE_VERSIONS}
            FOR n IN APPEND(
                v.props.origin_publication.dossiers || [],
                v.props.commencement_publication.dossiers || []
            )
            RETURN n),
        (FOR i IN {COLLECTION_INSTRUMENTS}
            FILTER i.props.dossier_numbers != null
            FOR n IN i.props.dossier_numbers
                RETURN n)
    ))
    FOR number IN named
        FILTER REGEX_TEST(number, "^[0-9]+$")
        FILTER LENGTH(
            FOR d IN {COLLECTION_DOSSIERS} FILTER d.props.number == number LIMIT 1 RETURN 1
        ) == 0
        SORT number
        RETURN number
    """
    return list(store.query(aql))


def dossiers_with_numbers(store: Store, numbers: list[str]) -> set[str]:
    """Those of *numbers* that a dossier has."""
    aql = f"""
    FOR number IN @numbers
        FILTER LENGTH(
            FOR d IN {COLLECTION_DOSSIERS} FILTER d.props.number == number LIMIT 1 RETURN 1
        ) > 0
        RETURN number
    """
    return set(store.query(aql, {"numbers": numbers}))


def dossiers_named_by_papers(store: Store) -> list[str]:
    """The dossier labels (``36996``, ``31700-VI``) that a Tweede Kamer paper or case is part
    of and that no dossier has."""
    aql = f"""
    LET named = UNIQUE(UNION(
        (FOR doc IN {COLLECTION_DOCUMENTS}
            FILTER "TK" IN doc.labels
            FOR label IN doc.props.dossier_numbers || []
                RETURN label),
        (FOR c IN {COLLECTION_CASES}
            FOR label IN c.props.dossier_numbers || []
                RETURN label)
    ))
    FOR label IN named
        FILTER LENGTH(
            FOR d IN {COLLECTION_DOSSIERS} FILTER d.props.label == label LIMIT 1 RETURN 1
        ) == 0
        SORT label
        RETURN label
    """
    return list(store.query(aql))


def dossiers_missing_papers(store: Store) -> list[str]:
    """The numbers of the dossiers that lack a paper below the highest number the graph has
    of them: nr. 48 of the Wmcz 2018 without nr. 1 to 47. Each paper counts in the dossier
    it is numbered in, a chapter of a budget (``36600-XV``) on its own."""
    aql = f"""
    FOR doc IN {COLLECTION_DOCUMENTS}
        FILTER "TK" IN doc.labels
        FILTER doc.props.dossier_number != null AND doc.props.sequence != null
        COLLECT number = doc.props.dossier_number, suffix = doc.props.dossier_suffix
        AGGREGATE held = COUNT_UNIQUE(doc.props.sequence), last = MAX(doc.props.sequence)
        FILTER held < last
        RETURN DISTINCT number
    """
    return list(store.query(aql))
