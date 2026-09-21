from __future__ import annotations

import datetime as dt
import time
import xml.etree.ElementTree as ET
from typing import TypedDict

from requests import Session

from lawgraph.clients._sru import number_of_records, parse_response
from lawgraph.clients.base import BaseClient, response_text
from lawgraph.config.constants import BWB_INSTRUMENT_TYPES
from lawgraph.config.settings import BWB_BASE_URL, BWB_SRU_ENDPOINT
from lawgraph.core.bwb_wti import GENERAL_INFO_END, extract_general_info
from lawgraph.core.logging import get_logger
from lawgraph.core.time import sortable_date
from lawgraph.core.xml import local_name

# Structural changes:
# - SRU endpoint and base URL now live in lawgraph.config.settings.
# - Added docstrings to the public helpers managing BWB toestanden.


logger = get_logger(__name__)


# The SRU service returns at most 5000 records per page and silently caps larger
# requests, so stay well below it.
SRU_PAGE_SIZE = 1000

# A WTI file is read in chunks until its first element is complete. That element is a few
# KB; the limit only stops a file without it from being downloaded whole.
WTI_CHUNK_SIZE = 8192
WTI_HEAD_LIMIT = 1_000_000
# The page sizes tried for a page the service answers empty: the big pages (3 MB) are the ones
# it fails on.
EMPTY_PAGE_SIZES = (SRU_PAGE_SIZE, SRU_PAGE_SIZE, 500, 250, 100, 50)


# Element of an SRU record -> field of ``ToestandMeta``.
_RECORD_FIELDS = {
    "bwb-id": "bwb_id",
    "identifier": "bwb_id",
    "title": "title",
    "locatie_toestand": "locatie_toestand",
    "locatie_wti": "locatie_wti",
    "locatie_manifest": "locatie_manifest",
    "geldigheidsperiode_startdatum": "geldigheidsperiode_startdatum",
    "geldigheidsperiode_einddatum": "geldigheidsperiode_einddatum",
}


class ToestandMeta(TypedDict):
    bwb_id: str
    title: str | None
    locatie_toestand: str
    locatie_wti: str | None
    locatie_manifest: str | None
    geldigheidsperiode_startdatum: str | None
    geldigheidsperiode_einddatum: str | None


def _currency(
    meta: ToestandMeta, today: dt.date
) -> tuple[bool, bool, dt.date, dt.date]:
    """Sorts the toestand that counts as current last.

    The one in force today; without one (a repealed regulation) the last that was, before
    any that is still to come. The SRU also lists the toestanden of the future, and one of
    those runs to 9999-12-31 just like the current one used to: "still valid, latest start"
    picked the text of next year for a regulation that is about to change.
    """
    start = sortable_date(meta.get("geldigheidsperiode_startdatum"))
    end = sortable_date(meta.get("geldigheidsperiode_einddatum"))
    return (start <= today <= end, start <= today, end, start)


def _newer(
    meta: ToestandMeta, than: ToestandMeta, today: dt.date | None = None
) -> bool:
    today = today or dt.date.today()
    return _currency(meta, today) > _currency(than, today)


