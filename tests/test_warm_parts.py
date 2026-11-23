"""The parts of the warm-up: one name each (what is kept of a part is kept by its name)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from lawgraph.api import warm
from lawgraph.core.feed import EVENT_VOTE
from lawgraph.db import version_cache


def test_every_part_has_its_own_name() -> None:
    names = [part.name for part in (*warm.PARTS, *warm.TAIL)]
    assert len(names) == len(set(names))


def test_the_first_warm_up_goes_on_while_the_data_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """During a run the data never stands still: without this, an API started then has no
    earlier answer to give for as long as the run lasts. A later warm-up stops."""

    class Moving:
        name = "moving"

        def __init__(self) -> None:
            self.reads = 0

        def data_version(self, tables: object = None) -> str:
            self.reads += 1
            return str(self.reads)

        def table_versions(self) -> dict[str, int]:
            return {}

    ran: list[str] = []

    def part(name: str) -> warm.Part:
        return warm.Part(name, lambda _store: ran.append(name))

    parts = (part("a"), part("b"))
    monkeypatch.setattr(warm, "_warmed", None)
    assert warm._warm_lane(Moving(), "0", parts)  # type: ignore[arg-type]
    assert ran == ["a", "b"]

    monkeypatch.setattr(warm, "_warmed", "0")
    ran.clear()
    assert not warm._warm_lane(Moving(), "0", parts)  # type: ignore[arg-type]
    assert ran == []
    assert version_cache.superseded(Moving(), "0")


def _vote(number: str, day: str, chamber: str = "TK", **props: Any) -> dict[str, Any]:
    return {
        "kind": EVENT_VOTE,
        "id": f"decisions/{number}-{chamber}",
        "date": day,
        "dossier": {"key": number, "number": number},
        "props": {"kind": "Wetgeving", "passed": True, "chamber": chamber, **props},
    }


def test_the_bills_of_the_homepage_are_warmed_as_its_network_tries_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The passed bills of the summary, newest first and the Eerste Kamer first on a day,
    then those of the votes of the Eerste Kamer, until one changes an article: a budget, a
    vote that failed and a dossier asked already are left."""
    summary = [
        _vote("36001", "2026-11-18"),
        _vote("36002", "2026-11-20", passed=False),
        _vote("36003", "2026-11-20", kind="Begroting"),
        _vote("36004", "2026-11-19"),
        _vote("36005", "2026-11-19", "EK"),
    ]
    older = [_vote("36001", "2026-11-10", "EK"), _vote("36006", "2026-11-03", "EK")]
    monkeypatch.setattr(warm, "get_feed_summary", lambda *a, **k: {"items": summary})
    monkeypatch.setattr(warm, "get_feed", lambda *a, **k: {"items": older})
    asked: list[str] = []

    def changed(number: str, store: object) -> SimpleNamespace:
        asked.append(number)
        return SimpleNamespace(total=int(number == "36006"))

    monkeypatch.setattr(warm, "get_changed_articles", changed)
    warm._warm_home_bills(object())  # type: ignore[arg-type]

    assert asked == ["36005", "36004", "36001", "36006"]


def test_the_bills_of_the_homepage_stop_at_the_first_that_changes_an_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bills = [_vote(str(36000 + n), f"2026-11-{10 + n}") for n in range(9)]
    monkeypatch.setattr(warm, "get_feed_summary", lambda *a, **k: {"items": bills})
    monkeypatch.setattr(warm, "get_feed", lambda *a, **k: {"items": bills})
    asked: list[str] = []

    def changed(number: str, store: object) -> SimpleNamespace:
        asked.append(number)
        return SimpleNamespace(total=0)

    monkeypatch.setattr(warm, "get_changed_articles", changed)
    warm._warm_home_bills(object())  # type: ignore[arg-type]

    assert len(asked) == warm.HOME_BILLS
