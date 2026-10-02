"""How ``retrieve eerstekamer-agenda`` walks the agendas: forward to the last one planned,
back to the window's start, and a run over everything on from where one broke off."""

from __future__ import annotations

import datetime as dt
from typing import Any

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
    def read(path: str, page: str) -> tuple[str | None, ...]:
        if not path.startswith("/plenaire_vergadering/"):
            return None, None, None, None
        day = f"{path[-8:-4]}-{path[-4:-2]}-{path[-2:]}"
        i = client.days.index(day)
        earlier = _plenary(client.days[i - 1]) if i else None
        later = _plenary(client.days[i + 1]) if i + 1 < len(client.days) else None
        return day, path, earlier, later

    return read


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
    pipeline = object.__new__(retrieve.EerstekamerAgendaRetrievePipeline)
    pipeline.client = client  # type: ignore[assignment]
    pipeline.store = None  # type: ignore[assignment]
    records = list(pipeline.fetch(since=since))
    return [r.external_id for r in records], states


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
