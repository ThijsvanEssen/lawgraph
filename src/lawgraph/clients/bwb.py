from __future__ import annotations

import datetime as dt
import time
import xml.etree.ElementTree as ET
from typing import TypedDict

from requests import Session

from lawgraph.clients._sru import number_of_records, parse_response, records, sru_params
from lawgraph.clients.base import QUERY_TIMEOUT, BaseClient, UnexpectedAnswer
from lawgraph.config.constants import BWB_INSTRUMENT_TYPES
from lawgraph.config.sources import BWB_SEARCH, BWB_SRU
from lawgraph.core.bwb_wti import GENERAL_INFO_END, extract_general_info
from lawgraph.core.logging import get_logger
from lawgraph.core.time import sortable_date
from lawgraph.core.xml import local_name

logger = get_logger(__name__)


# The SRU service returns at most 5000 records per page and silently caps larger
# requests, so stay well below it.
SRU_PAGE_SIZE = 1000
# The toestanden of one regulation are asked for in one page of this many.
TOESTANDEN_PAGE_SIZE = 500
# A safety cap on the records listed of one type (not ids).
MAX_RECORDS_PER_TYPE = 150_000

# A WTI file is read in chunks until its first element is complete. That element is a few
# KB; the limit only stops a file without it from being downloaded whole.
WTI_CHUNK_SIZE = 8192
WTI_HEAD_LIMIT = 1_000_000
# The page sizes tried for a page the service answers empty: the big pages (3 MB) are the ones
# it fails on.
EMPTY_PAGE_SIZES = (SRU_PAGE_SIZE, SRU_PAGE_SIZE, 500, 250, 100, 50)
# How often a type is listed before a listing that stays short is an error.
LISTING_ATTEMPTS = 3


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


def current_toestand(
    toestanden: list[ToestandMeta], today: dt.date | None = None
) -> ToestandMeta | None:
    """The toestand of *toestanden* that counts as current (``_currency``); of two equal
    ones the first. None for none."""
    day = today or dt.date.today()
    return max(toestanden, key=lambda meta: _currency(meta, day), default=None)