class BWBClient(BaseClient):
    """
    Client voor wetten.overheid.nl zodat we BWB-toestanden via SRU en XML kan ophalen.
    """

    def __init__(self, session: Session | None = None) -> None:
        """Configure the BWB client with optional shared requests Session."""
        super().__init__(
            base_url=BWB_BASE_URL,
            session=session,
        )

    def _sru_page(self, doc_type: str, start: int) -> ET.Element:
        """One result page of a type. The service sometimes answers a page that is valid but
        empty although records remain (it reports ``numberOfRecords`` and a next position);
        that is retried with smaller pages, and raised when it persists: taking it for the end
        of the list left out most of the large laws.
        """
        params = {
            "operation": "searchRetrieve",
            "version": "1.2",
            "x-connection": "BWB",
            "query": f'dcterms.type=="{doc_type}"',
            "maximumRecords": str(SRU_PAGE_SIZE),
            "startRecord": str(start),
        }
        for attempt, size in enumerate(EMPTY_PAGE_SIZES):
            params["maximumRecords"] = str(size)
            resp = self._get_raw_absolute_with_retry(
                BWB_SRU_ENDPOINT, params=params, timeout=120
            )
            root = parse_response(
                resp.content, context=f"BWB type={doc_type} start={start}"
            )
            if start > number_of_records(root) or any(
                local_name(e.tag) == "record" for e in root.iter()
            ):
                return root
            logger.warning(
                "BWB SRU returned an empty page at startRecord=%d of type=%s "
                "(%d records asked); trying again with a smaller page.",
                start,
                doc_type,
                size,
            )
            time.sleep(min(2**attempt, 8))
        raise RuntimeError(
            f"BWB SRU error (type={doc_type}): an empty page at startRecord={start} "
            "although records remain"
        )

    def enumerate_all_ids(
        self,
        *,
        types: tuple[str, ...] = BWB_INSTRUMENT_TYPES,
        max_records: int = 150_000,
    ) -> list[str]:
        """Every BWBR id of the SRU catalogue, in the order of ``enumerate_latest``."""
        return list(self.enumerate_latest(types=types, max_records=max_records))

    def enumerate_latest(
        self,
        *,
        types: tuple[str, ...] = BWB_INSTRUMENT_TYPES,
        max_records: int = 150_000,
    ) -> dict[str, ToestandMeta]:
        """The current toestand of every regulation, one SRU query per ``dcterms.type``.

        The listing already holds every toestand of every regulation, so the current one
        (``_newer``) is picked while it is read: asking the SRU for it again per regulation
        (``latest_toestand``) is one request per regulation that tells nothing new.

        The SRU service at zoekservice.overheid.nl returns one record per
        *toestand* (version), so many pages repeat the same BWBR id; the result
        is de-duplicated. Type values are case-sensitive (``AMvB``,
        ``ministeriele-regeling``). A service error (``<diagnostic>``) raises
        instead of silently yielding an empty list.

        ``max_records`` is a safety cap per type on *records* (not ids).
        """
        latest: dict[str, ToestandMeta] = {}

        for doc_type in types:
            logger.info("Enumerating BWB IDs for type=%s", doc_type)
            fetched = 0
            total = 0
            start = 1
            while start <= max_records:
                root = self._sru_page(doc_type, start)
                total = number_of_records(root)
                records = [e for e in root.iter() if local_name(e.tag) == "record"]
                for element in records:
                    meta = self._parse_record(element)
                    if meta and meta["bwb_id"]:
                        known = latest.get(meta["bwb_id"])
                        if known is None or _newer(meta, known):
                            latest[meta["bwb_id"]] = meta
                fetched += len(records)
                start += len(records)
                if start > total:
                    break
            else:
                logger.warning(
                    "BWB enumeration hit max_records=%d for type=%s; ids may be missing.",
                    max_records,
                    doc_type,
                )
            if start <= max_records and fetched < total:
                raise RuntimeError(
                    f"BWB SRU error (type={doc_type}): {fetched} records read, the "
                    f"service reports {total}"
                )
            if fetched > total:
                # the toestanden change while they are listed, and a page can overlap
                logger.warning(
                    "BWB SRU (type=%s): %d records read for a reported total of %d.",
                    doc_type,
                    fetched,
                    total,
                )

            logger.info(
                "Enumerated %d unique BWB IDs so far (type=%s done, %d toestanden).",
                len(latest),
                doc_type,
                fetched,
            )

        logger.info("BWB enumeration complete: %d unique IDs total.", len(latest))
        return latest

    def search_toestanden(self, bwb_id: str) -> list[ToestandMeta]:
        """Search the BWB SRU endpoint for all available toestanden for a BWBR ID."""
        params = {
            "operation": "searchRetrieve",
            "version": "1.2",
            "x-connection": "BWB",
            "query": f"dcterms.identifier=={bwb_id}",
            "maximumRecords": "500",
        }
        logger.debug("SRU search for %s (%s)", bwb_id, params)
        resp = self._get_raw_absolute_with_retry(
            BWB_SRU_ENDPOINT, params=params, timeout=30
        )

        root = parse_response(resp.content, context=f"BWB toestanden of {bwb_id}")
        total = number_of_records(root)
        if total > 500:
            # One page of 500 is asked for; more toestanden than that would be cut silently.
            raise RuntimeError(
                f"BWB {bwb_id} has {total} toestanden, more than one page"
            )

        toestanden: list[ToestandMeta] = []
        for element in root.iter():
            if local_name(element.tag) != "record":
                continue
            meta = self._parse_record(element)
            if meta:
                toestanden.append(meta)
        return toestanden

    def latest_toestand(self, bwb_id: str) -> ToestandMeta | None:
        """Return the most recent valid toestand metadata for a BWB ID."""
        toestanden = self.search_toestanden(bwb_id)
        if not toestanden:
            logger.debug("No BWB toestand found for %s", bwb_id)
            return None

        selected = toestanden[0]
        for meta in toestanden[1:]:
            if _newer(meta, selected):
                selected = meta

        logger.debug(
            "Gekozen toestand voor %s -> %s / %s",
            bwb_id,
            selected.get("geldigheidsperiode_startdatum"),
            selected.get("geldigheidsperiode_einddatum"),
        )
        return selected

    def fetch_toestand_xml(
        self,
        meta: ToestandMeta,
        timeout: float | None = None,
    ) -> str:
        """Download the raw toestand XML payload referenced in the metadata."""
        url = meta["locatie_toestand"]
        actual_timeout = timeout if timeout is not None else 30
        logger.debug(
            "Downloaden toestand XML voor %s van %s",
            meta["bwb_id"],
            url,
        )
        resp = self._get_raw_absolute_with_retry(url, timeout=actual_timeout)
        return response_text(resp)

    def fetch_wti_general_info(
        self,
        meta: ToestandMeta,
        timeout: int = 30,
    ) -> str | None:
        """The ``<algemene-informatie>`` element of the regulation's WTI file, verbatim.

        It holds the official abbreviations and is the first element of the file. The
        rest (amendment log, related regulations) runs to tens of MB, so the download
        stops as soon as the element is complete. ``None`` when the SRU record names no
        WTI file or the file has no such element.
        """
        url = meta.get("locatie_wti")
        if not url:
            return None
        logger.debug("Downloading WTI head for %s from %s", meta["bwb_id"], url)
        resp = self._get_raw_absolute_with_retry(url, timeout=timeout, stream=True)
        end_tag = GENERAL_INFO_END.encode()
        head = b""
        try:
            for chunk in resp.iter_content(chunk_size=WTI_CHUNK_SIZE):
                head += chunk
                if end_tag in head or len(head) >= WTI_HEAD_LIMIT:
                    break
        finally:
            resp.close()
        return extract_general_info(head.decode("utf-8", errors="replace"))

    def _parse_record(self, record: ET.Element) -> ToestandMeta | None:
        """The identifier, title, locations and validity of one SRU record."""
        values: dict[str, str] = {}
        for element in record.iter():
            key = _RECORD_FIELDS.get(local_name(element.tag))
            text = (element.text or "").strip()
            if key and text:
                values.setdefault(key, text)  # the first one counts
        if "bwb_id" not in values or "locatie_toestand" not in values:
            return None
        return {
            "bwb_id": values["bwb_id"],
            "title": values.get("title"),
            "locatie_toestand": values["locatie_toestand"],
            "locatie_wti": values.get("locatie_wti"),
            "locatie_manifest": values.get("locatie_manifest"),
            "geldigheidsperiode_startdatum": values.get(
                "geldigheidsperiode_startdatum"
            ),
            "geldigheidsperiode_einddatum": values.get("geldigheidsperiode_einddatum"),
        }
