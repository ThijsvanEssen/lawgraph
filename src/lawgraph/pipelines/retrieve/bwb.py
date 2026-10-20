from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lawgraph.clients.bwb import BWBClient, ToestandMeta
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_BWB_WTI_GENERAL,
    SOURCE_BWB,
)
from lawgraph.core.identifiers import clean_ids
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.publication_xml import staatsblad_ref_from_bwb_xml
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db.queries import raw as raw_queries

from .base import (
    DOWNLOAD_FAILURES,
    FETCH_WORKERS,
    FailureStreak,
    RetrievePipelineBase,
    RetrieveRecord,
    failure_reason,
    listed,
    missing_record,
)

logger = get_logger(__name__)

# The WTI file of an unchanged toestand is read again after this many days.
WTI_REFRESH_DAYS = 30
# From this many regulations the history reads the SRU listing of every toestand (about 150
# pages) instead of asking the SRU once per regulation.
HISTORY_LISTING_FROM = 150


def _history_id(meta: ToestandMeta) -> str:
    """``{bwb_id}@{start_date}``: the key of a historical toestand."""
    return f"{meta['bwb_id']}@{meta['geldigheidsperiode_startdatum']}"


def _unchanged(
    stored: Mapping[str, Any] | None, meta: ToestandMeta, today: str
) -> bool:
    """Whether the listed current toestand *meta* is the *stored* one, as the SRU described
    it then: the same file and the same end of its period, and that end had passed when it
    was stored, or has not passed yet. A regulation repealed since it was stored keeps its
    last toestand, whose end has passed now: it is stored again, so that its record tells
    it expired (``bwb_xml.expiry_date``)."""
    if stored is None or stored.get("url") != meta["locatie_toestand"]:
        return False
    end = meta.get("geldigheidsperiode_einddatum")
    if str(stored.get("end_date") or "") != str(end or ""):
        return False
    stored_on = str(stored.get("at") or "")[:10]
    return not (end and stored_on <= end < today)


@dataclass
class _Download:
    """What the network gave for one regulation, to be reported by the loop that stores."""

    records: list[RetrieveRecord] = field(default_factory=list)
    skip: str | None = None
    problem: str | None = None


class BWBRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline that fetches BWB toestanden and WTI general information."""

    def __init__(
        self,
        store: GraphStore,
        client: BWBClient | None = None,
    ) -> None:
        super().__init__(store)
        self.client = client or BWBClient()

    def run(
        self,
        *,
        bwb_ids: Sequence[str] | None = None,
        current: Mapping[str, ToestandMeta] | None = None,
        **kwargs: object,
    ) -> PipelineResult:
        """Fetch and store the current toestand and the WTI general information per ID.

        *current* is the toestand of each regulation when the caller already knows it (the
        full load, from its listing). Such a regulation is not asked for again, and it is
        left alone when the stored toestand is the same one; an id given without it is
        always looked up and downloaded.
        """
        return self._store_all(
            self._fetch_current(clean_ids(bwb_ids), current or {}), what="regulations"
        )

    def _fetch_current(
        self, normalized: Sequence[str], current: Mapping[str, ToestandMeta]
    ) -> Iterator[RetrieveRecord]:
        """The WTI general information of each regulation, followed by its current toestand."""
        if not normalized:
            logger.warning("BWB retrieve: no IDs to process.")
            return
        done = self._recently_stored(SOURCE_BWB, RAW_KIND_BWB_TOESTAND)
        bwb_ids = self._without_missing(
            SOURCE_BWB,
            RAW_KIND_BWB_TOESTAND,
            [bwb_id for bwb_id in normalized if bwb_id not in done],
        )
        logger.info(
            "Starting BWB retrieve for %d IDs (%d already stored in the last 24 hours).",
            len(normalized),
            len(normalized) - len(bwb_ids),
        )
        stored = self._stored_toestanden() if current else {}
        today = dutch_today().isoformat()
        wti_fresh = (
            self._stored_ids(
                SOURCE_BWB, RAW_KIND_BWB_WTI_GENERAL, hours=WTI_REFRESH_DAYS * 24
            )
            if current
            else set()
        )

        def download(bwb_id: str) -> _Download:
            """What one regulation needs of the network; the outcome is reported below."""
            meta = current.get(bwb_id)
            if meta is not None and _unchanged(stored.get(bwb_id), meta, today):
                # The same toestand as the stored one. Its WTI file can change on its own
                # (a new abbreviation), so that is read again once a month.
                got = _Download(skip="toestand unchanged since it was stored")
                if bwb_id not in wti_fresh:
                    self._add_wti_general_info(meta, got)
                return got
            meta = meta or self.client.latest_toestand(bwb_id)
            if meta is None:
                return _Download(skip="no toestand in the SRU")
            xml_text = self.client.fetch_toestand_xml(meta)
            published = staatsblad_ref_from_bwb_xml(xml_text)
            got = _Download()
            # The toestand last: it is what a re-run takes for "this regulation is done".
            self._add_wti_general_info(meta, got)
            got.records.append(
                RetrieveRecord(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND,
                    external_id=bwb_id,
                    payload_text=xml_text,
                    meta={
                        "bwb_id": bwb_id,
                        "state_url": meta["locatie_toestand"],
                        "start_date": meta.get("geldigheidsperiode_startdatum"),
                        "end_date": meta.get("geldigheidsperiode_einddatum"),
                        # the publication retrieve staatsblad fetches, read here once
                        "staatsblad_ref": (
                            f"stb-{published[0]}-{published[1]}" if published else None
                        ),
                    },
                )
            )
            return got

        def records(bwb_id: str, got: _Download) -> list[RetrieveRecord]:
            if got.problem:
                self.progress.problem(got.problem, bwb_id)
            if got.skip:
                self.progress.skip(got.skip, bwb_id)
            return got.records

        # Side by side: a regulation is up to three requests, each slower than the pace the
        # hosts ask for (3.9 regulations a second in the rebuild, at 0.1 s a request).
        # Listed by the SRU, a toestand without a file is asked for again in a few days.
        yield from self._download_each(
            bwb_ids,
            download,
            records,
            label="BWB",
            missing=lambda bwb_id, status: missing_record(
                SOURCE_BWB, RAW_KIND_BWB_TOESTAND, bwb_id, listed=True, status=status
            ),
            workers=FETCH_WORKERS,
        )

    def _stored_toestanden(self) -> dict[str, dict[str, Any]]:
        """``{bwb_id: {url, end_date, at}}`` of the stored current toestanden."""
        rows = raw_queries.toestand_state_urls(self.store)
        return {str(row["id"]): row for row in rows if row.get("url")}

    def _add_wti_general_info(self, meta: ToestandMeta, got: _Download) -> None:
        """The WTI general information (official abbreviations) of one regulation.

        It is a by-product of the regulation: a failure is a problem of *got* and leaves the
        toestand alone, and the record does not count as progress.
        """
        bwb_id = meta["bwb_id"]
        try:
            general_info = self.client.fetch_wti_general_info(meta)
        except DOWNLOAD_FAILURES as exc:  # the toestand is kept without its WTI
            got.problem = f"WTI general information not fetched ({failure_reason(exc)})"
            return
        if general_info is None:
            logger.debug("No WTI general information for %s.", bwb_id)
            return
        got.records.append(
            RetrieveRecord(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_WTI_GENERAL,
                external_id=bwb_id,
                payload_text=general_info,
                meta={"bwb_id": bwb_id, "wti_url": meta.get("locatie_wti")},
                counts=False,
            )
        )

    def run_history(
        self,
        *,
        bwb_ids: Sequence[str] | None = None,
        refetch: bool = False,
        since: dt.datetime | None = None,
        **kwargs: object,
    ) -> PipelineResult:
        """Fetch and store the historical toestanden of *bwb_ids* that are not stored yet.

        Without *bwb_ids*: every regulation of which the current toestand is stored (what
        ``retrieve bwb`` loaded). A new regulation has none stored, so it gets all of them;
        *refetch* downloads every toestand again. Each is a record of its own, keyed by
        ``{bwb_id}@{start_date}``. With *since* (and neither of the two) the SRU is asked
        only for what it changed since then, and for every toestand of a regulation that has
        none in the history yet: a new toestand changes the regulation's record that day,
        an old toestand of a regulation ``bwb`` stored since does not.
        """
        normalized = (
            clean_ids(bwb_ids) if bwb_ids else sorted(self._stored_toestanden())
        )
        if not normalized:
            logger.warning("BWB history retrieve: no IDs to process.")
            return PipelineResult()

        stored = (
            set()
            if refetch
            else self._stored_ids(SOURCE_BWB, RAW_KIND_BWB_TOESTAND_ALL)
        )
        logger.info(
            "Starting BWB history retrieve for %d IDs (%d toestanden stored).",
            len(normalized),
            len(stored),
        )
        listing = (
            self._changed_since(normalized, stored, since.date())
            if since and not bwb_ids and not refetch
            else self._toestanden_of(normalized)
        )
        return self._store_all(self._fetch_history(listing, stored), what="toestanden")

    def _changed_since(
        self, bwb_ids: Sequence[str], stored: set[str], day: dt.date
    ) -> Iterator[tuple[str, list[ToestandMeta]]]:
        """The toestanden the SRU changed since *day* of the regulations of *bwb_ids* that
        have a history, and every toestand of those that have none."""
        known = {key.split("@", 1)[0] for key in stored}
        changed = self.client.enumerate_modified(day)
        for bwb_id in bwb_ids:
            if bwb_id in known and bwb_id in changed:
                yield bwb_id, changed[bwb_id]
        yield from self._toestanden_of([b for b in bwb_ids if b not in known])

    def _toestanden_of(
        self, bwb_ids: Sequence[str]
    ) -> Iterator[tuple[str, list[ToestandMeta]]]:
        """Every toestand of each regulation: from one SRU listing of all of them when there
        are that many regulations, else from one SRU query per regulation."""
        if len(bwb_ids) >= HISTORY_LISTING_FROM:
            listed = self.client.enumerate_toestanden()
            for bwb_id in bwb_ids:
                yield bwb_id, listed.get(bwb_id, [])
            return
        streak = FailureStreak("BWB SRU")
        for bwb_id in bwb_ids:
            try:
                toestanden = self.client.search_toestanden(bwb_id)
            except DOWNLOAD_FAILURES as exc:
                self.progress.fail(
                    f"toestanden list not fetched ({failure_reason(exc)})", bwb_id
                )
                streak.failed(bwb_id, exc)
                continue
            streak.ok()
            yield bwb_id, toestanden

    def _fetch_history(
        self,
        listing: Iterator[tuple[str, list[ToestandMeta]]],
        stored: set[str],
    ) -> Iterator[RetrieveRecord]:
        """The toestanden of *listing* (per regulation) whose key is not in *stored*,
        downloaded side by side."""
        todo: dict[str, ToestandMeta] = {}
        for bwb_id, toestanden in listing:
            if not toestanden:
                self.progress.skip("no toestanden in the SRU", bwb_id)
            for meta in toestanden:
                if not meta.get("geldigheidsperiode_startdatum"):
                    # it has no place in the history of the regulation
                    self.progress.skip("no start date in the SRU", bwb_id)
                    continue
                external_id = _history_id(meta)
                if external_id not in stored:
                    todo.setdefault(external_id, meta)
        wanted = self._without_missing(
            SOURCE_BWB, RAW_KIND_BWB_TOESTAND_ALL, list(todo)
        )
        logger.info("%d toestanden are not stored yet.", len(wanted))

        def download(external_id: str) -> str:
            return self.client.fetch_toestand_xml(todo[external_id])

        def records(external_id: str, xml_text: str) -> list[RetrieveRecord]:
            meta = todo[external_id]
            return [
                RetrieveRecord(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND_ALL,
                    external_id=external_id,
                    payload_text=xml_text,
                    meta={
                        "bwb_id": meta["bwb_id"],
                        "state_url": meta["locatie_toestand"],
                        "start_date": meta["geldigheidsperiode_startdatum"],
                        "end_date": meta.get("geldigheidsperiode_einddatum"),
                    },
                )
            ]

        yield from self._download_each(
            wanted,
            download,
            records,
            label="BWB",
            missing=lambda external_id, status: missing_record(
                SOURCE_BWB,
                RAW_KIND_BWB_TOESTAND_ALL,
                external_id,
                listed=True,
                status=status,
            ),
            workers=FETCH_WORKERS,
        )

    def run_full(self) -> PipelineResult:
        """Full-load mode: every regulation the SRU lists (``BWBClient.enumerate_latest``,
        with its current toestand), downloaded when new or changed. Safe to interrupt and
        re-run."""

        def listing() -> Iterator[RetrieveRecord]:
            current = listed(self.client.enumerate_latest(), "BWB regulations")
            logger.info("BWB full-load: %d regulations listed.", len(current))
            yield from self._fetch_current(list(current), current)

        return self._store_all(listing(), what="regulations")
