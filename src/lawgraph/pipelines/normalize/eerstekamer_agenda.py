"""Normalize the agendas of the Eerste Kamer into activities.

Every block of the agenda of a plenary sitting (``ek-plenary-html``) and every committee
meeting of a day (``ek-committee-day-html``) is an activity (label and ``chamber`` ``EK``), as
the page gives it (``core.ek_agenda``): a block keyed by the site's own id
(``ek_<id>``), a meeting by its path (``ek_<yyyymmdd>_<committees>``); its date, time, title
or committees, the kind a meeting has (``mondeling overleg``), the decision points of a
meeting, and the page with the day it was read (``source_url``, ``retrieved_on``). The site
gives no status, so none is set: an activity of the Eerste Kamer is never ``Gepland``.

``ABOUT`` the dossiers a block names or the decision points of a meeting refer to, and
``LED_BY`` the committees of the Eerste Kamer a meeting names by their abbreviation
(``(LNV)``, ``(VWS)``), each when the graph holds it.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from dataclasses import asdict
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    COLLECTION_ACTIVITIES,
    COLLECTION_COMMITTEES,
    RAW_KIND_EERSTEKAMER_COMMITTEE_DAY,
    RAW_KIND_EERSTEKAMER_PLENARY,
    RELATION_ABOUT,
    RELATION_LED_BY,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import ek_agenda as agenda
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key, node_id
from lawgraph.core.official_urls import ek_url
from lawgraph.core.raw_records import meta, payload_text
from lawgraph.core.tk_records.activities import activity_display_name
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records
from lawgraph.sources.addresses import edge_source

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)
# What a plenary block is a part of, as the site names its page.
PLENARY_KIND = "plenaire vergadering"
_ABBREVIATION = re.compile(r"\(([^()]+)\)")


def _activity(key: str, props: dict[str, Any], meta: dict[str, Any]) -> Node:
    return Node(
        collection=COLLECTION_ACTIVITIES,
        key=key,
        labels=[CHAMBER_EK],
        props={
            **props,
            "chamber": CHAMBER_EK,
            "source_url": meta.get("url"),
            "retrieved_on": meta.get("read_on"),
            "display_name": activity_display_name(
                props.get("date"), props.get("agenda_title") or props.get("kind")
            ),
        },
    )


def plenary_activities(path: str, page: str, meta: dict[str, Any]) -> list[Node]:
    """An activity per block of the agenda of a plenary sitting."""
    sitting = agenda.plenary(path, page)
    return [
        _activity(
            make_node_key("ek", item.id),
            {
                "date": sitting.date,
                "time": item.time,
                "kind": PLENARY_KIND,
                "agenda_title": item.title,
                "dossier_numbers": item.dossiers,
            },
            meta,
        )
        for item in sitting.items
    ]


def committee_activities(page: str, meta: dict[str, Any]) -> list[Node]:
    """An activity per committee meeting of a day."""
    return [
        _activity(
            make_node_key("ek", meeting.path.rsplit("/", 1)[-1]),
            {
                "date": meeting.date,
                "time": meeting.time,
                "kind": meeting.kind,
                "agenda_title": meeting.committees,
                "dossier_numbers": sorted(
                    {d for point in meeting.points for d in point.dossiers}
                ),
                "decision_points": [asdict(point) for point in meeting.points],
            },
            {**meta, "url": ek_url(meeting.path)},
        )
        for meeting in agenda.committee_day(page).meetings
    ]


class EerstekamerAgendaNormalizePipeline(NormalizePipelineBase[Records]):
    """Activities of the Eerste Kamer from its agendas."""

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER,
            kinds=[RAW_KIND_EERSTEKAMER_PLENARY, RAW_KIND_EERSTEKAMER_COMMITTEE_DAY],
            since=since,
            batch_size=50,
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """The activities, then what they are about and the committees they are of."""
        self._link(self._write_nodes(raw))

    def _write_nodes(self, raw: Records) -> list[Node]:
        nodes: list[Node] = []
        for record in raw:
            path = str(record["external_id"])
            page = payload_text(record)
            if not page:
                self.progress.skip("no page", path)
                continue
            found = meta(record)
            if record.get("kind") == RAW_KIND_EERSTEKAMER_PLENARY:
                activities = plenary_activities(path, page, found)
            else:
                activities = committee_activities(page, found)
            if not activities:
                self.progress.skip("no activities on the page", path)
            nodes += activities
        with NodeWriter(self.store) as writer:
            writer.add_all(nodes)
        logger.info("Eerste Kamer: %d activities from its agendas.", len(nodes))
        return nodes

    def _link(self, activities: list[Node]) -> None:
        tk_cases.link_subjects(
            self.store, activities, RELATION_ABOUT, source=EDGE_SOURCE
        )
        committees = normalize_ek.ek_committee_keys(self.store)
        writer = EdgeWriter(self.store, what="Eerste Kamer committee edges")
        meetings = [n for n in activities if n.props.get("kind") != PLENARY_KIND]
        for node in meetings:
            for abbreviation in _ABBREVIATION.findall(
                node.props.get("agenda_title") or ""
            ):
                if node.node_id and (key := committees.get(abbreviation.strip())):
                    writer.add(
                        node.node_id,
                        node_id(COLLECTION_COMMITTEES, key),
                        RELATION_LED_BY,
                        source=EDGE_SOURCE,
                    )
        writer.flush()
        logger.info("Linked %d Eerste Kamer activities to committees.", writer.added)
