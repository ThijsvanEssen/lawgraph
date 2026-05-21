from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from typing import Any

from lawgraph.clients.bwb import BWBClient
from lawgraph.clients.eu import EUClient
from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.clients.tk import TKClient
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline

from .eurlex import EurlexRetrievePipeline
from .rechtspraak import RechtspraakRetrievePipeline
from .tk import TKRetrievePipeline

logger = get_logger(__name__)


class RetrieveSourcesPipeline:

    def __init__(
        self,
        store: ArangoStore,
        tk_client: TKClient | None = None,
        rs_client: RechtspraakClient | None = None,
        eu_client: EUClient | None = None,
        bwb_client: BWBClient | None = None,
    ) -> None:
        self.tk_pipeline = TKRetrievePipeline(store, tk_client)
        self.rechtspraak_pipeline = RechtspraakRetrievePipeline(store, rs_client)
        self.eurlex_pipeline = EurlexRetrievePipeline(store, eu_client)
        self.bwb_pipeline = BWBRetrievePipeline(store, bwb_client)

    def dump_tk(
        self,
        *,
        since: dt.datetime,
        limit: int = 100,
        zaak_filter: Callable[[dict[str, Any]], bool] | None = None,
        documentversie_filter: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        result = self.tk_pipeline.run(
            since=since,
            limit=limit,
            zaak_filter=zaak_filter,
            documentversie_filter=documentversie_filter,
        )
        logger.info("TK retrieve: %s.", result.summary())

    def dump_rechtspraak_index(
        self,
        *,
        since: dt.datetime | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> None:
        result = self.rechtspraak_pipeline.run(
            fetch_index=True,
            since=since,
            extra_params=extra_params,
            eclis=None,
        )
        logger.info("Rechtspraak index retrieve: %s.", result.summary())

    def dump_rechtspraak_contents(self, *, eclis: Sequence[str]) -> None:
        result = self.rechtspraak_pipeline.run(eclis=eclis)
        logger.info("Rechtspraak contents retrieve: %s.", result.summary())

    def dump_eurlex_celex_list(
        self,
        celex_ids: Sequence[str],
        lang: str = "NL",
    ) -> None:
        result = self.eurlex_pipeline.run(celex_ids=celex_ids, lang=lang)
        logger.info("EUR-Lex retrieve: %s.", result.summary())
