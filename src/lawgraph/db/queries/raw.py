"""The reads of ``raw_sources``: the records of a source and kind, what was stored when, and
the counts of the batch commands. Payloads are not read here; a caller that needs the text
passes the rows through ``store.with_payloads``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_RAW_SOURCES,
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_RS_CONTENT,
    RAW_KIND_STB_AMVB,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_STEMMING,
    SOURCE_BWB,
    SOURCE_EURLEX,
    SOURCE_RECHTSPRAAK,
    SOURCE_STAATSBLAD,
    SOURCE_TK,
)
from lawgraph.db.counting import Store

# ── records of a source ──────────────────────────────────────────────────────


def iter_raw_records(
    store: Store,
    *,
    source: str,
    kinds: list[str],
    since_iso: str | None,
    batch_size: int,
) -> Iterator[dict[str, Any]]:
    """The records of *kinds*, those fetched at or after *since_iso* when it is given."""
    since_filter = "FILTER r.fetched_at >= @since" if since_iso else ""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source
            FILTER r.kind IN @kinds
            {since_filter}
            RETURN r
        """
    bind_vars: dict[str, Any] = {"source": source, "kinds": kinds}
    if since_iso:
        bind_vars["since"] = since_iso
    return store.query(aql, bind_vars, batch_size=batch_size)


def count_raw_records(store: Store, source: str, kinds: list[str]) -> int | None:
    """How many records *kinds* hold, from the index."""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind IN @kinds
            COLLECT WITH COUNT INTO n
            RETURN n
        """
    count = next(iter(store.query(aql, {"source": source, "kinds": kinds})), None)
    return count if isinstance(count, int) else None


def decisions_voted_since(store: Store, since_iso: str | None) -> list[Any]:
    """The decision ids (``Besluit_Id``) of the Tweede Kamer vote rows fetched since then."""
    bind_vars = {"source": SOURCE_TK, "kind": RAW_KIND_TK_STEMMING}
    touched = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind AND r.fetched_at >= @since
            FILTER r.payload_json.Besluit_Id != null
            RETURN DISTINCT r.payload_json.Besluit_Id
        """
    return list(store.query(touched, {**bind_vars, "since": since_iso}))


def vote_rows_of_decisions(
    store: Store, decisions: list[Any]
) -> Iterator[dict[str, Any]]:
    """Every Tweede Kamer vote row of *decisions*."""
    bind_vars = {"source": SOURCE_TK, "kind": RAW_KIND_TK_STEMMING}
    rows = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind
            FILTER r.payload_json.Besluit_Id IN @decisions
            RETURN r
        """
    return store.query(rows, {**bind_vars, "decisions": decisions})


# ── what was stored when ─────────────────────────────────────────────────────


def ids_waiting_for_retry(
    store: Store, *, source: str, kind: str, now_iso: str | None
) -> Iterator[Any]:
    """External ids of the records of *kind* (a missing kind) whose ``retry_after`` lies
    after *now_iso*: documents the source answered HTTP 404 for not long ago."""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind AND r.meta.retry_after > @now
            RETURN r.external_id
        """
    bind = {"source": source, "kind": kind, "now": now_iso}
    return store.query(aql, bind)


def ids_stored_since(
    store: Store, *, source: str, kind: str, cutoff_iso: str | None
) -> Iterator[Any]:
    """External ids of the records of *kind* fetched at or after *cutoff_iso*."""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind AND r.fetched_at >= @cutoff
            RETURN r.external_id
        """
    return store.query(aql, {"source": source, "kind": kind, "cutoff": cutoff_iso})


def fetch_times(store: Store, *, source: str, kind: str) -> Iterator[dict[str, Any]]:
    """``{id, at}`` (external id, ``fetched_at``) of every stored record of *kind*."""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind
            RETURN {{id: r.external_id, at: r.fetched_at}}
        """
    return store.query(aql, {"source": source, "kind": kind})


def toestand_state_urls(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, url}`` (BWB id, ``meta.state_url``) of the stored current toestanden."""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind
            RETURN {{id: r.external_id, url: r.meta.state_url}}
        """
    return store.query(aql, {"source": SOURCE_BWB, "kind": RAW_KIND_BWB_TOESTAND})


def toestand_payload_refs(store: Store) -> Iterator[dict[str, Any]]:
    """``{bwb_id, payload_ref}`` of every stored toestand, fifty to a cursor batch."""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
          FILTER r.source == @source AND r.kind == @kind AND r.external_id != null
          RETURN {{ bwb_id: r.external_id, payload_ref: r.payload_ref }}
        """
    return store.query(
        aql,
        bind_vars={"source": SOURCE_BWB, "kind": RAW_KIND_BWB_TOESTAND},
        batch_size=50,
    )


def stored_staatsblad_ids(store: Store, identifiers: list[str]) -> Iterator[Any]:
    """Which of the Staatsblad *identifiers* are stored."""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
          FILTER r.source == @source AND r.kind == @kind AND r.external_id IN @ext_ids
          RETURN r.external_id
        """
    return store.query(
        aql,
        bind_vars={
            "source": SOURCE_STAATSBLAD,
            "kind": RAW_KIND_STB_AMVB,
            "ext_ids": identifiers,
        },
    )


