"""Semantic pipeline: series of parallel judgments, one court on one day in the same words.

Reads the judgments of one court and one day at a time (the texts of one day are all it
holds), groups them with ``core.judgment_series`` and writes ``series_id`` (the lowest ECLI
of the series) and ``series_size`` on each judgment of a series; a judgment that is in no
series (any more) has both null. No edges: the series is found again by its id.

With ``--since`` only the days of the judgments retrieved from then on are grouped again:
a series is never wider than one day.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import COLLECTION_JUDGMENTS
from lawgraph.core.judgment_series import (
    GENERIC_SUMMARY_DATES,
    SeriesCandidate,
    group_series,
    series_props,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db import NodeWriter
from lawgraph.db.queries import semantic as semantic_queries

from .base import JUDGMENT_BATCH_SIZE, SemanticPipelineBase

logger = get_logger(__name__)

CourtDay = tuple[str, str]  # (court_code, date)


def _candidate(row: dict[str, Any]) -> SeriesCandidate:
    return SeriesCandidate.of(
        row["ecli"],
        text=row.get("text"),
        summary=row.get("summary"),
        document_type=row.get("document_type"),
        case_number_keys=row.get("case_number_keys") or [],
    )


class RechtspraakSeriesSemanticPipeline(SemanticPipelineBase):
    """Write ``series_id`` and ``series_size`` on the judgments of a series."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        since_iso = iso_timestamp(since)
        generic = set(
            semantic_queries.generic_summaries(
                self.store, min_dates=GENERIC_SUMMARY_DATES
            )
        )
        days = self._court_days(since_iso)
        series = judgments = 0
        with NodeWriter(self.store) as writer:
            for day in self._track(days.values(), "court days", total=len(days)):
                rows = [
                    row
                    for row in semantic_queries.judgments_of_court_day(
                        self.store, batch_size=JUDGMENT_BATCH_SIZE, **day
                    )
                    if row.get("ecli")
                ]
                groups = group_series([_candidate(row) for row in rows], generic)
                series += len(groups)
                judgments += sum(len(members) for members in groups)
                self._write(
                    rows,
                    series_props((r["ecli"] for r in rows), groups),
                    writer,
                    result,
                )
        logger.info(
            "%d series of %d judgments on %d court days; %d judgments changed.",
            series,
            judgments,
            len(days),
            result.updated,
        )
        return result

    def _court_days(self, since_iso: str | None) -> dict[CourtDay, dict[str, Any]]:
        """The court days to group: those of the judgments retrieved since *since_iso*, or
        every day with two judgments or more of one court; and the days of the judgments
        in a series now, so that one that no longer is loses its series."""
        if since_iso:
            listed = [
                semantic_queries.judgment_court_days(
                    self.store, eclis=self._recent_eclis(since_iso)
                )
            ]
        else:
            in_series = sorted(semantic_queries.judgments_in_series(self.store))
            listed = [
                semantic_queries.judgment_court_days(self.store),
                semantic_queries.judgment_court_days(self.store, eclis=in_series),
            ]
        return {
            (day["court_code"], day["date"]): day for rows in listed for day in rows
        }

    @staticmethod
    def _write(
        rows: list[dict[str, Any]],
        props: dict[str, tuple[str | None, int | None]],
        writer: NodeWriter,
        result: PipelineResult,
    ) -> None:
        for row in rows:
            series_id, size = props[row["ecli"]]
            if (row.get("series_id"), row.get("series_size")) == (series_id, size):
                result.unchanged += 1
                continue
            writer.add(
                Node(
                    collection=COLLECTION_JUDGMENTS,
                    type=NodeType.JUDGMENT,
                    key=row["key"],
                    props={"series_id": series_id, "series_size": size},
                )
            )
            result.updated += 1
