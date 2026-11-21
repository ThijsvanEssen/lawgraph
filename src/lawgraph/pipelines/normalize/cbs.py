"""Normalize the court map per municipality and year (``lg_court_districts``).

Each stored CBS table "Gebieden in Nederland" (``retrieve cbs``) gives a year's municipalities
with their arrondissement and ressort; the text of the Wet op de rechterlijke indeling in the
graph (``normalize bwb``) gives the article that draws each, and for this year's table how the
text compares per municipality (``core.court_districts``). A table without the columns of the
areas fails the step (the CBS changed it); the others are written. The table is written
again whole.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import RAW_KIND_CBS_REGIONS, SOURCE_CBS
from lawgraph.core import court_districts
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.raw_records import payload_json
from lawgraph.core.time import dutch_today
from lawgraph.db.queries import court_districts as queries

from .base import NormalizePipelineBase

logger = get_logger(__name__)


@dataclass(frozen=True)
class Stored:
    """The stored tables and the text of the articles of the law."""

    tables: list[dict[str, Any]]
    articles: dict[str, str]


class CbsNormalizePipeline(NormalizePipelineBase[Stored]):
    """The arrondissement and ressort of every municipality per year, checked against the
    text of the law for this year."""

    def fetch_raw(self, *, since: dt.datetime | None = None) -> Stored:
        # every year again, whatever the window: the table is written whole
        return Stored(
            tables=list(
                self._iter_raw_sources(source=SOURCE_CBS, kinds=[RAW_KIND_CBS_REGIONS])
            ),
            articles=queries.article_texts(self.store, court_districts.LAW_BWB_ID),
        )

    def write(self, raw: Stored, result: PipelineResult) -> None:
        """The rows of every year. No nodes, no edges."""
        if not raw.tables:
            logger.warning("No CBS table of areas is stored; the table stays as it is.")
            return
        law = court_districts.read_law(raw.articles)
        if not law.districts:
            logger.warning(
                "The graph holds no text of the arrondissementen (%s): no articles, no "
                "check.",
                court_districts.LAW_BWB_ID,
            )
        this_year = dutch_today().year
        rows: list[dict[str, Any]] = []
        for record in raw.tables:
            payload = payload_json(record)
            try:
                municipalities = court_districts.read_table(payload)
            except ValueError as exc:
                self.progress.fail(
                    "table of areas not read", f"{record.get('external_id')}: {exc}"
                )
                continue
            year = int(payload["year"])
            checked = year == this_year and bool(law.districts)
            rows += court_districts.rows(year, municipalities, law, checked)
            if checked:
                self._log_gaps(year, rows)
        queries.write(self.store, rows)
        result.updated += len(rows)

    @staticmethod
    def _log_gaps(year: int, rows: list[dict[str, Any]]) -> None:
        gaps = [
            r["municipality"]
            for r in rows
            if r["year"] == year and r["district_check"] != "agrees"
        ]
        logger.info(
            "%d: the text of the law puts %d municipalities elsewhere or nowhere: %s",
            year,
            len(gaps),
            ", ".join(gaps) or "none",
        )
