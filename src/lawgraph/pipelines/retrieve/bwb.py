from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from lawgraph.clients.bwb import BWBClient, ToestandMeta
from lawgraph.config.constants import (
    COLLECTION_RAW_SOURCES,
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_BWB_WTI_GENERAL,
    SOURCE_BWB,
)
from lawgraph.core.identifiers import clean_ids
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore

from .base import (
    RetrievePipelineBase,
    RetrieveRecord,
    failure_reason,
    fetched_side_by_side,
)

logger = get_logger(__name__)

# The WTI file of an unchanged toestand is read again after this many days.
WTI_REFRESH_DAYS = 30


@dataclass
class _Download:
    """What the network gave for one regulation, to be reported by the loop that stores."""

    records: list[RetrieveRecord] = field(default_factory=list)
    skip: str | None = None
    fail: str | None = None
    problem: str | None = None


class BWBRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline that fetches BWB toestanden and WTI general information."""

    def __init__(
        self,
        store: ArangoStore,
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
        normalized = clean_ids(bwb_ids)
        result = PipelineResult()

        if not normalized:
            logger.warning("BWB retrieve: no IDs to process.")
            return result

        done = self._recently_stored(SOURCE_BWB, RAW_KIND_BWB_TOESTAND)
        todo = [bwb_id for bwb_id in normalized if bwb_id not in done]
        logger.info(
            "Starting BWB retrieve for %d IDs (%d already stored in the last 24 hours).",
            len(normalized),
            len(normalized) - len(todo),
        )
        return self._store_all(
            self._fetch_current(todo, current or {}), what="regulations"
        )

    def _fetch_current(
        self, bwb_ids: Sequence[str], current: Mapping[str, ToestandMeta]
    ) -> Iterator[RetrieveRecord]:
        """The WTI general information of each regulation, followed by its current toestand."""
        stored = self._stored_state_urls() if current else {}
        wti_fresh = (
            self._stored_since(
                SOURCE_BWB, RAW_KIND_BWB_WTI_GENERAL, hours=WTI_REFRESH_DAYS * 24
            )
            if current
            else set()
        )
        self.progress.expect(len(bwb_ids))

        def download(bwb_id: str) -> _Download:
            """What one regulation needs of the network; the outcome is reported below."""
            meta = current.get(bwb_id)
            if meta is not None and stored.get(bwb_id) == meta["locatie_toestand"]:
                # The same toestand as the stored one. Its WTI file can change on its own
                # (a new abbreviation), so that is read again once a month.
                got = _Download(skip="toestand unchanged since it was stored")
                if bwb_id not in wti_fresh:
                    self._add_wti_general_info(meta, got)
                return got
            if meta is None:
                try:
                    meta = self.client.latest_toestand(bwb_id)
                except Exception as exc:
                    reason = f"toestand metadata not fetched ({failure_reason(exc)})"
                    return _Download(fail=reason)
            if meta is None:
                return _Download(skip="no toestand in the SRU")
            xml_text = self.client.fetch_toestand_xml(meta)
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
                    },
                )
            )
            return got

        # Side by side: a regulation is up to three requests, each slower than the pace the
        # hosts ask for (3.9 regulations a second in the rebuild, at 0.1 s a request).
        for bwb_id, got in fetched_side_by_side(bwb_ids, download):
            if isinstance(got, Exception):
                self.progress.fail(f"download failed ({failure_reason(got)})", bwb_id)
                continue
            if got.problem:
                self.progress.problem(got.problem, bwb_id)
            if got.fail:
                self.progress.fail(got.fail, bwb_id)
                continue
            yield from got.records
            if got.skip:
                self.progress.skip(got.skip, bwb_id)

    def _stored_state_urls(self) -> dict[str, str]:
        """``{bwb_id: state_url}`` of the stored current toestanden."""
        aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind
            RETURN {{id: r.external_id, url: r.meta.state_url}}
        """
        rows = self.store.query(
            aql, {"source": SOURCE_BWB, "kind": RAW_KIND_BWB_TOESTAND}
        )
        return {str(row["id"]): str(row["url"]) for row in rows if row.get("url")}

    def _add_wti_general_info(self, meta: ToestandMeta, got: _Download) -> None:
        """The WTI general information (official abbreviations) of one regulation.

        It is a by-product of the regulation: a failure is a problem of *got* and leaves the
        toestand alone, and the record does not count as progress.
        """
        bwb_id = meta["bwb_id"]
        try:
            general_info = self.client.fetch_wti_general_info(meta)
        except Exception as exc:
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
        **kwargs: object,
    ) -> PipelineResult:
        """Fetch and store ALL historical BWB toestanden for given IDs.

        Each historical version is stored as a separate raw_source record keyed
        by ``{bwb_id}@{start_date}``.  Safe to re-run — ``_insert`` is
        upsert-based.
        """
        normalized = clean_ids(bwb_ids)
        result = PipelineResult()

        if not normalized:
            logger.warning("BWB history retrieve: no IDs to process.")
            return result

        logger.info("Starting BWB history retrieve for %d IDs.", len(normalized))
        return self._store_all(self._fetch_history(normalized), what="toestanden")

    def _fetch_history(self, bwb_ids: Sequence[str]) -> Iterator[RetrieveRecord]:
        """Every toestand of each regulation; how many there are is only known per regulation."""
        for bwb_id in bwb_ids:
            try:
                toestanden = self.client.search_toestanden(bwb_id)
            except Exception as exc:
                self.progress.fail(
                    f"toestanden list not fetched ({failure_reason(exc)})", bwb_id
                )
                continue
            if not toestanden:
                self.progress.skip("no toestanden in the SRU", bwb_id)
                continue

            for meta in toestanden:
                start_date = meta.get("geldigheidsperiode_startdatum") or "unknown"
                external_id = f"{bwb_id}@{start_date}"
                try:
                    xml_text = self.client.fetch_toestand_xml(meta)
                except Exception as exc:
                    self.progress.fail(
                        f"download failed ({failure_reason(exc)})", external_id
                    )
                    continue
                yield RetrieveRecord(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND_ALL,
                    external_id=external_id,
                    payload_text=xml_text,
                    meta={
                        "bwb_id": bwb_id,
                        "state_url": meta["locatie_toestand"],
                        "start_date": start_date,
                        "end_date": meta.get("geldigheidsperiode_einddatum"),
                    },
                )

    def run_history_full(self) -> PipelineResult:
        """Full-load mode: enumerate ALL BWB laws via SRU wildcard, then fetch all toestanden.

        Uses ``BWBClient.enumerate_all_ids()`` to discover every BWBR ID
        registered in the SRU catalogue, then calls ``run_history(bwb_ids=...)``
        to fetch all historical versions.  Safe to interrupt and re-run.
        """
        logger.info("BWB history full-load: enumerating all BWBR IDs via SRU wildcard.")
        try:
            all_ids = self.client.enumerate_all_ids()
        except Exception as exc:
            result = PipelineResult()
            msg = f"BWB SRU enumeration failed: {exc}"
            logger.error(msg)
            result.add_error(msg)
            return result

        logger.info(
            "BWB history full-load: %d IDs found; starting retrieval.", len(all_ids)
        )
        return self.run_history(bwb_ids=all_ids)

    def run_full(self) -> PipelineResult:
        """Full-load mode: enumerate ALL BWB laws via SRU wildcard, then fetch each.

        ``BWBClient.enumerate_latest()`` lists every regulation with its current toestand;
        ``run`` downloads those that are new or changed. Safe to interrupt and re-run.
        """
        logger.info("BWB full-load: enumerating all BWBR IDs via SRU wildcard.")
        try:
            current = self.client.enumerate_latest()
        except Exception as exc:
            result = PipelineResult()
            msg = f"BWB SRU enumeration failed: {exc}"
            logger.error(msg)
            result.add_error(msg)
            return result

        if not current:
            # Thousands of regulations exist: an empty listing is a broken question or a
            # broken source, not "nothing to do".
            result = PipelineResult()
            result.add_error("The BWB listing is empty; nothing was retrieved.")
            return result
        logger.info("BWB full-load: %d IDs found; starting retrieval.", len(current))
        return self.run(bwb_ids=list(current), current=current)
