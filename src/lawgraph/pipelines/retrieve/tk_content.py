"""Pipeline that fetches the XML of Tweede Kamer papers and stores it in raw_sources.

Only papers whose kind contains one of a few words qualify (by default ``toelichting``,
``motie``, ``amendement``, ``voorstel van wet`` and ``nota van wijziging``): the memoranda
that feed the memorandum context (``tk-mvt``, ``tk-amendment-articles``), the moties and
amendementen, and the bill and its changes, whose text is what they say; not the whole
corpus.
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
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Sequence
from typing import Any

from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.config.constants import RAW_KIND_TK_KAMERSTUK_XML, SOURCE_TK
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.retrieve.base import (
    FailureStreak,
    RetrievePipelineBase,
    RetrieveRecord,
    failure_reason,
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
)

# A new paper is first published as a PDF only ("Onopgemaakt"); its XML follows within about
# two working days. A paper this young that the repository has no XML for yet is asked for
# again soon, not after the month of a document that was never there.
_FRESH_FOR_DAYS = 7


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
        dry_run: bool = False,
    ) -> PipelineResult:
        """Fetch the XML of every qualifying paper that has none stored.

        Args:
            kinds: Case-insensitive substrings matched against ``props.kind``.
            dry_run: When True, log what would happen but make no changes.
        """
        papers = _gaps.kamerstuk_gaps(self.store, kinds)
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
        self.progress.expect(len(papers))
        streak = FailureStreak("Kamerstuk XML")
        for paper in papers:
            identifier = paper["identifier"]
            if dry_run:
                self.progress.skip("dry run", identifier)
                continue
            record = self._fetch_one(paper, identifier, streak)
            if record is not None:
                yield record

    def _fetch_one(
        self, paper: dict[str, Any], identifier: str, streak: FailureStreak
    ) -> RetrieveRecord | None:
        progress = self.progress
        try:
            xml = self.client.fetch_kamerstuk_xml(identifier)
        except Exception as exc:
            progress.fail(f"download failed ({failure_reason(exc)})", identifier)
            streak.failed(identifier, exc)
            return None
        streak.ok()

        if xml is None:
            progress.skip("no XML in the repository (HTTP 404)", identifier)
            return missing_record(
                SOURCE_TK,
                RAW_KIND_TK_KAMERSTUK_XML,
                identifier,
                listed=_is_fresh(paper.get("date")),
            )
        try:
            ET.fromstring(xml.lstrip("﻿"))
        except ET.ParseError:
            # An error page that answered 200 must not be kept for a paper: it is not asked
            # for again once a record exists.
            progress.fail("the XML cannot be read", identifier)
            return None
        return RetrieveRecord(
            source=SOURCE_TK,
            kind=RAW_KIND_TK_KAMERSTUK_XML,
            external_id=identifier,
            payload_text=xml,
            meta={"document": paper["key"]},
        )


def _is_fresh(date: object) -> bool:
    """Whether a paper dated *date* (ISO) is young enough for its XML to be on its way."""
    try:
        published = dt.date.fromisoformat(str(date)[:10])
    except ValueError:
        return False
    today = dt.datetime.now(dt.timezone.utc).date()
    return today - published <= dt.timedelta(days=_FRESH_FOR_DAYS)