# ── what was fetched since a moment, for the semantic phase ─────────────────


def judgment_payload_refs(
    store: Store, *, since_iso: str | None, batch_size: int
) -> Iterator[dict[str, Any]]:
    """``{ecli, payload_ref}`` of every stored Rechtspraak judgment with a payload,
    those fetched at or after *since_iso* when it is given."""
    since_filter = "FILTER r.fetched_at >= @since" if since_iso else ""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind
            {since_filter}
            FILTER r.payload_ref != null
            RETURN {{ecli: r.meta.ecli || r.external_id, payload_ref: r.payload_ref}}
        """
    bind: dict[str, Any] = {
        "source": SOURCE_RECHTSPRAAK,
        "kind": RAW_KIND_RS_CONTENT,
    }
    if since_iso:
        bind["since"] = since_iso
    return store.query(aql, bind, batch_size=batch_size)


def count_judgment_records(store: Store) -> int | None:
    """How many Rechtspraak judgments are stored, from the index."""
    count_aql = f"""
            FOR r IN {COLLECTION_RAW_SOURCES}
                FILTER r.source == @source AND r.kind == @kind
                COLLECT WITH COUNT INTO n
                RETURN n
            """
    bind = {"source": SOURCE_RECHTSPRAAK, "kind": RAW_KIND_RS_CONTENT}
    count = next(iter(store.query(count_aql, bind)), None)
    return count if isinstance(count, int) else None


def judgment_eclis_fetched_since(store: Store, since_iso: str) -> Iterator[Any]:
    """The ECLIs of the judgments retrieved at or after *since_iso*."""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind
            FILTER r.fetched_at >= @since
            RETURN r.meta.ecli || r.external_id
        """
    bind = {
        "source": SOURCE_RECHTSPRAAK,
        "kind": RAW_KIND_RS_CONTENT,
        "since": since_iso,
    }
    return store.query(aql, bind)


def bwb_ids_fetched_since(store: Store, since_iso: str) -> Iterator[Any]:
    """BWB ids whose raw record was fetched at or after *since_iso*."""
    aql = f"""
        FOR raw IN {COLLECTION_RAW_SOURCES}
            FILTER raw.source == @source
            FILTER raw.fetched_at >= @since
            FILTER raw.meta.bwb_id != null
        RETURN DISTINCT raw.meta.bwb_id
        """
    return store.query(aql, bind_vars={"source": SOURCE_BWB, "since": since_iso})


def celex_fetched_since(store: Store, since_iso: str) -> Iterator[Any]:
    """CELEX numbers of the EUR-Lex records fetched at or after *since_iso*."""
    aql = f"""
            FOR raw IN {COLLECTION_RAW_SOURCES}
                FILTER raw.source == @source
                FILTER raw.fetched_at >= @since
                FILTER raw.meta.celex != null
            RETURN raw.meta.celex
            """
    return store.query(aql, bind_vars={"source": SOURCE_EURLEX, "since": since_iso})


def tk_document_ids_fetched_since(store: Store, since_iso: str) -> Iterator[Any]:
    """External ids of the Tweede Kamer documents fetched at or after *since_iso*."""
    aql = f"""
        FOR raw IN {COLLECTION_RAW_SOURCES}
            FILTER raw.source == @source AND raw.kind == @kind
            FILTER raw.fetched_at >= @since
            FILTER raw.external_id != null
        RETURN raw.external_id
        """
    return store.query(
        aql,
        bind_vars={
            "source": SOURCE_TK,
            "kind": RAW_KIND_TK_DOCUMENT,
            "since": since_iso,
        },
    )


# ── counts of the batch commands ─────────────────────────────────────────────

# Grouped on the fields of the index, so the count walks the index and reads no document.
RAW_COUNTS_AQL = f"""
FOR r IN {COLLECTION_RAW_SOURCES}
    COLLECT source = r.source, kind = r.kind WITH COUNT INTO n
    RETURN {{source, kind, n}}
"""


def raw_counts(store: Store) -> Iterator[dict[str, Any]]:
    """``{source, kind, n}`` for every raw kind that holds records."""
    return store.query(RAW_COUNTS_AQL)


# Grouped on the fields of the index, so the count walks the index: as a scan of the
# collection it read every document, and an EU act is up to 1 MB.
RECORD_COUNTS_AQL = f"""
FOR r IN {COLLECTION_RAW_SOURCES}
    COLLECT source = r.source, kind = r.kind WITH COUNT INTO n
    FILTER NOT LIKE(kind, @missing)
    RETURN n
"""


def record_counts(store: Store, missing_suffix: str) -> Iterator[int]:
    """The number of records per kind, leaving out the kinds ending in *missing_suffix*."""
    return store.query(RECORD_COUNTS_AQL, {"missing": f"%{missing_suffix}"})


def payload_refs_sample(
    store: Store, *, source: str, kind: str, sample: int
) -> Iterator[str]:
    """The ``payload_ref`` of at most *sample* records of *kind*."""
    aql = f"""
    FOR r IN {COLLECTION_RAW_SOURCES}
        FILTER r.source == @source AND r.kind == @kind AND r.payload_ref != null
        LIMIT @sample
        RETURN r.payload_ref
    """
    bind = {"source": source, "kind": kind, "sample": sample}
    return store.query(aql, bind)