class BWBClient(BaseClient):
    """Client for the BWB: the toestanden of the regulations from its SRU, and their XML
    and WTI files from the repository the records point to."""

    def __init__(self, session: Session | None = None) -> None:
        super().__init__(base_url=BWB_SEARCH.base_url, session=session)

    def _sru_page(self, doc_type: str, start: int) -> ET.Element:
        """One result page of a type. The service sometimes answers a page that is valid but
        empty although records remain (it reports ``numberOfRecords`` and a next position);
        that is retried with smaller pages, and raised when it persists: taking it for the end
        of the list left out most of the large laws.
        """
        for attempt, size in enumerate(EMPTY_PAGE_SIZES):
            params = sru_params(
                f'dcterms.type=="{doc_type}"', size=size, start=start, connection="BWB"
            )
            resp = self.get(BWB_SRU, params=params, timeout=QUERY_TIMEOUT)
            root = parse_response(
                resp.content, context=f"BWB type={doc_type} start={start}"
            )
            if start > number_of_records(root) or records(root):
                return root
            if attempt + 1 == len(EMPTY_PAGE_SIZES):
                break
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

    def _toestanden_of_type(
        self, doc_type: str, max_records: int
    ) -> dict[str, ToestandMeta]:
        """Every toestand of *doc_type* by its location; raises when the listing is short.

        The service does not sort and cannot be asked to, and under load it has answered
        records it had given before for a later page: 25,000 records for a total of 24,216,
        holding 1,335 of the 3,204 laws. A toestand has a location of its own, so the
        listing is complete when it holds as many locations as the service reports; a
        short one is listed again, and what is still short after that is an error.
        """
        toestanden: dict[str, ToestandMeta] = {}
        total = 0
        for attempt in range(1, LISTING_ATTEMPTS + 1):
            total = self._list_into(toestanden, doc_type, max_records)
            if len(toestanden) >= total:
                return toestanden
            logger.warning(
                "BWB SRU (type=%s): %d of %d toestanden after listing %d: pages were "
                "repeated or lost; listing it again.",
                doc_type,
                len(toestanden),
                total,
                attempt,
            )
        raise RuntimeError(
            f"BWB SRU error (type={doc_type}): {len(toestanden)} of {total} toestanden "
            f"after {LISTING_ATTEMPTS} listings: the listing is not complete"
        )

    def _list_into(
        self, toestanden: dict[str, ToestandMeta], doc_type: str, max_records: int
    ) -> int:
        """Walk the pages of *doc_type* once, adding to *toestanden*; the reported total."""
        total = 0
        start = 1
        while start <= max_records:
            root = self._sru_page(doc_type, start)
            total = number_of_records(root)
            page = records(root)
            for element in page:
                meta = self._parse_record(element)
                if meta and meta["bwb_id"]:
                    toestanden[meta["locatie_toestand"]] = meta
            start += len(page)
            if start > total:
                break
        return total

    def enumerate_toestanden(
        self,
        *,
        types: tuple[str, ...] = BWB_INSTRUMENT_TYPES,
        max_records: int = MAX_RECORDS_PER_TYPE,
    ) -> dict[str, list[ToestandMeta]]:
        """Every toestand of every regulation, by BWBR id, one SRU query per ``dcterms.type``.

        The SRU service at zoekservice.overheid.nl returns one record per *toestand*
        (version), so a regulation has as many records as it has toestanden. Type values are
        case-sensitive (``AMvB``, ``ministeriele-regeling``). A service error
        (``<diagnostic>``) raises instead of silently yielding an empty listing.

        ``max_records`` is a safety cap per type on *records* (not ids).
        """
        by_id: dict[str, list[ToestandMeta]] = {}
        for doc_type in types:
            logger.info("Enumerating BWB toestanden for type=%s", doc_type)
            toestanden = self._toestanden_of_type(doc_type, max_records)
            for meta in toestanden.values():
                by_id.setdefault(meta["bwb_id"], []).append(meta)
            logger.info(
                "Enumerated %d unique BWB IDs so far (type=%s done, %d toestanden).",
                len(by_id),
                doc_type,
                len(toestanden),
            )
        logger.info("BWB enumeration complete: %d unique IDs total.", len(by_id))
        return by_id

    def enumerate_latest(
        self,
        *,
        types: tuple[str, ...] = BWB_INSTRUMENT_TYPES,
        max_records: int = MAX_RECORDS_PER_TYPE,
    ) -> dict[str, ToestandMeta]:
        """The current toestand of every regulation, picked from ``enumerate_toestanden``.

        The listing already holds every toestand of every regulation, so asking the SRU for
        the current one per regulation (``latest_toestand``) is one request per regulation
        that tells nothing new.
        """
        today = dt.date.today()
        found = self.enumerate_toestanden(types=types, max_records=max_records)
        return {
            bwb_id: meta
            for bwb_id, toestanden in found.items()
            if (meta := current_toestand(toestanden, today)) is not None
        }

    def search_toestanden(self, bwb_id: str) -> list[ToestandMeta]:
        """Search the BWB SRU endpoint for all available toestanden for a BWBR ID."""
        params = sru_params(
            f"dcterms.identifier=={bwb_id}",
            size=TOESTANDEN_PAGE_SIZE,
            connection="BWB",
        )
        resp = self.get(BWB_SRU, params=params)
        root = parse_response(resp.content, context=f"BWB toestanden of {bwb_id}")
        total = number_of_records(root)
        if total > TOESTANDEN_PAGE_SIZE:
            # One page is asked for; more toestanden than that would be cut silently.
            raise UnexpectedAnswer(
                f"BWB {bwb_id} has {total} toestanden, more than one page"
            )
        return [meta for meta in map(self._parse_record, records(root)) if meta]

    def latest_toestand(self, bwb_id: str) -> ToestandMeta | None:
        """Return the most recent valid toestand metadata for a BWB ID."""
        selected = current_toestand(self.search_toestanden(bwb_id))
        if selected is None:
            logger.debug("No BWB toestand found for %s", bwb_id)
            return None

        logger.debug(
            "Chose the toestand of %s: %s to %s",
            bwb_id,
            selected.get("geldigheidsperiode_startdatum"),
            selected.get("geldigheidsperiode_einddatum"),
        )
        return selected

    def fetch_toestand_xml(self, meta: ToestandMeta) -> str:
        """The XML of the toestand at the location of *meta*."""
        logger.debug(
            "Downloading the toestand XML of %s from %s",
            meta["bwb_id"],
            meta["locatie_toestand"],
        )
        return self.get_xml(meta["locatie_toestand"])

    def fetch_wti_general_info(self, meta: ToestandMeta) -> str | None:
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
        resp = self.get(url, stream=True)
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
