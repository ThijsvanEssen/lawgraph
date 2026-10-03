"""The reads of ``raw_sources``: the records of a source and kind, what was stored when, and
the counts of the batch commands. Payloads are not read here; a caller that needs the text
passes the rows through ``store.with_payloads``.

A scan of records comes in key order within its source and kind, so a run reads them in the
same order every time.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_ECHR_JUDGMENT,
    RAW_KIND_RS_CONTENT,
    RAW_KIND_STB_AMVB,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_STEMMING,
    SOURCE_BWB,
    SOURCE_ECHR,
    SOURCE_EURLEX,
    SOURCE_RECHTSPRAAK,
    SOURCE_STAATSBLAD,
    SOURCE_TK,
)
from lawgraph.db._rows import raw_doc
from lawgraph.db.counting import Store

# A moment that may be absent: absent, every record is after it (as ArangoDB compared a
# string with null).
_SINCE = "(%(since)s::text IS NULL OR fetched_at >= %(since)s)"
_ORDER = "ORDER BY source, kind, key"
# The toestanden of each law from the oldest to the newest: what normalize bwb-history makes
# of them (the place of each version, the version a later toestand merges into) depends on
# the order it reads them in. Nulls first, as ArangoDB's SORT puts them: retrieve bwb-history
# writes both into every toestand's meta (all 813 of the parity build have them), so a null is
# only a record written otherwise.
_CHRONOLOGICAL = (
    "ORDER BY lg_str(doc -> 'meta' -> 'bwb_id') NULLS FIRST,"
    " lg_str(doc -> 'meta' -> 'start_date') NULLS FIRST, key"
)


def _records(rows: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    return (raw_doc(row) for row in rows)


# ── records of a source ──────────────────────────────────────────────────────


def iter_raw_records(
    store: Store,
    *,
    source: str,
    kinds: list[str],
    since_iso: str | None,
    batch_size: int,
    chronological: bool = False,
) -> Iterator[dict[str, Any]]:
    """The records of *kinds*, those fetched at or after *since_iso* when it is given;
    *chronological*: the toestanden of each law in the order of their start."""
    rows = store.query(
        f"""
        SELECT key, doc FROM raw_sources
        WHERE source = %(source)s AND kind = ANY(%(kinds)s) AND {_SINCE}
        {_CHRONOLOGICAL if chronological else _ORDER}
        """,
        {"source": source, "kinds": kinds, "since": since_iso},
        batch_size=batch_size,
    )
    return _records(rows)


def count_raw_records(store: Store, source: str, kinds: list[str]) -> int | None:
    """How many records *kinds* hold, from the index."""
    count = next(
        store.query(
            "SELECT count(*)::int FROM raw_sources"
            " WHERE source = %(source)s AND kind = ANY(%(kinds)s)",
            {"source": source, "kinds": kinds},
        ),
        None,
    )
    return count if isinstance(count, int) else None


def decisions_voted_since(store: Store, since_iso: str | None) -> list[Any]:
    """The decision ids (``Besluit_Id``) of the Tweede Kamer vote rows fetched since then."""
    rows = store.query(
        f"""
        SELECT DISTINCT doc -> 'payload_json' ->> 'Besluit_Id' AS decision
        FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s AND {_SINCE}
          AND doc -> 'payload_json' ->> 'Besluit_Id' IS NOT NULL
        ORDER BY decision
        """,
        {"source": SOURCE_TK, "kind": RAW_KIND_TK_STEMMING, "since": since_iso},
    )
    return list(rows)


def vote_rows_of_decisions(
    store: Store, decisions: list[Any]
) -> Iterator[dict[str, Any]]:
    """Every Tweede Kamer vote row of *decisions*."""
    rows = store.query(
        f"""
        SELECT key, doc FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s
          AND doc -> 'payload_json' ->> 'Besluit_Id' = ANY(%(decisions)s)
        {_ORDER}
        """,
        {
            "source": SOURCE_TK,
            "kind": RAW_KIND_TK_STEMMING,
            "decisions": [str(d) for d in decisions],
        },
    )
    return _records(rows)


def deleted_records_since(
    store: Store, kind: str, since_iso: str | None
) -> Iterator[dict[str, Any]]:
    """The Tweede Kamer records of *kind* fetched since then that the Kamer deleted."""
    rows = store.query(
        f"""
        SELECT key, doc FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s AND {_SINCE}
          AND lg_bool(doc -> 'payload_json' -> 'Verwijderd') IS TRUE
        {_ORDER}
        """,
        {"source": SOURCE_TK, "kind": kind, "since": since_iso},
    )
    return _records(rows)


def tk_records_of(
    store: Store, kind: str, external_ids: list[str]
) -> Iterator[dict[str, Any]]:
    """The Tweede Kamer records of *kind* with these TK ids."""
    rows = store.query(
        f"""
        SELECT key, doc FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s AND external_id = ANY(%(ids)s)
        {_ORDER}
        """,
        {"source": SOURCE_TK, "kind": kind, "ids": external_ids},
    )
    return _records(rows)


# ── what was stored when ─────────────────────────────────────────────────────


def ids_waiting_for_retry(
    store: Store, *, source: str, kind: str, now_iso: str | None
) -> Iterator[Any]:
    """External ids of the records of *kind* (a missing kind) whose ``retry_after`` lies
    after *now_iso*: documents the source answered HTTP 404 for not long ago."""
    return store.query(
        f"""
        SELECT external_id FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s
          AND lg_str(doc -> 'meta' -> 'retry_after') IS NOT NULL
          AND (%(now)s::text IS NULL OR lg_str(doc -> 'meta' -> 'retry_after') > %(now)s)
        {_ORDER}
        """,
        {"source": source, "kind": kind, "now": now_iso},
    )


def ids_stored_since(
    store: Store, *, source: str, kind: str, cutoff_iso: str | None
) -> Iterator[Any]:
    """External ids of the records of *kind* fetched at or after *cutoff_iso*."""
    return store.query(
        f"""
        SELECT external_id FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s AND {_SINCE}
        {_ORDER}
        """,
        {"source": source, "kind": kind, "since": cutoff_iso},
    )


def echr_items(store: Store) -> Iterator[dict[str, Any]]:
    """``{item_id, ecli, language}`` of every stored HUDOC judgment record."""
    return store.query(
        f"""
        SELECT external_id AS item_id,
               doc -> 'payload_json' -> 'ecli' AS ecli,
               doc -> 'payload_json' -> 'languageisocode' AS language
        FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s
        {_ORDER}
        """,
        {"source": SOURCE_ECHR, "kind": RAW_KIND_ECHR_JUDGMENT},
    )


def fetch_times(store: Store, *, source: str, kind: str) -> Iterator[dict[str, Any]]:
    """``{id, at}`` (external id, ``fetched_at``) of every stored record of *kind*."""
    return store.query(
        f"""
        SELECT external_id AS id, fetched_at AS at FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s
        {_ORDER}
        """,
        {"source": source, "kind": kind},
    )


def toestand_state_urls(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, url}`` (BWB id, ``meta.state_url``) of the stored current toestanden."""
    return store.query(
        f"""
        SELECT external_id AS id, doc -> 'meta' -> 'state_url' AS url FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s
        {_ORDER}
        """,
        {"source": SOURCE_BWB, "kind": RAW_KIND_BWB_TOESTAND},
    )


