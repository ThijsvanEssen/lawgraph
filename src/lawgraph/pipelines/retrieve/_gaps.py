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
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_RAW_SOURCES,
    RAW_KIND_EU_CELEX,
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_RS_CONTENT,
    SOURCE_BWB,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.identifiers import CELEX_AQL_REGEX, find_celex_ids
from lawgraph.core.logging import get_logger
from lawgraph.core.time import iso_timestamp
from lawgraph.db import Store

logger = get_logger(__name__)

# The most gaps of one kind a run fetches; the rest is said out loud and comes next time.
MAX_GAPS_PER_RUN = 50_000

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
    """Find CELEX IDs referenced in BWB article text but not yet loaded from EUR-Lex."""
    # CELEX IDs already in instruments collection
    aql_loaded = f"""
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.celex != null
      RETURN UPPER(inst.props.celex)
    """
    loaded: set[str] = cast(set[str], set(store.query(aql_loaded)))

    # CELEX IDs already retrieved into raw_sources
    aql_raw = f"""
    FOR r IN {COLLECTION_RAW_SOURCES}
      FILTER r.source == "eurlex" AND r.kind == @kind
      RETURN UPPER(r.external_id)
    """
    already_retrieved: set[str] = cast(
        set[str], set(store.query(aql_raw, {"kind": RAW_KIND_EU_CELEX}))
    )
    known = loaded | already_retrieved

    # Scan BWB article text for CELEX references; only the texts that can hold one are sent.
    aql_texts = f"""
    FOR art IN {COLLECTION_ARTICLES}
      FILTER art.props.bwb_id != null
      FILTER art.props.text != null
      FILTER REGEX_TEST(art.props.text, @celex)
      RETURN art.props.text
    """
    found: set[str] = set()
    for text in store.query(aql_texts, {"celex": CELEX_AQL_REGEX}):
        for celex in find_celex_ids(str(text)):
            if celex not in known:
                found.add(celex)

    return sorted(found)


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
