"""The composition of the Eerste Kamer from its stored versions: the snapshot of a day is
the newest version of every page read on or before it, and walking the same versions gives
the same periods."""

from __future__ import annotations

import re
from typing import Any

import pytest

from lawgraph.core import ek_composition as ec
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.pipelines.normalize import eerstekamer_composition as composition
from tests.fakes import InMemoryStore
from tests.paths import fixture_text

D66 = "/fractie/democraten_1966"
CROLL = "/persoon/mr_r_s_croll_d66"


def _version(path: str, day: str, text: str) -> dict[str, Any]:
    return {
        "external_id": ec.version_id(path, day),
        "payload_text": text,
        "meta": {"read_on": day, "last_read_on": day},
    }


def _versions() -> list[dict[str, Any]]:
    """The listing and D66 on 2026-09-30, D66 without Croll on 2026-10-07."""
    d66 = fixture_text("ek_faction_d66.html")
    without = re.sub(
        rf'<li class="persoon[^"]*">\s*<a href="{CROLL}">.*?</li>', "", d66, flags=re.S
    )
    return [
        _version(ec.FACTIONS_PATH, "2026-09-30", fixture_text("ek_factions.html")),
        _version(D66, "2026-09-30", d66),
        _version(D66, "2026-10-07", without),
    ]


def test_the_snapshot_of_a_day_is_the_newest_version_of_each_page() -> None:
    days = [
        (day, [r["external_id"] for r in read], sorted(newest))
        for day, read, newest in ec.versions_by_day(reversed(_versions()))
    ]

    assert days == [
        ("2026-09-30", [f"{D66}@2026-09-30", "/fracties@2026-09-30"], [D66, "/fracties"]),
        ("2026-10-07", [f"{D66}@2026-10-07"], [D66, "/fracties"]),
    ]  # fmt: skip
    newest = ec.newest_versions(_versions())
    assert newest[D66]["external_id"] == f"{D66}@2026-10-07"
    # a page stored by its path alone is a version of that path
    assert ec.page_path(D66) == ec.page_path(ec.version_id(D66, "2026-10-07")) == D66


@pytest.fixture()
def pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> composition.EerstekamerCompositionNormalizePipeline:
    monkeypatch.setattr(normalize_tk, "members_born_on", lambda *_a: [])
    return composition.EerstekamerCompositionNormalizePipeline(store=InMemoryStore())


def test_the_same_versions_give_the_same_periods(
    pipeline: composition.EerstekamerCompositionNormalizePipeline,
) -> None:
    first = pipeline.observe(_versions())
    again = pipeline.observe(list(reversed(_versions())))

    assert first is not None and first == again
    croll = first.members[CROLL].props["ek"]
    assert (croll["observed_from"], croll["observed_until"]) == (
        "2026-09-30",
        "2026-10-07",
    )
    assert first.factions["ek_democraten_1966"]["data_since"] == "2026-09-30"
    assert (
        first.edges[("members/ek_mr_r_s_croll_d66", "factions/ek_democraten_1966")][
            "observed_until"
        ]
        == "2026-10-07"
    )


def test_the_observed_composition_is_walked_on_from(
    pipeline: composition.EerstekamerCompositionNormalizePipeline,
) -> None:
    """The versions the observed composition covers are not walked again; a later one is,
    from the periods it holds."""
    held = {
        "factions": [
            {
                "key": "ek_democraten_1966",
                "props": {
                    "chamber": "EK",
                    "observed_from": "2019-06-11",
                    "data_since": "2019-06-11",
                    "seats": 7,
                    "colors": ["#00D84B"],  # not this pipeline's: left out
                },
            }
        ],
        "committees": [],
        "members": [
            {
                "key": "ek_mr_r_s_croll_d66",
                "ek": {
                    "path": CROLL,
                    "faction": "ek_democraten_1966",
                    "observed_from": "2019-06-11",
                    "observed_until": None,
                },
                "name": "mr. R.S. Croll",
                "birth_date": None,
            }
        ],  # fmt: skip
        "edges": [],
        "covers": ["/fracties@2026-09-30", f"{D66}@2026-09-30"],
    }
    observed = {"kind": "ek-composition-observed", "payload_json": held}

    state = pipeline.observe([observed, *_versions()])

    assert state is not None
    croll = state.members[CROLL].props["ek"]
    assert (croll["observed_from"], croll["observed_until"]) == (
        "2019-06-11",
        "2026-10-07",
    )
    faction = state.factions["ek_democraten_1966"]
    assert (faction["observed_from"], faction["data_since"]) == (
        "2019-06-11",
        "2019-06-11",
    )
    assert "colors" not in faction
