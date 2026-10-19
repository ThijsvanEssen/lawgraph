from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence

from lawgraph.clients.eu import EUClient
from lawgraph.config.constants import RAW_KIND_EURLEX_CELEX, SOURCE_EURLEX
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import is_later
from lawgraph.db import GraphStore
from lawgraph.db.queries import raw as raw_queries

from .base import (
    RetrievePipelineBase,
    RetrieveRecord,
    listed,
    missing_record,
)

logger = get_logger(__name__)


class EurlexRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for EUR-Lex CELEX html dumps."""

    def __init__(self, store: GraphStore, eu_client: EUClient | None = None) -> None:
        super().__init__(store)
        self.eu = eu_client or EUClient()

    def run(  # type: ignore[override]
        self,
        *,
        celex_ids: Sequence[str],
        lang: str = "NL",
        **kwargs: object,
    ) -> PipelineResult:
        """Fetch the requested acts and store them while they are fetched.

        An interrupted run keeps what it already has, and a re-run skips the acts stored in
        the last 24 hours. An act CELLAR has no HTML text of
        (many old regulations, every corrigendum) is counted as skipped, not as an error.
        """
        return self._store_all(self._fetch_acts(celex_ids, lang), what="acts")

    def run_changed(
        self, *, celex_ids: Sequence[str], lang: str = "NL"
    ) -> PipelineResult:
        """Fetch the acts of *celex_ids* that are not stored or that CELLAR changed since:
        its ``cmr:lastModificationDate`` lies after the one stored with the act
        (``meta.modified``). A stored act without that date is fetched once; one CELLAR has
        no date for is left alone."""
        return self._store_all(self._fetch_changed(celex_ids, lang), what="acts")

    def _fetch_changed(
        self, celex_ids: Sequence[str], lang: str
    ) -> Iterator[RetrieveRecord]:
        dates = self.eu.last_modified(list(celex_ids))
        stored = {
            str(row["id"]): row["value"]
            for row in raw_queries.meta_values(
                self.store,
                source=SOURCE_EURLEX,
                kind=RAW_KIND_EURLEX_CELEX,
                field="modified",
            )
        }
        changed = [
            celex
            for celex in celex_ids
            if celex not in stored
            or (
                celex in dates
                and (not stored[celex] or is_later(dates[celex], stored[celex]))
            )
        ]
        logger.info(
            "EUR-Lex: %d of %d acts are new or changed in CELLAR.",
            len(changed),
            len(celex_ids),
        )
        yield from self._download(changed, lang, dates)

    def _fetch_acts(
        self, celex_ids: Sequence[str], lang: str
    ) -> Iterator[RetrieveRecord]:
        done = self._recently_stored(SOURCE_EURLEX, RAW_KIND_EURLEX_CELEX)
        todo = [celex for celex in celex_ids if celex not in done]
        yield from self._download(todo, lang, self.eu.last_modified(todo))

    def _download(
        self, celex_ids: list[str], lang: str, dates: dict[str, str]
    ) -> Iterator[RetrieveRecord]:
        """The acts of *celex_ids*, each stored with the date CELLAR last changed it
        (*dates*), so a later run can tell whether it changed since. A download that fails
        is skipped (the next run asks again); many in a row stop the step."""
        todo = self._without_missing(SOURCE_EURLEX, RAW_KIND_EURLEX_CELEX, celex_ids)
        yield from self._download_each(
            todo,
            lambda celex: self.eu.fetch_celex_html(celex, lang=lang),
            lambda celex, html: [
                RetrieveRecord(
                    source=SOURCE_EURLEX,
                    kind=RAW_KIND_EURLEX_CELEX,
                    external_id=celex,
                    payload_text=html,
                    meta={"celex": celex, "lang": lang, "modified": dates.get(celex)},
                )
            ],
            label="EUR-Lex",
            failed_is_skipped=True,
            missing=lambda celex, status: missing_record(
                SOURCE_EURLEX, RAW_KIND_EURLEX_CELEX, celex, status=status
            ),
        )

    def _fetch_listed(
        self, listing: Callable[[], list[str]], what: str, lang: str
    ) -> Iterator[RetrieveRecord]:
        """The acts *listing* names (every *what*), inside the run: a listing that fails or
        is empty is an error of the step."""
        celex_ids = listed(listing(), what)
        logger.info("EUR-Lex: %d %s listed; starting retrieval.", len(celex_ids), what)
        yield from self._fetch_acts(celex_ids, lang)

    def _run_listed(
        self, listing: Callable[[], list[str]], what: str, lang: str
    ) -> PipelineResult:
        return self._store_all(self._fetch_listed(listing, what, lang), what="acts")

    def run_full(
        self, *, lang: str = "NL", cdm_types: tuple[str, ...] = ("directive",)
    ) -> PipelineResult:
        """Full-load mode: the acts of *cdm_types* CELLAR SPARQL lists
        (``EUClient.enumerate_all_ids``, which leaves out corrigenda and is incomplete for
        recent years). Safe to interrupt and re-run."""
        return self._run_listed(
            lambda: self.eu.enumerate_all_ids(cdm_types=cdm_types),
            f"EU acts of type {', '.join(cdm_types)}",
            lang,
        )

    def run_nim(self, *, country_code: str = "NLD", lang: str = "NL") -> PipelineResult:
        """NIM mode: the EU acts with national implementation measures of *country_code*."""
        return self._run_listed(
            lambda: self.eu.enumerate_nim_ids(country_code=country_code),
            f"EU acts with national implementation measures of {country_code}",
            lang,
        )

    def run_cjeu(
        self,
        *,
        celex_ids: list[str] | None = None,
        country_code: str = "NLD",
        lang: str = "NL",
    ) -> PipelineResult:
        """CJEU mode: the judgments that cite the acts *celex_ids*, or without them the
        judgments referred from a court of *country_code*."""
        return self._run_listed(
            lambda: self.eu.enumerate_cjeu_ids(
                celex_ids=celex_ids, country_code=country_code
            ),
            "CJEU judgments",
            lang,
        )

    def run_com(self, *, celex_ids: list[str], lang: str = "NL") -> PipelineResult:
        """COM mode: the COM proposals of the acts *celex_ids* (those in the graph)."""
        return self._run_listed(
            lambda: self.eu.enumerate_com_ids(
                celex_ids=listed(celex_ids, "EU acts in the graph")
            ),
            "COM proposals",
            lang,
        )
