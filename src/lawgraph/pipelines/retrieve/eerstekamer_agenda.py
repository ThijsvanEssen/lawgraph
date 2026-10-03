"""Retrieve pipeline for the agendas of the Eerste Kamer (eerstekamer.nl).

One record per plenary sitting (``ek-plenary-html``, external id its path) and per day of
committee meetings (``ek-committee-day-html``, external id the day). From the next sitting and
the next day of meetings the pages are walked forward to the last one planned, and back to
``since``; a run without ``since`` goes back to June 2015, where the list of votes begins.
Such a run is long, so where its walk back has got to is kept in ``pipeline_state``
(``retrieve eerstekamer-agenda``): a run that broke off goes on from there, and a run that
ends removes it. A page has no date it changed, so every page of the window is read again.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import (
    RAW_KIND_EK_COMMITTEE_DAY,
    RAW_KIND_EK_PLENARY,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import eerstekamer_agenda as agenda
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore
from lawgraph.db.queries import state

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)

STATE_KEY = "retrieve eerstekamer-agenda"
# What the state holds of a kind whose walk back has reached the floor.
DONE = "done"
# How far back a run over everything goes: the list of votes begins in June 2015.
EARLIEST = dt.date(2015, 6, 1)


@dataclass(frozen=True)
class _Kind:
    """A kind of agenda page: where its walk starts, and what a page says of itself."""

    name: str  # plenary, committee
    raw_kind: str
    start: str
    # (path, html) -> (the day, the external id, the page before, the page after)
    read: Callable[[str, str], tuple[str | None, str | None, str | None, str | None]]


def _plenary(path: str, page: str) -> tuple[str | None, ...]:
    sitting = agenda.plenary(path, page)
    return sitting.date, path, sitting.earlier, sitting.later


def _committee(path: str, page: str) -> tuple[str | None, ...]:
    day = agenda.committee_day(page)
    date = day.meetings[0].date if day.meetings else None
    return date, date, day.earlier, day.later


KINDS = (
    _Kind("plenary", RAW_KIND_EK_PLENARY, agenda.PLENARY_PATH, _plenary),  # type: ignore[arg-type]
    _Kind(
        "committee",
        RAW_KIND_EK_COMMITTEE_DAY,
        agenda.COMMITTEE_DAYS_PATH,
        _committee,  # type: ignore[arg-type]
    ),
)


class EerstekamerAgendaRetrievePipeline(RetrievePipelineBase):
    """Store the agendas of the plenary sittings and committee meetings of the Eerste Kamer."""

    def __init__(
        self, store: GraphStore, client: EerstekamerSiteClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()

    def fetch(  # type: ignore[override]
        self, *, since: dt.date | None = None, **kwargs: object
    ) -> Iterator[RetrieveRecord]:
        floor = (since or EARLIEST).isoformat()
        # a run over everything goes on from where one that broke off got to
        resume: dict[str, str] = (
            (state.get_state(self.store, STATE_KEY) or {}) if since is None else {}
        )
        for kind in KINDS:
            yield from self._walk(kind, floor, resume, keep=since is None)
        if since is None:
            state.set_state(self.store, STATE_KEY, None)

    def _walk(
        self, kind: _Kind, floor: str, resume: dict[str, str], *, keep: bool
    ) -> Iterator[RetrieveRecord]:
        today = dt.date.today().isoformat()
        path, page = self.client.page_at(kind.start)
        day, external_id, earlier, later = kind.read(path, page)
        # forward from the next one to the last one planned
        while True:
            if external_id:
                yield self._record(kind, external_id, path, page, today)
            if not later:
                break
            path, page = self.client.page_at(later)
            day, external_id, _, later = kind.read(path, page)
        # back to the floor, or on from where a run that broke off got to
        back: str | None = resume.get(kind.name) or earlier
        while back and back != DONE:
            path, page = self.client.page_at(back)
            day, external_id, back, _ = kind.read(path, page)
            if day is not None and day < floor:
                back = None
                break
            if external_id:
                yield self._record(kind, external_id, path, page, today)
            if keep:
                resume[kind.name] = back or DONE
                state.set_state(self.store, STATE_KEY, resume)
        if keep:
            resume[kind.name] = DONE
            state.set_state(self.store, STATE_KEY, resume)

    def _record(
        self, kind: _Kind, external_id: str, path: str, page: str, today: str
    ) -> RetrieveRecord:
        return RetrieveRecord(
            source=SOURCE_EERSTEKAMER,
            kind=kind.raw_kind,
            external_id=external_id,
            payload_text=page,
            meta={"url": self.client.url(path), "read_on": today},
        )
