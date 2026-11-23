"""The numbers of an article over its versions (``core.amount_series``): the version in force
on a day, and the series of each number, which stops where its part holds another count."""

from __future__ import annotations

from typing import Any

from lawgraph.core.amount_series import series, version_on, versions


def _row(
    key: str, start: str, until: str | None, value: float | None = None, at: int = 0
) -> dict[str, Any]:
    """A row of ``amounts.article_amounts``: an amount of lid 2, or a version without one."""
    return {
        "version_key": key,
        "version_from": start,
        "version_until": until,
        "current": until is None,
        "kind": None if value is None else "bedrag",
        "part": "lid-2",
        "source": "text",
        "valid_from": None,
        "date": None,
        "value": value,
        "span_start": at,
    }


ROWS = [
    _row("v1", "2023-01-01", "2024-01-01", 3070.0, at=10),
    _row("v2", "2024-01-01", "2025-01-01", 3362.0, at=10),
    _row("v2", "2024-01-01", "2025-01-01", 24812.0, at=40),
    _row("v3", "2025-01-01", None, 3068.0, at=10),
    _row("v3", "2025-01-01", None, 28406.0, at=40),
    _row("v4", "2026-01-01", None),  # a version without numbers
]


def test_a_day_picks_its_version_and_none_the_current_one() -> None:
    found = versions(ROWS)
    assert [v.key for v in found] == ["v1", "v2", "v3", "v4"]
    assert found[3].rows == []
    assert version_on(found, "2024-06-30") == 1
    assert version_on(found, "2025-01-01") == 2
    assert version_on(found, "2000-01-01") is None
    assert version_on(found, None) == 3  # the last current one
    assert version_on([], None) is None


def test_a_series_runs_while_the_part_holds_as_many_numbers() -> None:
    found = versions(ROWS[:5])
    pairs = series(found, 2)
    assert [
        [
            (s["version_key"], s["valid_from"], s["valid_until"], s["value"])
            for s in steps
        ]
        for _, steps in pairs
    ] == [
        [
            ("v2", "2024-01-01", "2025-01-01", 3362.0),
            ("v3", "2025-01-01", None, 3068.0),
        ],
        [
            ("v2", "2024-01-01", "2025-01-01", 24812.0),
            ("v3", "2025-01-01", None, 28406.0),
        ],
    ]
    # v1 held one amount in lid-2, not two: which of them it is, is not guessed
    assert [steps[0]["version_key"] for _, steps in series(found, 0)] == ["v1"]
