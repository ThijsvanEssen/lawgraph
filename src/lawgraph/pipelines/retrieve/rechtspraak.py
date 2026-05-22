from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from typing import Any

from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.config.constants import (
    RAW_KIND_RS_CONTENT,
    RAW_KIND_RS_INDEX,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class RechtspraakRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline that handles Rechtspraak index snapshots and contents."""

    def __init__(
        self, store: ArangoStore, rs_client: RechtspraakClient | None = None
    ) -> None:
        super().__init__(store)
        self.rs = rs_client or RechtspraakClient()

    def fetch(
        self,
        *args: object,
        fetch_index: bool = False,
        since: dt.datetime | None = None,
        extra_params: dict[str, Any] | None = None,
        eclis: Sequence[str] | None = None,
        **kwargs: object,
    ) -> Sequence[RetrieveRecord]:
        """Return raw_records for Rechtspraak index snapshots and specific ECLI content."""
        logger.info(
            "Fetching Rechtspraak data (index=%s, eclis=%d).",
            fetch_index,
            len(eclis) if eclis else 0,
        )
        records: list[RetrieveRecord] = []

        if fetch_index:
            xml_index = self.rs.fetch_ecli_index_xml(
                modified_since=since,
                extra_params=extra_params,
            )
            records.append(
                RetrieveRecord(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_INDEX,
                    external_id=None,
                    payload_text=xml_index,
                    meta={
                        "modified_since": since.isoformat() if since else None,
                        "extra_params": extra_params,
                    },
                )
            )

        if eclis:
            for ecli in eclis:
                try:
                    xml = self.rs.fetch_ecli_content(ecli)
                except Exception as exc:
                    logger.warning("Skipping ECLI %s: %s", ecli, exc)
                    continue
                records.append(
                    RetrieveRecord(
                        source=SOURCE_RECHTSPRAAK,
                        kind=RAW_KIND_RS_CONTENT,
                        external_id=ecli,
                        payload_text=xml,
                        meta={"ecli": ecli},
                    )
                )

        index_count = sum(1 for rec in records if rec.kind == RAW_KIND_RS_INDEX)
        content_count = sum(1 for rec in records if rec.kind == RAW_KIND_RS_CONTENT)
        logger.info(
            "Rechtspraak retrieve created %d records (%d index, %d content).",
            len(records),
            index_count,
            content_count,
        )
        return records

    def run_full(
        self,
        *,
        extra_params: dict[str, Any] | None = None,
        max_records: int = 5_000_000,
    ) -> PipelineResult:
        """Full-load mode: paginate the entire Rechtspraak index without a date filter.

        Fetches index pages with ``max=1000`` and ``from=N`` until a page smaller than
        the page size is returned or ``max_records`` is reached.  Each page is stored as
        a separate ``RAW_KIND_RS_INDEX`` raw record keyed by its offset so re-runs are
        idempotent.
        """
        result = PipelineResult()
        page_size = 1000
        start = 0

        logger.info("Rechtspraak full-load: starting paginated index retrieval.")

        while start < max_records:
            params: dict[str, Any] = dict(extra_params or {})
            params["max"] = str(page_size)
            params["from"] = str(start)

            try:
                xml_text = self.rs.fetch_ecli_index_xml(
                    modified_since=None, extra_params=params
                )
            except Exception as exc:
                msg = f"Rechtspraak index fetch failed (from={start}): {exc}"
                logger.error(msg)
                result.add_error(msg)
                break

            entry_count = self._count_index_entries(xml_text)
            record = RetrieveRecord(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_INDEX,
                external_id=f"full_page_{start}",
                payload_text=xml_text,
                meta={"from": start, "max": page_size, "full_load": True},
            )
            try:
                self._insert(record)
                result.created += 1
            except Exception as exc:
                msg = f"Could not store Rechtspraak index page (from={start}): {exc}"
                logger.error(msg)
                result.add_error(msg)

            logger.info(
                "Rechtspraak full-load: stored index page from=%d (%d entries).",
                start,
                entry_count,
            )

            if entry_count < page_size:
                break
            start += page_size

        logger.info(
            "Rechtspraak full-load completed: %d pages stored, %d errors.",
            result.created,
            len(result.errors),
        )
        return result

    @staticmethod
    def _count_index_entries(xml_text: str) -> int:
        """Count Atom <entry> elements in an index page XML string."""
        try:
            root = ET.fromstring(xml_text)
            return sum(
                1
                for el in root
                if (el.tag.split("}", 1)[-1] if "}" in el.tag else el.tag) == "entry"
            )
        except ET.ParseError:
            return xml_text.count("<entry>")
