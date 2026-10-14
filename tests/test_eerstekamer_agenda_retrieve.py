"""How ``retrieve eerstekamer-agenda`` walks the agendas: forward to the last one planned,
back to the window's start, and a run over everything on from where one broke off."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.pipelines.retrieve import base as retrieve_base
from lawgraph.pipelines.retrieve import eerstekamer_agenda as retrieve


def _plenary(day: str) -> str:
    return f"/plenaire_vergadering/{day.replace('-', '')}"


class _Client:
    """Plenary sittings on four days; committee pages without meetings."""

    days = ["2026-09-22", "2026-09-29", "2026-10-06", "2026-10-13"]

    def __init__(self) -> None:
        self.read: list[str] = []

    def url(self, path: str) -> str:
        return "https://www.eerstekamer.nl" + path

    def page_at(self, path: str) -> tuple[str, str]:
        self.read.append(path)
        if path == "/menukeuze_plenair":
            path = _plenary("2026-10-06")
        return path, path


def _read(client: _Client) -> Any:
    def read(path: str, page: str) -> retrieve.Page:
        if not path.startswith("/plenaire_vergadering/"):
            return retrieve.Page(None, None, None, None)
        day = f"{path[-8:-4]}-{path[-4:-2]}-{path[-2:]}"
        i = client.days.index(day)
        earlier = _plenary(client.days[i - 1]) if i else None
        later = _plenary(client.days[i + 1]) if i + 1 < len(client.days) else None
        return retrieve.Page(day, path, earlier, later)

    return read


class _Store:
    def __init__(self) -> None:
        self.stored: list[str] = []

    def insert_raw_sources(self, docs: list[dict]) -> list:
        self.stored.extend(doc["external_id"] for doc in docs)
        return []


def _write_every(monkeypatch: Any, max_records: int) -> None:
    """The writer stores its buffer every *max_records* records (and at the end)."""
    real_writer = retrieve_base.RawSourceWriter
    monkeypatch.setattr(
        retrieve_base,
        "RawSourceWriter",
        lambda store, **kw: real_writer(store, max_records=max_records, **kw),
    )


def _run(monkeypatch: Any, since: dt.date | None, saved: dict | None) -> tuple:
    client = _Client()
    states: list[Any] = []
    monkeypatch.setattr(retrieve.state, "get_state", lambda store, key: saved)
    monkeypatch.setattr(
        retrieve.state, "set_state", lambda store, key, doc: states.append(doc)
    )
    kinds = tuple(
        retrieve._Kind(k.name, k.raw_kind, k.start, _read(client))
        for k in retrieve.KINDS
    )
    monkeypatch.setattr(retrieve, "KINDS", kinds)
    store = _Store()
    pipeline = retrieve.EerstekamerAgendaRetrievePipeline(store, client)  # type: ignore[arg-type]
    assert pipeline.run(since=since).errors == []
    return store.stored, states


def test_a_window_reads_what_is_planned_and_back_to_its_start(monkeypatch: Any) -> None:
    ids, states = _run(monkeypatch, dt.date(2026, 9, 25), None)
    assert ids == [
        _plenary("2026-10-06"),
        _plenary("2026-10-13"),
        _plenary("2026-09-29"),
    ]
    assert states == []  # a window keeps no state


def test_a_run_over_everything_keeps_where_it_is_and_ends_clean(
    monkeypatch: Any,
) -> None:
    _write_every(monkeypatch, 1)
    ids, states = _run(monkeypatch, None, None)
    assert _plenary("2026-09-22") in ids
    assert {"plenary": "done", "committee": "done"} in states
    assert states[-1] is None  # the run ended: nothing to go on from


def test_a_run_that_broke_off_goes_on_from_where_it_got_to(monkeypatch: Any) -> None:
    ids, _ = _run(
        monkeypatch, None, {"plenary": _plenary("2026-09-22"), "committee": "done"}
    )
    # forward again, then back from where it got to, not from today's sitting
    assert ids == [
        _plenary("2026-10-06"),
        _plenary("2026-10-13"),
        _plenary("2026-09-22"),
    ]


class _Crash(BaseException):
    """The process dies: nothing after it runs, so no buffer is written."""


def _crash_at(
    monkeypatch: Any, day: str, *, max_records: int
) -> tuple[list[str], dict | None]:
    """Run over everything until reading the sitting of *day* kills the process; what was
    stored and what the state said at that moment."""
    client = _Client()
    store = _Store()
    saved: list[Any] = [None]
    at_crash: dict[str, Any] = {}
    monkeypatch.setattr(retrieve.state, "get_state", lambda store, key: saved[-1])
    monkeypatch.setattr(
        retrieve.state, "set_state", lambda store, key, doc: saved.append(doc)
    )
    read = _read(client)

    def dying(path: str, page: str) -> Any:
        if path == _plenary(day):
            at_crash.update(stored=list(store.stored), state=saved[-1])
            raise _Crash
        return read(path, page)

    kinds = tuple(
        retrieve._Kind(k.name, k.raw_kind, k.start, dying) for k in retrieve.KINDS
    )
    monkeypatch.setattr(retrieve, "KINDS", kinds)
    _write_every(monkeypatch, max_records)
    pipeline = retrieve.EerstekamerAgendaRetrievePipeline(store, client)  # type: ignore[arg-type]
    with pytest.raises(_Crash):
        pipeline.run()
    return at_crash["stored"], at_crash["state"]


def test_a_crash_before_the_buffer_is_written_keeps_no_resume_point_past_it(
    monkeypatch: Any,
) -> None:
    stored, saved = _crash_at(monkeypatch, "2026-09-22", max_records=500)
    assert stored == []  # the buffer was not written
    # the next run walks back from today's sitting again, not past 29 September
    assert not (saved or {}).get("plenary")


def test_the_resume_point_follows_what_was_written(monkeypatch: Any) -> None:
    stored, saved = _crash_at(monkeypatch, "2026-09-22", max_records=1)
    assert _plenary("2026-09-29") in stored
    assert saved == {"plenary": _plenary("2026-09-22")}
