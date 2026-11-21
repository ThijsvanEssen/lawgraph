"""Which dossier a search finds plays now (``api.active_dossier.playing``)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.api.active_dossier import playing

TODAY = dt.date(2026, 11, 21)


def _hit(key: str, score: float, last_activity: str | None) -> dict[str, Any]:
    return {"key": key, "score": score, "extra": {"last_activity": last_activity}}


def test_a_dossier_quiet_for_more_than_30_days_does_not_play() -> None:
    hits = [_hit("a", 0.75, "2026-10-21"), _hit("b", 0.2, None)]
    assert playing(hits, TODAY) is None
    assert playing([], TODAY) is None


def test_a_dossier_active_30_days_ago_still_plays() -> None:
    hit = _hit("a", 0.2, "2026-10-22")
    assert playing([hit], TODAY) is hit


def test_the_best_title_match_before_the_newest_activity() -> None:
    hits = [
        _hit("new", 0.2, "2026-11-20"),
        _hit("named", 0.75, "2026-11-01"),
        _hit("quiet", 1.0, "2025-01-01"),
    ]
    assert playing(hits, TODAY)["key"] == "named"  # type: ignore[index]


def test_of_matches_alike_the_newest_activity_then_the_first_key() -> None:
    hits = [
        _hit("b", 0.25, "2026-11-01"),
        _hit("c", 0.25, "2026-11-10"),
        _hit("a", 0.25, "2026-11-10"),
    ]
    assert playing(hits, TODAY)["key"] == "a"  # type: ignore[index]