def toestand_payload_refs(store: Store) -> Iterator[dict[str, Any]]:
    """``{bwb_id, payload_ref}`` of every stored toestand, fifty to a cursor batch."""
    return store.query(
        f"""
        SELECT external_id AS bwb_id, doc -> 'payload_ref' AS payload_ref FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s AND external_id IS NOT NULL
        {_ORDER}
        """,
        {"source": SOURCE_BWB, "kind": RAW_KIND_BWB_TOESTAND},
        batch_size=50,
    )


def stored_staatsblad_ids(store: Store, identifiers: list[str]) -> Iterator[Any]:
    """Which of the Staatsblad *identifiers* are stored."""
    return store.query(
        f"""
        SELECT external_id FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s AND external_id = ANY(%(ids)s)
        {_ORDER}
        """,
        {"source": SOURCE_STAATSBLAD, "kind": RAW_KIND_STB_AMVB, "ids": identifiers},
    )


# ── what was fetched since a moment, for the semantic phase ─────────────────

# ``r.meta.ecli || r.external_id``: the ECLI of the metadata when it has one.
_ECLI = "coalesce(nullif(lg_str(doc -> 'meta' -> 'ecli'), ''), external_id)"


def judgment_payload_refs(
    store: Store, *, since_iso: str | None, batch_size: int
) -> Iterator[dict[str, Any]]:
    """``{ecli, payload_ref}`` of every stored Rechtspraak judgment with a payload,
    those fetched at or after *since_iso* when it is given."""
    return store.query(
        f"""
        SELECT {_ECLI} AS ecli, doc -> 'payload_ref' AS payload_ref FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s AND {_SINCE}
          AND coalesce(json_typeof(doc -> 'payload_ref'), 'null') <> 'null'
        {_ORDER}
        """,
        {"source": SOURCE_RECHTSPRAAK, "kind": RAW_KIND_RS_CONTENT, "since": since_iso},
        batch_size=batch_size,
    )


