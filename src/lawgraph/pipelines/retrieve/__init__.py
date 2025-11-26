from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from typing import Any

from lawgraph.clients.eu import EUClient
from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.clients.tk import TKClient
from lawgraph.config.settings import (
    RAW_KIND_TK_DOCUMENTVERSIE,
    RAW_KIND_TK_ZAAK,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

from .eurlex import EurlexRetrievePipeline
from .rechtspraak import RechtspraakRetrievePipeline
from .tk import TKRetrievePipeline

logger = get_logger(__name__)


class RetrieveSourcesPipeline:
    """Koordineert de bron-specifieke retrieve pipelines."""

    def __init__(
        self,
        store: ArangoStore,
        tk_client: TKClient | None = None,
        rs_client: RechtspraakClient | None = None,
        eu_client: EUClient | None = None,
    ) -> None:
        self.tk_pipeline = TKRetrievePipeline(store, tk_client)
        self.rechtspraak_pipeline = RechtspraakRetrievePipeline(store, rs_client)
        self.eurlex_pipeline = EurlexRetrievePipeline(store, eu_client)

    def dump_tk(
        self,
        *,
        since: dt.datetime,
        limit: int = 100,
        zaak_filter: Callable[[dict[str, Any]], bool] | None = None,
        documentversie_filter: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        records = self.tk_pipeline.dump(
            since=since,
            limit=limit,
            zaak_filter=zaak_filter,
            documentversie_filter=documentversie_filter,
        )
        zaak_count = sum(1 for rec in records if rec.kind == RAW_KIND_TK_ZAAK)
        documentversie_count = sum(1 for rec in records if rec.kind == RAW_KIND_TK_DOCUMENTVERSIE)
        logger.info(
            "Stored %d TK Zaak and %d TK DocumentVersie retrieve records.",
            zaak_count,
            documentversie_count,
        )

    def dump_rechtspraak_index(
        self,
        *,
        since: dt.datetime | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> None:
        records = self.rechtspraak_pipeline.dump(
            fetch_index=True,
            since=since,
            extra_params=extra_params,
            eclis=None,
        )
        modified_text = "modified since " + since.isoformat() if since else "full index"
        logger.info(
            "Stored %d Rechtspraak index snapshot (%s).",
            len(records),
            modified_text,
        )

    def dump_rechtspraak_contents(self, *, eclis: Sequence[str]) -> None:
        records = self.rechtspraak_pipeline.dump(eclis=eclis)
        logger.info(
            "Stored %d Rechtspraak contents via retrieve pipeline.",
            len(records),
        )

    def dump_eurlex_celex_list(
        self,
        *,
        celex_ids: Sequence[str],
        lang: str = "NL",
    ) -> None:
        records = self.eurlex_pipeline.dump(celex_ids=celex_ids, lang=lang)
        logger.info("Stored %d EUR-Lex CELEX html records.", len(records))
