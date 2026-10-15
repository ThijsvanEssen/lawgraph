"""Retrieve pipeline for the agendas of the Eerste Kamer (eerstekamer.nl).

One record per plenary sitting (``ek-plenary-html``, external id its path) and per day of
committee meetings (``ek-committee-day-html``, external id the day). From the next sitting and
the next day of meetings the pages are walked forward to the last one planned, and back to
``since``; a run without ``since`` goes back to June 2015, where the list of votes begins.
Such a run is long, so where its walk back has got to is kept in ``pipeline_state``
(``retrieve eerstekamer-agenda``) once the pages before it are stored: a run that broke off
goes on from there, and a run that ends removes it. A page has no date it changed, so every
page of the window is read again.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, NamedTuple

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import (
    RAW_KIND_EK_COMMITTEE_DAY,
    RAW_KIND_EK_PLENARY,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import ek_agenda as agenda
from lawgraph.core.logging import get_logger
from lawgraph.core.official_urls import ek_url
from lawgraph.db import GraphStore, raw_key
from lawgraph.db.queries import state

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)

STATE_KEY = "retrieve eerstekamer-agenda"
# What the state holds of a kind whose walk back has reached the floor.
DONE = "done"
# How far back a run over everything goes: the list of votes begins in June 2015.
EARLIEST = dt.date(2015, 6, 1)


class Page(NamedTuple):
    """What an agenda page says of itself."""

    day: str | None
    external_id: str | None
    earlier: str | None  # the path of the page before
    later: str | None  # the path of the page after


@dataclass(frozen=True)
class _Kind:
    """A kind of agenda page: where its walk starts, and how a page is read."""

    name: str  # plenary, committee
    raw_kind: str
    start: str
    read: Callable[[str, str], Page]  # (path, html) -> Page


def _plenary(path: str, page: str) -> Page:
    sitting = agenda.plenary(path, page)
    return Page(sitting.date, path, sitting.earlier, sitting.later)


def _committee(path: str, page: str) -> Page:
    day = agenda.committee_day(page)
    date = day.meetings[0].date if day.meetings else None
    return Page(date, date, day.earlier, day.later)


KINDS = (
    _Kind("plenary", RAW_KIND_EK_PLENARY, agenda.PLENARY_PATH, _plenary),
    _Kind(
        "committee", RAW_KIND_EK_COMMITTEE_DAY, agenda.COMMITTEE_DAYS_PATH, _committee
    ),
)


class EerstekamerAgendaRetrievePipeline(RetrievePipelineBase):
    """Store the agendas of the plenary sittings and committee meetings of the Eerste Kamer."""

    # States to keep once the record before them is stored: (its key, the state).
    _unsaved: deque[tuple[str | None, dict[str, str] | None]]

    def __init__(
        self, store: GraphStore, client: EerstekamerSiteClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()

    def fetch(
        self, *, since: dt.date | None = None, **kwargs: object
    ) -> Iterator[RetrieveRecord]:
        floor = (since or EARLIEST).isoformat()
        keep = since is None
        self._unsaved = deque()
        # a run over everything goes on from where one that broke off got to
        resume: dict[str, str] = (
            (state.get_state(self.store, STATE_KEY) or {}) if keep else {}
        )
        for kind in KINDS:
            yield from self._walk(kind, floor, resume, keep=keep)
        if keep:
            self._keep(None, None)

    def _walk(
        self, kind: _Kind, floor: str, resume: dict[str, str], *, keep: bool
    ) -> Iterator[RetrieveRecord]:
        today = dt.date.today().isoformat()
        path, html = self.client.page_at(kind.start)
        page = kind.read(path, html)
        earlier = page.earlier
        # forward from the next one to the last one planned
        while True:
            if page.external_id:
                yield self._record(kind, page.external_id, path, html, today)
            if not page.later:
                break
            path, html = self.client.page_at(page.later)
            page = kind.read(path, html)
        # back to the floor, or on from where a run that broke off got to
        back: str | None = resume.get(kind.name) or earlier
        while back and back != DONE:
            path, html = self.client.page_at(back)
            page = kind.read(path, html)
            if page.day is not None and page.day < floor:
                break
            back = page.earlier
            resume[kind.name] = back or DONE
            record = (
                self._record(kind, page.external_id, path, html, today)
                if page.external_id
                else None
            )
            if keep:
                self._keep(record, resume)
            if record:
                yield record
        resume[kind.name] = DONE
        if keep:
            self._keep(None, resume)

    def _keep(
        self, record: RetrieveRecord | None, resume: dict[str, str] | None
    ) -> None:
        """Keep *resume* (``None``: remove the state) once *record* and every record before it
        is stored; without a record, once every record before it is."""
        key = (
            raw_key(record.source, record.kind, str(record.external_id))
            if record
            else None
        )
        self._unsaved.append((key, dict(resume) if resume is not None else None))
        if key is None and len(self._unsaved) == 1:
            self._on_stored([])

    def _on_stored(self, docs: list[dict[str, Any]]) -> None:
        stored = {doc["_key"] for doc in docs}
        kept = False
        last: dict[str, str] | None = None
        while self._unsaved and (
            self._unsaved[0][0] is None or self._unsaved[0][0] in stored
        ):
            last = self._unsaved.popleft()[1]
            kept = True
        if kept:
            state.set_state(self.store, STATE_KEY, last)

    def _record(
        self, kind: _Kind, external_id: str, path: str, page: str, today: str
    ) -> RetrieveRecord:
        return RetrieveRecord(
            source=SOURCE_EERSTEKAMER,
            kind=kind.raw_kind,
            external_id=external_id,
            payload_text=page,
            meta={"url": ek_url(path), "read_on": today},
        )
