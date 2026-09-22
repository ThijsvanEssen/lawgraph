"""What the graph refers to and does not hold: the work list of ``retrieve <source> --mode gaps``.

A retrieve pipeline chooses what to fetch in one of three ways: what changed since a date
(``incremental``), everything inside the window (``full``), or what loaded records refer to
and the graph only holds a stub of (``gaps``). These are the queries of the last; the report
of ``lawgraph gaps`` reads the same ones, so it shows what a run would fetch.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_RAW_SOURCES,
    RAW_KIND_EU_CELEX,
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_RS_CONTENT,
    RAW_KIND_TK_KAMERSTUK_XML,
    RELATION_PART_OF,
    SOURCE_BWB,
    SOURCE_EURLEX,
    SOURCE_RECHTSPRAAK,
    SOURCE_TK,
)
from lawgraph.core.identifiers import kamerstuk_identifier
from lawgraph.core.logging import get_logger
from lawgraph.core.time import iso_timestamp
from lawgraph.db import Store, raw_key

logger = get_logger(__name__)

# The most gaps of one kind a run fetches; the rest is said out loud and comes next time.
MAX_GAPS_PER_RUN = 50_000

# Keys looked up in one query (as ``ArangoStore.existing_keys``).
_KEY_CHUNK = 5000

# A law is fetched when at least this many of its articles are referred to.
DEFAULT_MIN_STUBS = 3


def bwb_gaps(store: Store, *, min_stubs: int = DEFAULT_MIN_STUBS) -> list[str]:
    """BWB ids of the laws that are referred to and not loaded.

    A law of which *min_stubs* articles or more are referred to, and every law a loaded
    regulation is issued under ("Gelet op"): that one is named by the legislator, not
    found in running text, so one mention is enough. (The Wft and the Wwft were named as a
    basis 1,203 and 73 times and were in no list of gaps: a basis whose law is absent made
    no stub.)
    """
    loaded = loaded_bwb_ids(store)
    cited = [
        row["bwb_id"]
        for row in stub_article_counts(store)
        if row["bwb_id"] not in loaded and row["count"] >= min_stubs
    ]
    return list(
        dict.fromkeys([*cited, *(b for b in basis_laws(store) if b not in loaded)])
    )


def basis_laws(store: Store) -> list[str]:
    """BWB ids named as the basis of a loaded regulation, the most named first."""
    aql = f"""
    FOR regulation IN {COLLECTION_INSTRUMENTS}
      FILTER regulation.props.source == @source AND LENGTH(regulation.props.basis) > 0
      FOR basis IN regulation.props.basis
        FILTER basis.bwb_id != null
        COLLECT bwb_id = UPPER(basis.bwb_id) WITH COUNT INTO named
        SORT named DESC
        RETURN bwb_id
    """
    return [str(bwb_id) for bwb_id in store.query(aql, {"source": SOURCE_BWB})]


def loaded_bwb_ids(store: Store) -> set[str]:
    aql = f"""
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.bwb_id != null
      FILTER inst.props.stub != true
      RETURN UPPER(inst.props.bwb_id)
    """
    return {str(bwb_id) for bwb_id in store.query(aql)}


def _capped(rows: list[Any], what: str) -> list[Any]:
    """The first ``MAX_GAPS_PER_RUN`` of *rows*; a longer list is said out loud."""
    if len(rows) > MAX_GAPS_PER_RUN:
        logger.warning(
            "%d %s found; this run takes the first %d (`retrieve all --mode gaps` or expand-graph "
            "again for the rest).",
            len(rows),
            what,
            MAX_GAPS_PER_RUN,
        )
        return rows[:MAX_GAPS_PER_RUN]
    return rows


def stub_article_counts(store: Store) -> list[dict[str, Any]]:
    """Return stub article groups sorted by reference count descending."""
    aql = f"""
    FOR doc IN {COLLECTION_ARTICLES}
      FILTER doc.props.stub == true AND doc.props.bwb_id != null
      COLLECT bwb_id = doc.props.bwb_id WITH COUNT INTO cnt
      SORT cnt DESC
      RETURN {{ bwb_id, count: cnt }}
    """
    return list(store.query(aql))


def rechtspraak_gaps(store: Store) -> list[str]:
    """ECLIs of the Dutch stub judgments, sorted; Rechtspraak has no EU or ECHR judgments."""
    aql = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
      FILTER j.props.stub == true AND j.props.ecli != null
      FILTER STARTS_WITH(j.props.ecli, "ECLI:NL:")
      SORT j.props.ecli
      RETURN j.props.ecli
    """
    # Those Rechtspraak answered 404 for come out before the cap, not after it: they sort
    # where they sort, and a first 50,000 full of judgments that are not published would
    # keep every later one from ever being asked for.
    missing_aql = f"""
    FOR r IN {COLLECTION_RAW_SOURCES}
      FILTER r.source == @source AND r.kind == @kind AND r.meta.retry_after > @now
      RETURN r.external_id
    """
    missing = set(
        store.query(
            missing_aql,
            {
                "source": SOURCE_RECHTSPRAAK,
                "kind": RAW_KIND_RS_CONTENT + RAW_KIND_MISSING_SUFFIX,
                "now": iso_timestamp(dt.datetime.now(dt.timezone.utc)),
            },
        )
    )
    eclis = [ecli for ecli in store.query(aql) if ecli not in missing]
    return _capped(eclis, "stub judgments")


