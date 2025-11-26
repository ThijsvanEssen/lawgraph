from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.config.settings import (
    RAW_KIND_RS_CONTENT,
    RAW_KIND_RS_INDEX,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

from .base import RetrieveRecord, RetrievePipelineBase

logger = get_logger(__name__)


class RechtspraakRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline that handles Rechtspraak index snapshots and contents."""
    def __init__(self, store: ArangoStore, rs_client: RechtspraakClient | None = None) -> None:
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
            xml_index = self.rs.search_ecli_index(
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
                xml = self.rs.fetch_ecli_content(ecli)
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
