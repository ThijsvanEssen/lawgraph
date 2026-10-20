"""Retrieve pipeline for ECHR HUDOC judgments: their metadata, then their text."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.clients.base import UnexpectedAnswer
from lawgraph.clients.echr import EchrClient
from lawgraph.config.constants import (
    RAW_KIND_ECHR_JUDGMENT,
    RAW_KIND_ECHR_TEXT,
    SOURCE_ECHR,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries import raw as raw_queries

from .base import (
    FETCH_WORKERS,
    RetrievePipelineBase,
    RetrieveRecord,
    is_not_found,
    is_server_error,
    missing_record,
    status_of,
)

logger = get_logger(__name__)

_FULL_RUN_MAX_RECORDS = 50000
# The language whose text a judgment gets, best first: HUDOC holds a judgment once per
# language and translation, and normalize keeps the English record, else the French one.
_TEXT_LANGUAGES = ("ENG", "FRE")


def text_items(judgments: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """``{item_id: {ecli, language}}`` of the texts to fetch: per judgment (its ECLI, else
    its item id) the English record, else the French one; none for a judgment in neither
    language."""
    best: dict[str, tuple[int, str, dict[str, Any]]] = {}
    for judgment in judgments:
        item_id = str(judgment.get("item_id") or "")
        language = judgment.get("language")
        if not item_id or language not in _TEXT_LANGUAGES:
            continue
        rank = _TEXT_LANGUAGES.index(language)
        judgment_id = str(judgment.get("ecli") or "").upper() or item_id
        if judgment_id not in best or rank < best[judgment_id][0]:
            ecli = str(judgment.get("ecli") or "").upper() or None
            best[judgment_id] = (rank, item_id, {"ecli": ecli, "language": language})
    return {item_id: meta for _, item_id, meta in sorted(best.values())}


def _no_text(exc: Exception) -> bool:
    """HUDOC has no text for this item: HTTP 404, HTTP 204 (an empty answer, for 001-168072
    and three more of the full load), an answer that is no DOCX, or an HTTP 5xx that
    outlasted the client's retries (HUDOC answers HTTP 500 for an item it cannot convert,
    every time). The item is remembered as missing and asked for again after
    ``MISSING_FOR_DAYS``."""
    return (
        is_not_found(exc)
        or status_of(exc) == 204
        or isinstance(exc, UnexpectedAnswer)
        or is_server_error(exc)
    )


class ECHRRetrievePipeline(RetrievePipelineBase):
    """Retrieve ECHR HUDOC judgments for a given respondent country."""

    def __init__(self, store: GraphStore, client: EchrClient | None = None) -> None:
        super().__init__(store)
        self.client = client or EchrClient()

    def fetch(
        self,
        *,
        respondent: str = "NLD",
        since_date: str | None = None,
        max_records: int = 10000,
        eclis: list[str] | None = None,
        refetch: bool = False,
        **kwargs: Any,
    ) -> Iterator[RetrieveRecord]:
        """The judgments against *respondent*, or the judgments with *eclis* (any state),
        then the texts of the judgments that have none (``_texts``)."""
        missing: list[RetrieveRecord] = []
        if eclis:
            wanted = self._without_missing(SOURCE_ECHR, RAW_KIND_ECHR_JUDGMENT, eclis)
            judgments = self.client.fetch_by_ecli(wanted)
            answered = {str(j.get("ecli") or "").upper() for j in judgments}
            missing = [
                missing_record(SOURCE_ECHR, RAW_KIND_ECHR_JUDGMENT, ecli)
                for ecli in wanted
                if ecli.upper() not in answered
            ]
        else:
            judgments = self.client.search_judgments(
                respondent=respondent,
                since_date=self._since(respondent, since_date),
                max_records=max_records,
            )

        for judgment in judgments:
            item_id = str(judgment.get("itemid") or "")
            if not item_id:
                continue
            yield RetrieveRecord(
                source=SOURCE_ECHR,
                kind=RAW_KIND_ECHR_JUDGMENT,
                external_id=item_id,
                payload_json=judgment,
                meta={
                    "appno": judgment.get("appno"),
                    "docname": judgment.get("docname"),
                    "kpdate": judgment.get("kpdate"),
                    "respondent": judgment.get("respondent") or respondent,
                },
            )
        logger.info(
            "ECHR retrieve: %d judgment records (respondent=%s).",
            len(judgments),
            respondent,
        )
        yield from missing
        yield from self._texts(judgments, refetch=refetch)

    def _since(self, respondent: str, since_date: str | None) -> str | None:
        """*since_date*, or the day of the latest judgment against *respondent* stored when
        that is earlier: a run that was missed (HUDOC unavailable, the source off) leaves no
        hole, the next one reads from there."""
        if since_date is None:
            return None
        latest = raw_queries.latest_echr_judgment_day(self.store, respondent)
        if latest and latest < since_date:
            logger.info(
                "ECHR: since %s, the day of the latest judgment stored.", latest
            )
            return latest
        return since_date

    def _texts(
        self, fetched: list[dict[str, Any]], *, refetch: bool
    ) -> Iterator[RetrieveRecord]:
        """The text of every judgment stored or just fetched that has none yet (every one
        with *refetch*); a judgment HUDOC has no document for is remembered as missing."""
        judgments = [
            *raw_queries.echr_items(self.store),
            *(
                {
                    "item_id": j.get("itemid"),
                    "ecli": j.get("ecli"),
                    "language": j.get("languageisocode"),
                }
                for j in fetched
            ),
        ]
        items = text_items(judgments)
        wanted = list(items)
        if not refetch:
            have = self._stored_ids(SOURCE_ECHR, RAW_KIND_ECHR_TEXT)
            wanted = [item_id for item_id in wanted if item_id not in have]
        wanted = self._without_missing(SOURCE_ECHR, RAW_KIND_ECHR_TEXT, wanted)
        logger.info("ECHR retrieve: %d judgment texts to fetch.", len(wanted))
        yield from self._download_each(
            wanted,
            self.client.fetch_document_xml,
            lambda item_id, text: [
                RetrieveRecord(
                    source=SOURCE_ECHR,
                    kind=RAW_KIND_ECHR_TEXT,
                    external_id=item_id,
                    payload_text=text,
                    meta=items[item_id],
                )
            ],
            label="HUDOC",
            missing=lambda item_id, status: missing_record(
                SOURCE_ECHR, RAW_KIND_ECHR_TEXT, item_id, status=status
            ),
            # One document HUDOC cannot convert is missing; many in a row is the host.
            is_missing=_no_text,
            workers=FETCH_WORKERS,
        )

    def run_full(self, respondent: str = "NLD") -> PipelineResult:
        """Fetch all available ECHR judgments for the respondent, and every text again."""
        return self.run(
            respondent=respondent, max_records=_FULL_RUN_MAX_RECORDS, refetch=True
        )
