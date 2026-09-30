"""``retrieve eurlex-nim``: the national implementing measures of EU acts in EUR-Lex."""

from __future__ import annotations

from collections.abc import Iterator

from lawgraph.clients.eu import EUClient
from lawgraph.config.constants import RAW_KIND_EU_NIM, SOURCE_EURLEX
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord


class EurlexNimRetrievePipeline(RetrievePipelineBase):
    """The national implementing measures of a country in EUR-Lex (CELLAR SPARQL): one
    record per measure, with the EU acts it implements, its official journal, number and
    date. ``semantic bwb-implements`` makes IMPLEMENTS of them."""

    def __init__(self, store: ArangoStore, eu_client: EUClient | None = None) -> None:
        super().__init__(store)
        self.eu = eu_client or EUClient()

    def fetch(  # type: ignore[override]
        self, *, country_code: str = "NLD", since: str | None = None, **kwargs: object
    ) -> Iterator[RetrieveRecord]:
        """The measures CELLAR changed on or after *since* (``YYYY-MM-DD``), all without."""
        for measure in self.eu.national_measures(
            country_code=country_code, since=since
        ):
            yield RetrieveRecord(
                source=SOURCE_EURLEX,
                kind=RAW_KIND_EU_NIM,
                external_id=measure["id"],
                payload_json=measure,
                meta={"country": country_code},
            )