def eurlex_gaps(store: Store) -> list[str]:
    """The EU acts BWB regulations name (``props.celex_refs``) that were not retrieved.

    The id is an attribute of the link in the XML, not text of an article, so it is read
    from what ``normalize bwb`` kept on the regulation.
    """
    aql = f"""
    LET retrieved = (
      FOR r IN {COLLECTION_RAW_SOURCES}
        FILTER r.source == @source AND r.kind == @kind
        RETURN UPPER(r.external_id)
    )
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.celex_refs != null
      FOR celex IN inst.props.celex_refs
        FILTER celex NOT IN retrieved
        COLLECT named = celex
        SORT named
        RETURN named
    """
    bind = {"source": SOURCE_EURLEX, "kind": RAW_KIND_EU_CELEX}
    return cast(list[str], list(store.query(aql, bind)))


def kamerstuk_gaps(store: Store, kind: str = "toelichting") -> list[dict[str, Any]]:
    """The Tweede Kamer papers whose *kind* contains a word, and whose XML was not retrieved.

    Each has the dossier it is part of (a paper without one or without a number in it has no
    address in the repository and is left out) and its ``identifier``, ``kst-<dossier>-<n>``.
    Those the repository answered HTTP 404 for not long ago are left out too, so the report
    of ``lawgraph gaps`` names exactly what a run fetches.
    """
    aql = f"""
    FOR pub IN {COLLECTION_DOCUMENTS}
      FILTER "TK" IN pub.labels
      FILTER CONTAINS(LOWER(pub.props.kind || ""), @kind)
      FILTER pub.props.sequence != null
      LET dossier = FIRST(
        FOR e IN {COLLECTION_EDGES}
          FILTER e._from == pub._id AND e.relation == @part_of
          FILTER STARTS_WITH(e._to, "{COLLECTION_DOSSIERS}/")
          FOR d IN {COLLECTION_DOSSIERS}
            FILTER d._id == e._to
            RETURN d
      )
      FILTER dossier != null AND dossier.props.number != null
      RETURN {{
        key: pub._key,
        title: pub.props.title || pub.props.display_name || pub._key,
        number: dossier.props.number,
        suffix: dossier.props.suffix,
        sequence: pub.props.sequence,
        date: pub.props.date
      }}
    """
    papers = list(store.query(aql, {"kind": kind.lower(), "part_of": RELATION_PART_OF}))
    for paper in papers:
        paper["identifier"] = kamerstuk_identifier(
            paper["number"], paper.get("suffix"), paper["sequence"]
        )
    stored = _with_raw_record(store, papers, RAW_KIND_TK_KAMERSTUK_XML)
    waiting = _with_raw_record(
        store,
        papers,
        RAW_KIND_TK_KAMERSTUK_XML + RAW_KIND_MISSING_SUFFIX,
        retry_ahead=True,
    )
    return _capped(
        [p for p in papers if p["identifier"] not in stored | waiting],
        "Kamerstukken without XML",
    )


def _with_raw_record(
    store: Store,
    papers: list[dict[str, Any]],
    kind: str,
    *,
    retry_ahead: bool = False,
) -> set[str]:
    """The identifiers of *papers* that have a raw record of *kind*, by primary key.

    With *retry_ahead* only a record of a missing document counts that is not to be asked for
    again yet.
    """
    by_key = {
        raw_key(SOURCE_TK, kind, paper["identifier"]): paper["identifier"]
        for paper in papers
    }
    retry = "FILTER r.meta.retry_after > @now" if retry_ahead else ""
    aql = f"""
    FOR r IN {COLLECTION_RAW_SOURCES}
      FILTER r._key IN @keys
      {retry}
      RETURN r._key
    """
    bind: dict[str, Any] = {}
    if retry_ahead:
        bind["now"] = iso_timestamp(dt.datetime.now(dt.timezone.utc))
    keys = list(by_key)
    found: set[str] = set()
    for start in range(0, len(keys), _KEY_CHUNK):
        chunk = {**bind, "keys": keys[start : start + _KEY_CHUNK]}
        found.update(by_key[key] for key in store.query(aql, chunk))
    return found


def echr_gaps(store: Store) -> list[str]:
    """Return ECLIs (or HUDOC app numbers) of stub ECHR judgment nodes."""
    aql = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
      FILTER j.props.stub == true AND STARTS_WITH(j.props.ecli, "ECLI:CE:ECHR:")
      SORT j.props.ecli
      RETURN j.props.ecli
    """
    return [e for e in store.query(aql) if e]


def verdragenbank_gaps(store: Store) -> list[str]:
    """Return external IDs of stub verdrag instrument nodes."""
    aql = f"""
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.stub == true
        AND inst.props.kind IN ["verdrag", "bilateraalverdrag", "multilateraalverdrag"]
      RETURN inst.props.external_id
    """
    return [e for e in store.query(aql) if e]
