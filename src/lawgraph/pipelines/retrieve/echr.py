"""Retrieve pipeline for ECHR HUDOC judgments: their metadata, then their text."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

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
    FailureStreak,
    RetrievePipelineBase,
    RetrieveRecord,
    failure_reason,
    fetched_side_by_side,
    is_not_found,
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


def _server_error(exc: Exception) -> bool:
    status = status_of(exc)
    return status is not None and 500 <= status < 600


def _no_text(exc: Exception) -> bool:
    """HUDOC has no text for this item: HTTP 404, an answer that is no DOCX, or an HTTP 5xx
    that outlasted the client's retries (HUDOC answers HTTP 500 for an item it cannot
    convert, every time). The item is remembered as missing and asked for again after
    ``MISSING_FOR_DAYS``."""
    return is_not_found(exc) or isinstance(exc, ValueError) or _server_error(exc)


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
        **kwargs,
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
                since_date=since_date,
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
            have = {
                str(row["id"])
                for row in raw_queries.fetch_times(
                    self.store, source=SOURCE_ECHR, kind=RAW_KIND_ECHR_TEXT
                )
            }
            wanted = [item_id for item_id in wanted if item_id not in have]
        wanted = self._without_missing(SOURCE_ECHR, RAW_KIND_ECHR_TEXT, wanted)
        logger.info("ECHR retrieve: %d judgment texts to fetch.", len(wanted))
        streak = FailureStreak("HUDOC")
        for item_id, answer in fetched_side_by_side(
            wanted, self.client.fetch_document_xml
        ):
            if isinstance(answer, str):
                streak.ok()
                yield RetrieveRecord(
                    source=SOURCE_ECHR,
                    kind=RAW_KIND_ECHR_TEXT,
                    external_id=item_id,
                    payload_text=answer,
                    meta=items[item_id],
                )
            elif _no_text(answer):
                if _server_error(answer):
                    # One document HUDOC cannot convert; many in a row is the host.
                    streak.failed(item_id, answer)
                self.progress.skip(f"no text ({failure_reason(answer)})", item_id)
                yield missing_record(
                    SOURCE_ECHR,
                    RAW_KIND_ECHR_TEXT,
                    item_id,
                    status=status_of(answer) or 200,
                )
            else:
                streak.failed(item_id, answer)
                self.progress.fail(failure_reason(answer), item_id)

    def run_full(self, respondent: str = "NLD") -> PipelineResult:
        """Fetch all available ECHR judgments for the respondent, and every text again."""
        return self.run(
            respondent=respondent, max_records=_FULL_RUN_MAX_RECORDS, refetch=True
        )
