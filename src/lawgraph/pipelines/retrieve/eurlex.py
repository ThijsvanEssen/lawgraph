from __future__ import annotations

from collections.abc import Sequence

from lawgraph.clients.eu import EUClient
from lawgraph.config.constants import RAW_KIND_EU_CELEX, SOURCE_EURLEX
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class EurlexRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for EUR-Lex CELEX html dumps."""

    def __init__(self, store: ArangoStore, eu_client: EUClient | None = None) -> None:
        super().__init__(store)
        self.eu = eu_client or EUClient()

    def fetch(  # type: ignore[override]
        self,
        *,
        celex_ids: Sequence[str],
        lang: str = "NL",
        **kwargs: object,
    ) -> Sequence[RetrieveRecord]:
        """Return raw HTML payloads for the requested CELEX identifiers."""
        logger.info("Fetching EUR-Lex CELEX ids: %s", celex_ids)
        records: list[RetrieveRecord] = []
        for celex in celex_ids:
            try:
                html = self.eu.fetch_celex_html(celex, lang=lang)
            except Exception as exc:
                logger.warning("Skipping CELEX %s: %s", celex, exc)
                continue
            records.append(
                RetrieveRecord(
                    source=SOURCE_EURLEX,
                    kind=RAW_KIND_EU_CELEX,
                    external_id=celex,
                    payload_text=html,
                    meta={"celex": celex, "lang": lang},
                )
            )
        logger.info("EUR-Lex retrieve created %d records.", len(records))
        return records

    def run_full(self, *, lang: str = "NL") -> PipelineResult:
        """Full-load mode: enumerate ALL EUR-Lex documents via CELLAR SPARQL, then fetch each.

        Uses ``EUClient.enumerate_all_ids()`` to discover every regulation, directive,
        and decision CELEX ID, then calls ``run(celex_ids=...)`` to fetch and store each.
        Safe to interrupt and re-run — the upsert pattern ensures idempotency.
        """
        logger.info("EUR-Lex full-load: enumerating all CELEX IDs via CELLAR SPARQL.")
        try:
            all_ids = self.eu.enumerate_all_ids()
        except Exception as exc:
            result = PipelineResult()
            msg = f"EUR-Lex SPARQL enumeration failed: {exc}"
            logger.error(msg)
            result.add_error(msg)
            return result

        logger.info(
            "EUR-Lex full-load: %d IDs found; starting retrieval.", len(all_ids)
        )
        return self.run(celex_ids=all_ids, lang=lang)

    def run_nim(self, *, country_code: str = "NLD", lang: str = "NL") -> PipelineResult:
        """NIM mode: enumerate EU acts with national implementation measures for a country,
        then fetch each.

        Uses ``EUClient.enumerate_nim_ids()`` to discover CELEX IDs, then calls
        ``run(celex_ids=...)`` to fetch and store each.
        Safe to interrupt and re-run — the upsert pattern ensures idempotency.
        """
        logger.info(
            "EUR-Lex NIM-load: enumerating CELEX IDs with NIM for country=%s.",
            country_code,
        )
        try:
            all_ids = self.eu.enumerate_nim_ids(country_code=country_code)
        except Exception as exc:
            result = PipelineResult()
            msg = f"EUR-Lex NIM SPARQL enumeration failed: {exc}"
            logger.error(msg)
            result.add_error(msg)
            return result

        logger.info("EUR-Lex NIM-load: %d IDs found; starting retrieval.", len(all_ids))
        return self.run(celex_ids=all_ids, lang=lang)

    def run_cjeu(
        self,
        *,
        celex_ids: list[str] | None = None,
        country_code: str = "NLD",
        lang: str = "NL",
    ) -> PipelineResult:
        """CJEU mode: enumerate relevant CJEU judgment CELEX IDs, then fetch each.

        If ``celex_ids`` is provided, finds judgments citing those instruments.
        Otherwise enumerates NL-party judgments via ``country_code``.
        """
        logger.info("EUR-Lex CJEU: enumerating relevant judgment CELEX IDs.")
        all_ids = self.eu.enumerate_cjeu_ids(
            celex_ids=celex_ids, country_code=country_code
        )
        logger.info(
            "EUR-Lex CJEU: %d judgment IDs found; starting retrieval.", len(all_ids)
        )
        return self.run(celex_ids=all_ids, lang=lang)

    def run_com(
        self,
        *,
        celex_ids: list[str] | None = None,
        lang: str = "NL",
    ) -> PipelineResult:
        """COM mode: enumerate COM proposal CELEX IDs for the given instruments, then fetch each.

        ``celex_ids`` should be the CELEX IDs of the instruments already in the graph.
        If not provided, a warning is logged and an empty result is returned.
        """
        if not celex_ids:
            logger.warning(
                "run_com() called without celex_ids — cannot enumerate COM proposals."
            )
            return PipelineResult()

        logger.info(
            "EUR-Lex COM: enumerating proposal CELEX IDs for %d instruments.",
            len(celex_ids),
        )
        all_ids = self.eu.enumerate_com_ids(celex_ids=celex_ids)
        logger.info(
            "EUR-Lex COM: %d COM proposal IDs found; starting retrieval.", len(all_ids)
        )
        return self.run(celex_ids=all_ids, lang=lang)