def count_judgment_records(store: Store) -> int | None:
    """How many Rechtspraak judgments are stored, from the index."""
    return count_raw_records(store, SOURCE_RECHTSPRAAK, [RAW_KIND_RS_CONTENT])


def judgment_eclis_fetched_since(store: Store, since_iso: str) -> Iterator[Any]:
    """The ECLIs of the judgments retrieved at or after *since_iso*."""
    return store.query(
        f"""
        SELECT {_ECLI} FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s AND fetched_at >= %(since)s
        {_ORDER}
        """,
        {"source": SOURCE_RECHTSPRAAK, "kind": RAW_KIND_RS_CONTENT, "since": since_iso},
    )


def bwb_ids_fetched_since(store: Store, since_iso: str) -> Iterator[Any]:
    """BWB ids whose raw record was fetched at or after *since_iso*."""
    return store.query(
        """
        SELECT DISTINCT doc -> 'meta' ->> 'bwb_id' AS bwb_id FROM raw_sources
        WHERE source = %(source)s AND fetched_at >= %(since)s
          AND doc -> 'meta' ->> 'bwb_id' IS NOT NULL
        ORDER BY bwb_id
        """,
        {"source": SOURCE_BWB, "since": since_iso},
    )


def celex_fetched_since(store: Store, since_iso: str) -> Iterator[Any]:
    """CELEX numbers of the EUR-Lex records fetched at or after *since_iso*."""
    return store.query(
        f"""
        SELECT doc -> 'meta' ->> 'celex' FROM raw_sources
        WHERE source = %(source)s AND fetched_at >= %(since)s
          AND doc -> 'meta' ->> 'celex' IS NOT NULL
        {_ORDER}
        """,
        {"source": SOURCE_EURLEX, "since": since_iso},
    )


def tk_document_ids_fetched_since(store: Store, since_iso: str) -> Iterator[Any]:
    """External ids of the Tweede Kamer documents fetched at or after *since_iso*."""
    return store.query(
        f"""
        SELECT external_id FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s AND fetched_at >= %(since)s
          AND external_id IS NOT NULL
        {_ORDER}
        """,
        {"source": SOURCE_TK, "kind": RAW_KIND_TK_DOCUMENT, "since": since_iso},
    )


# ── counts of the batch commands ─────────────────────────────────────────────


def raw_counts(store: Store) -> Iterator[dict[str, Any]]:
    """``{source, kind, n}`` for every raw kind that holds records."""
    return store.query(
        """
        SELECT source, kind, count(*)::int AS n FROM raw_sources
        GROUP BY source, kind
        ORDER BY source NULLS FIRST, kind NULLS FIRST
        """
    )


def record_counts(store: Store, missing_suffix: str) -> Iterator[int]:
    """The number of records per kind, leaving out the kinds ending in *missing_suffix*."""
    return store.query(
        """
        SELECT count(*)::int FROM raw_sources
        GROUP BY source, kind
        HAVING kind NOT LIKE %(missing)s
        ORDER BY source NULLS FIRST, kind NULLS FIRST
        """,
        {"missing": f"%{missing_suffix}"},
    )


def payload_refs_sample(
    store: Store, *, source: str, kind: str, sample: int
) -> Iterator[str]:
    """The ``payload_ref`` of at most *sample* records of *kind*."""
    return store.query(
        f"""
        SELECT lg_str(doc -> 'payload_ref') FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s
          AND lg_str(doc -> 'payload_ref') IS NOT NULL
        {_ORDER}
        LIMIT %(sample)s
        """,
        {"source": source, "kind": kind, "sample": sample},
    )
