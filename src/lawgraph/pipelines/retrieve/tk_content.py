"""Pipeline that fetches the XML of Tweede Kamer papers and stores it in raw_sources.

Only papers whose kind contains one of a few words qualify (by default ``toelichting``,
``motie``, ``amendement``, ``voorstel van wet``, ``nota van wijziging``, ``raad van state``
and ``nader rapport``): the memoranda that feed the memorandum context (``tk-mvt``,
``tk-amendment-articles``), the moties and amendementen, the bill and its changes, and the
advice of the Raad van State on it with the government's answer, whose text is what they
say; not the whole corpus.
The Tweede Kamer's own API serves only a PDF; the KOOP repository has the same paper as
structured XML, filed under its dossier. ``normalize tk-content`` reads the XML from the
raw records.

Flow:
    1. The papers of the graph that are numbered in a dossier and have no raw XML yet
       (``_gaps.kamerstuk_gaps``)
    2. Build the identifier ``kst-<dossier>-<number>`` and fetch its XML
    3. Store it unchanged, keyed by the identifier; an answer of HTTP 404 becomes a record
       that says so
    4. Report created / skipped / error counts
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Sequence
from typing import Any

from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.config.constants import RAW_KIND_TK_KAMERSTUK_XML, SOURCE_TK
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.retrieve.base import (
    RetrievePipelineBase,
    RetrieveRecord,
    missing_record,
)

logger = get_logger(__name__)

# The words of a kind that qualify a paper for fetching, by default.
DEFAULT_KINDS = (
    "toelichting",
    "motie",
    "amendement",
    "voorstel van wet",
    "nota van wijziging",
    "raad van state",
    "nader rapport",
)

# A new paper is first published as a PDF only ("Onopgemaakt"); its XML follows within about
# two working days, now and then a week or more later (prod, Oct 2026: 41 of 105 papers of a
# day still had none after three days). A paper this young that the repository has no XML
# for yet is asked for again the next night, not after the month of a document that was
# never there.
_FRESH_FOR_DAYS = 14
_FRESH_RETRY_DAYS = 1


class TKContentRetrievePipeline(RetrievePipelineBase):
    """Fetch the XML of Tweede Kamer papers and store it.

    Only papers whose ``props.kind`` contains one of the *kinds* (case-insensitive) and of
    which no XML is stored yet are processed.
    """

    def __init__(
        self,
        *,
        store: GraphStore,
        client: KamerstukClient | None = None,
    ) -> None:
        super().__init__(store)
        self.client = client or KamerstukClient()

    def run(  # type: ignore[override]
        self,
        *,
        kinds: Sequence[str] = DEFAULT_KINDS,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> PipelineResult:
        """Fetch the XML of every qualifying paper that has none stored.

        Args:
            kinds: Case-insensitive substrings matched against ``props.kind``.
            limit: At most this many papers; the rest are the gaps of the next run.
            dry_run: When True, log what would happen but make no changes.
        """
        papers = _gaps.kamerstuk_gaps(self.store, kinds)
        if limit:
            papers = _gaps.Gaps.capped(papers, "Kamerstukken without XML", limit)
        if not papers:
            logger.info("No papers without XML found for kinds %s.", list(kinds))
            return PipelineResult()
        logger.info(
            "Fetching the XML of %d papers (kind contains one of %s)%s.",
            len(papers),
            list(kinds),
            " — DRY RUN" if dry_run else "",
        )
        result = self._store_all(self._fetch_papers(papers, dry_run), what="papers")
        return _gaps.noted(result, papers)

    def _fetch_papers(
        self, papers: list[dict[str, Any]], dry_run: bool
    ) -> Iterator[RetrieveRecord]:
        if dry_run:
            self.progress.expect(len(papers))
            for paper in papers:
                self.progress.skip("dry run", paper["identifier"])
            return
        by_id = {paper["identifier"]: paper for paper in papers}
        yield from self._download_each(
            list(by_id),
            self.client.fetch_kamerstuk_xml,
            lambda identifier, xml: [
                RetrieveRecord(
                    source=SOURCE_TK,
                    kind=RAW_KIND_TK_KAMERSTUK_XML,
                    external_id=identifier,
                    payload_text=xml,
                    meta={"document": by_id[identifier]["key"]},
                )
            ],
            source="Kamerstuk XML",
            missing=lambda identifier, status: missing_record(
                SOURCE_TK,
                RAW_KIND_TK_KAMERSTUK_XML,
                identifier,
                status=status,
                days=(
                    _FRESH_RETRY_DAYS
                    if _is_fresh(by_id[identifier].get("date"))
                    else None
                ),
            ),
        )


def _is_fresh(date: object) -> bool:
    """Whether a paper dated *date* (ISO) is young enough for its XML to be on its way."""
    try:
        published = dt.date.fromisoformat(str(date)[:10])
    except ValueError:
        return False
    today = dt.datetime.now(dt.timezone.utc).date()
    return today - published <= dt.timedelta(days=_FRESH_FOR_DAYS)
