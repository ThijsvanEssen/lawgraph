"""When the Tweede Kamer last met and voted, and when it meets and votes next: from its
activities (``Activiteit``: ``Soort``, ``Status``, ``Datum`` and ``DatumSoort``), on a real
PostgreSQL, through ``chamber_schedule`` of ``GET /api/feed/summary``."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.api.routes import feed as feed_route
from lawgraph.config.constants import COLLECTION_ACTIVITIES, RAW_KIND_TK_ACTIVITEIT
from lawgraph.db import GraphStore
from lawgraph.db.queries.activities import get_chamber_schedule
from lawgraph.pipelines.normalize.tk_dossiers import TKDossiersNormalizePipeline
from tests.databases import Api
from tests.integration.seed import write_tk
from tests.optional import present

TODAY = "2026-10-21"


def _activity(
    key: str,
    date: str,
    kind: str,
    status: str,
    precision: str = "Dag",
    **props: Any,
) -> dict[str, Any]:
    return {
        "key": key,
        "type": "activity",
        "labels": [],
        "props": {
            "date": date,
            "kind": kind,
            "status": status,
            "precision": precision,
            "number": key.upper(),
            "agenda_title": kind,
            **props,
        },
    }


# The herfstreces of 2026: the Kamer last met on Thursday 15 October, voted last on
# Wednesday 14 October, and meets and votes again on Tuesday 27 October; the votes on
# every budget are planned for the week of 7 December, not yet for a day.
RECESS = [
    _activity("2026a1", "2026-10-14", "Stemmingen", "Uitgevoerd"),
    _activity("2026a2", "2026-10-15", "Plenair debat (wetgeving)", "Uitgevoerd"),
    _activity("2026a3", "2026-10-15", "Hamerstukken", "Uitgevoerd"),
    # a committee meets in the recess: no sitting of the Kamer
    _activity("2026a4", "2026-10-20", "Commissiedebat", "Uitgevoerd"),
    _activity("2026a5", "2026-10-22", "Werkbezoek", "Gepland", "Meerdaags"),
    # votes called off are none
    _activity("2026a6", "2026-10-20", "Stemmingen", "Geannuleerd"),
    _activity("2026a7", "2026-10-27", "Stemmingen", "Gepland"),
    _activity("2026a8", "2026-10-27", "Vragenuur", "Gepland"),
    _activity("2026a9", "2026-12-07", "Stemmingen", "Gepland", "Weeknummer",
              agenda_title="Stemmingen over alle begrotingen"),
]  # fmt: skip


@pytest.fixture()
def recess(store: GraphStore) -> GraphStore:
    store.bulk_insert_or_update_nodes(COLLECTION_ACTIVITIES, RECESS)
    return store


def _keys(schedule: dict[str, Any]) -> dict[str, str | None]:
    return {part: (row or {}).get("key") for part, row in schedule.items()}


def test_the_schedule_is_the_last_and_next_sitting_and_votes(
    recess: GraphStore,
) -> None:
    assert _keys(get_chamber_schedule(recess, TODAY)) == {
        "last_sitting": "2026a3",
        "last_votes": "2026a1",
        # the votes are a sitting too: of one day the first by key
        "next_sitting": "2026a7",
        "next_votes": "2026a7",
    }


def test_votes_planned_for_a_week_come_after_those_planned_for_a_day(
    recess: GraphStore,
) -> None:
    after = get_chamber_schedule(recess, "2026-10-28")
    assert after["next_votes"]["key"] == "2026a9"
    assert after["next_votes"]["props"]["precision"] == "Weeknummer"
    # a day in the week of a vote planned for that week: the day it is planned for first
    recess.bulk_insert_or_update_nodes(
        COLLECTION_ACTIVITIES,
        [_activity("2026a10", "2026-12-08", "Stemmingen", "Gepland")],
    )
    assert get_chamber_schedule(recess, "2026-10-28")["next_votes"]["key"] == "2026a10"


def test_a_vote_on_the_day_itself_is_still_next_until_it_was_held(
    recess: GraphStore,
) -> None:
    on_the_day = get_chamber_schedule(recess, "2026-10-27")
    assert on_the_day["next_votes"]["key"] == "2026a7"
    assert on_the_day["last_votes"]["key"] == "2026a1"


def test_nothing_planned_or_held_is_null(store: GraphStore) -> None:
    assert _keys(get_chamber_schedule(store, TODAY)) == {
        "last_sitting": None,
        "last_votes": None,
        "next_sitting": None,
        "next_votes": None,
    }


def test_the_summary_says_when_the_kamer_meets_and_votes(
    recess: GraphStore, api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(feed_route, "dutch_today", lambda: dt.date(2026, 10, 21))
    schedule = api.get_json("/api/feed/summary", days=1)["chamber_schedule"]
    assert schedule["next_votes"] == {
        "id": "activities/2026a7",
        "key": "2026a7",
        "number": "2026A7",
        "kind": "Stemmingen",
        "date": "2026-10-27",
        "precision": "Dag",
        "agenda_title": "Stemmingen",
        "tk_url": "https://www.tweedekamer.nl/debat_en_vergadering/plenaire_vergaderingen"
        "/details/activiteit?id=2026A7",
        "path": "/activiteiten/2026A7",
    }
    assert schedule["last_votes"]["date"] == "2026-10-14"
    assert schedule["last_sitting"]["date"] == "2026-10-15"
    assert schedule["next_sitting"]["date"] == "2026-10-27"


def test_normalize_activities_reads_every_stored_activity_again(
    store: GraphStore,
) -> None:
    """``normalize tk-dossiers --activities``: every stored Activiteit record again into
    its node, also one stored before its node took ``precision``."""
    write_tk(
        store,
        [
            (
                RAW_KIND_TK_ACTIVITEIT,
                {
                    "Id": "a-week",
                    "Nummer": "2026A05472",
                    "Soort": "Stemmingen",
                    "Status": "Gepland",
                    "Datum": "2026-12-07T00:00:00+01:00",
                    "DatumSoort": "Weeknummer",
                },
            )
        ],
    )
    TKDossiersNormalizePipeline(store=store, activities=True).run()
    props = present(store.get_document(COLLECTION_ACTIVITIES, "a_week"))["props"]
    assert (props["date"], props["precision"]) == ("2026-12-07", "Weeknummer")
