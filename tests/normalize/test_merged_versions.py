"""Which versions of an article are one: a republication that repeats the version before it."""

from __future__ import annotations

from typing import Any

from lawgraph.pipelines.normalize.bwb_history import merged_versions


def _v(key: str, start: str, effect: str, digest: str | None) -> dict[str, Any]:
    return {
        "key": key,
        "bwb_id": "BWBR0001840",
        "stam_id": "2990103",
        "valid_from": start,
        "effect": effect,
        "digest": digest,
    }


def test_a_run_of_republications_is_the_version_that_began_it() -> None:
    versions = [
        _v("a", "2002-03-21", "wijziging", "x"),
        _v("b", "2008-07-15", "tekstplaatsing-vernummering", "x"),
        _v("c", "2018-12-21", "tekstplaatsing-wijziging", "x"),
        _v("d", "2022-01-01", "wijziging", "y"),
        _v("e", "2023-01-01", "tekstplaatsing-wijziging", "z"),  # a text of its own
    ]
    assert merged_versions(versions) == {"b": "a", "c": "a"}


def test_an_amendment_that_shows_no_change_stays_a_version() -> None:
    versions = [
        _v("a", "2020-01-01", "wijziging", "x"),
        _v("b", "2024-01-01", "wijziging", "x"),
        _v("c", "2025-01-01", "tekstplaatsing-wijziging", None),  # not digested yet
    ]
    assert merged_versions(versions) == {}
