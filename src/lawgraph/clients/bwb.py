from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Callable, TypedDict

from requests import Session

from lawgraph.clients._sru import _local_name
from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import BWB_BASE_URL, BWB_SRU_ENDPOINT
from lawgraph.core.logging import get_logger

# Structural changes:
# - SRU endpoint and base URL now live in lawgraph.config.settings.
# - Added docstrings to the public helpers managing BWB toestanden.


logger = get_logger(__name__)


class ToestandMeta(TypedDict):
    bwb_id: str
    locatie_toestand: str
    locatie_wti: str | None
    locatie_manifest: str | None
    geldigheidsperiode_startdatum: str | None
    geldigheidsperiode_einddatum: str | None


class BWBClient(BaseClient):
    """
    Client voor wetten.overheid.nl zodat we BWB-toestanden via SRU en XML kan ophalen.
    """

    def __init__(self, session: Session | None = None) -> None:
        """Configure the BWB client with optional shared requests Session."""
        super().__init__(
            env_var="BWB_BASE",
            default_base_url=BWB_BASE_URL,
            session=session,
        )

    def enumerate_all_ids(
        self,
        *,
        types: tuple[str, ...] = ("wet", "amvb", "ministerieelebesluit", "regeling"),
        max_records: int = 50000,
    ) -> list[str]:
        """Enumerate all BWBR IDs via SRU wildcard queries, one query per document type.

        The SRU service at zoekservice.overheid.nl supports CQL queries with
        ``dcterms.type=<type>`` and paginates via ``startRecord``. We collect
        all distinct BWBR IDs across the requested document types.

        ``max_records`` is a safety cap per type to avoid runaway fetches.
        """
        all_ids: list[str] = []
        seen: set[str] = set()
        page_size = 100

        for doc_type in types:
            logger.info("Enumerating BWB IDs for type=%s", doc_type)
            start = 1
            while start <= max_records:
                params = {
                    "operation": "searchRetrieve",
                    "version": "1.2",
                    "x-connection": "BWB",
                    "query": f"dcterms.type={doc_type}",
                    "maximumRecords": str(page_size),
                    "startRecord": str(start),
                    "recordSchema": "http://standaarden.overheid.nl/sru",
                }
                try:
                    resp = self._get_raw_absolute_with_retry(
                        BWB_SRU_ENDPOINT, params=params, timeout=60
                    )
                    root = ET.fromstring(resp.text)
                except Exception as exc:
                    logger.warning(
                        "SRU enumeration error (type=%s, start=%d): %s",
                        doc_type,
                        start,
                        exc,
                    )
                    break

                records_on_page: list[str] = []
                for element in root.iter():
                    if _local_name(element.tag) != "record":
                        continue
                    meta = self._parse_record(element)
                    if meta and meta["bwb_id"]:
                        records_on_page.append(meta["bwb_id"])
                        if meta["bwb_id"] not in seen:
                            seen.add(meta["bwb_id"])
                            all_ids.append(meta["bwb_id"])

                if len(records_on_page) < page_size:
                    break
                start += page_size

            logger.info(
                "Enumerated %d unique BWB IDs so far (type=%s done).",
                len(all_ids),
                doc_type,
            )

        logger.info("BWB enumeration complete: %d unique IDs total.", len(all_ids))
        return all_ids

    def search_toestanden(self, bwb_id: str) -> list[ToestandMeta]:
        """Search the BWB SRU endpoint for all available toestanden for a BWBR ID."""
        params = {
            "operation": "searchRetrieve",
            "version": "1.2",
            "x-connection": "BWB",
            "query": f"dcterms.identifier=={bwb_id}",
            "maximumRecords": "500",
        }
        logger.debug("SRU Search voor %s (%s)", bwb_id, params)
        resp = self._get_raw_absolute_with_retry(
            BWB_SRU_ENDPOINT, params=params, timeout=30
        )

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            logger.error("Kon SRU-antwoord voor %s niet parsen: %s", bwb_id, exc)
            return []

        toestanden: list[ToestandMeta] = []
        for element in root.iter():
            if _local_name(element.tag) != "record":
                continue
            meta = self._parse_record(element)
            if meta:
                toestanden.append(meta)
        return toestanden

    def latest_toestand(self, bwb_id: str) -> ToestandMeta | None:
        """Return the most recent valid toestand metadata for a BWB ID."""
        toestanden = self.search_toestanden(bwb_id)
        if not toestanden:
            logger.warning("Geen BWB-toestand gevonden voor %s", bwb_id)
            return None

        def sort_key(meta: ToestandMeta) -> tuple[dt.date, dt.date]:
            return (
                self._date_for_sort(meta.get("geldigheidsperiode_einddatum")),
                self._date_for_sort(meta.get("geldigheidsperiode_startdatum")),
            )

        still_valid = [
            meta
            for meta in toestanden
            if meta.get("geldigheidsperiode_einddatum") == "9999-12-31"
        ]
        candidates = still_valid if still_valid else toestanden
        selected = sorted(candidates, key=sort_key, reverse=True)[0]

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
        return resp.text

    def _parse_record(self, record: ET.Element) -> ToestandMeta | None:
        """Extract identifiers and URIs from a single SRU record element."""
        field_values: dict[str, str | None] = {
            "bwb_id": None,
            "locatie_toestand": None,
            "locatie_wti": None,
            "locatie_manifest": None,
            "geldigheidsperiode_startdatum": None,
            "geldigheidsperiode_einddatum": None,
        }

        def _set_if_missing(key: str, value: str) -> None:
            if not field_values[key]:
                field_values[key] = value

        handlers: dict[str, Callable[[str], None]] = {
            "bwb-id": lambda value: _set_if_missing("bwb_id", value),
            "identifier": lambda value: _set_if_missing("bwb_id", value),
            "locatie_toestand": lambda value: _set_if_missing(
                "locatie_toestand", value
            ),
            "locatie_wti": lambda value: _set_if_missing("locatie_wti", value),
            "locatie_manifest": lambda value: _set_if_missing(
                "locatie_manifest", value
            ),
            "geldigheidsperiode_startdatum": lambda value: _set_if_missing(
                "geldigheidsperiode_startdatum", value
            ),
            "geldigheidsperiode_einddatum": lambda value: _set_if_missing(
                "geldigheidsperiode_einddatum", value
            ),
        }

        for element in record.iter():
            text = (element.text or "").strip()
            if not text:
                continue
            handler = handlers.get(_local_name(element.tag))
            if handler:
                handler(text)

        if not field_values["bwb_id"] or not field_values["locatie_toestand"]:
            return None

        return {
            "bwb_id": field_values["bwb_id"],
            "locatie_toestand": field_values["locatie_toestand"],
            "locatie_wti": field_values["locatie_wti"],
            "locatie_manifest": field_values["locatie_manifest"],
            "geldigheidsperiode_startdatum": field_values[
                "geldigheidsperiode_startdatum"
            ],
            "geldigheidsperiode_einddatum": field_values[
                "geldigheidsperiode_einddatum"
            ],
        }

    @staticmethod
    def _date_for_sort(value: str | None) -> dt.date:
        """Coerce possibly missing dates into sortable dt.date values."""
        if not value:
            return dt.date.min
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return dt.date.min
