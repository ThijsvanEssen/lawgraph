"""The law as it stood on a date: each article in its place of that day, the real
``normalize bwb`` and ``normalize bwb-history`` on three toestanden of one law, and the
at-date route.

- Hoofdstuk 1 is renamed in 2025 and again in 2026, while its articles keep their versions:
  the breadcrumb of a day names the title of that day.
- Article 1:3 moves to Hoofdstuk 2 in 2025 under the same version.
- Articles 1:1a and 1:1b are inserted in 2025 and 1:1c in 2026; 1:4 and 2:2 leave the law in
  2025. A version keeps its place among the articles of every toestand that holds it, so the
  law of each day is in the order of that day's toestand.
- The articles are in force since 1994, the first toestand the source gives starts in 2018:
  before it the source gives no law, only the start of each article.
- The third toestand comes in a run with ``--since``: what the earlier run stored stays.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    SOURCE_BWB,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc

LAW = "BWBR0099001"
OLD_TITLE = "Verkeer tussen burgers en bestuursorganen"
NEW_TITLE = "Verkeer met bestuursorganen"
NEWEST_TITLE = "Verkeer met de overheid"

# number -> (stam-id, versie-id, inwerking)
ARTICLES = {
    "1:1": ("101", "1001", "1994-01-01"),
    "1:1a": ("111", "1111", "2025-01-01"),
    "1:1b": ("112", "1121", "2025-01-01"),
    "1:1c": ("113", "1131", "2026-06-01"),
    "1:2": ("102", "1002", "1994-01-01"),
    "1:3": ("103", "1003", "1994-01-01"),
    "1:4": ("104", "1004", "1994-01-01"),
    "2:1": ("201", "2001", "1994-01-01"),
    "2:2": ("202", "2002", "1994-01-01"),
}

Chapters = list[tuple[str, str, list[str]]]  # (nr, title, article numbers)
Toestand = tuple[str, str, str, str, str | None]  # kind, external id, xml, start, end

FIRST: Chapters = [
    ("1", OLD_TITLE, ["1:1", "1:2", "1:3", "1:4"]),
    ("2", "Slotbepalingen", ["2:1", "2:2"]),
]
SECOND: Chapters = [
    ("1", NEW_TITLE, ["1:1", "1:1a", "1:1b", "1:2"]),
    ("2", "Slotbepalingen", ["1:3", "2:1"]),
]
THIRD: Chapters = [
    ("1", NEWEST_TITLE, ["1:1", "1:1c", "1:1a", "1:1b", "1:2"]),
    ("2", "Slotbepalingen", ["1:3", "2:1"]),
]


def _article(chapter: str, number: str) -> str:
    stam, versie, inwerking = ARTICLES[number]
    return (
        f'<artikel bwb-ng-variabel-deel="/Hoofdstuk{chapter}/Artikel{number}" '
        f'stam-id="{stam}" versie-id="{versie}" inwerking="{inwerking}">'
        f"<kop><label>Artikel</label><nr>{number}</nr><titel>Kop {number}</titel></kop>"
        f"<al>De tekst van artikel {number}, die lang genoeg is om af te kappen.</al>"
        "</artikel>"
    )


def _toestand(start: str, chapters: Chapters) -> str:
    body = "".join(
        f'<hoofdstuk bwb-ng-variabel-deel="/Hoofdstuk{nr}">'
        f"<kop><label>Hoofdstuk</label><nr>{nr}</nr><titel>{title}</titel></kop>"
        + "".join(_article(nr, number) for number in numbers)
        + "</hoofdstuk>"
        for nr, title, numbers in chapters
    )
    return (
        f'<toestand bwb-id="{LAW}" inwerkingtreding="{start}">'
        '<wetgeving soort="wet"><intitule>Testwet</intitule>'
        "<citeertitel>Testwet</citeertitel>"
        f"<wet-besluit><wettekst>{body}</wettekst></wet-besluit></wetgeving></toestand>"
    )


def _store(store: GraphStore, toestanden: list[Toestand]) -> None:
    with RawSourceWriter(store) as writer:
        for kind, external_id, xml, start, end in toestanden:
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=kind,
                    external_id=external_id,
                    payload_text=xml,
                    meta={
                        "bwb_id": LAW,
                        "state_url": f"https://repo/{LAW}/{start}.xml",
                        "start_date": start,
                        "end_date": end,
                    },
                )
            )


def _history(start: str, end: str, chapters: Chapters) -> Toestand:
    return (
        RAW_KIND_BWB_TOESTAND_ALL,
        f"{LAW}@{start}",
        _toestand(start, chapters),
        start,
        end,
    )


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = GraphStore()
    _store(
        store,
        [
            (
                RAW_KIND_BWB_TOESTAND,
                LAW,
                _toestand("2025-01-01", SECOND),
                "2025-01-01",
                None,
            ),
            _history("2018-01-01", "2024-12-31", FIRST),
            _history("2025-01-01", "9999-12-31", SECOND),
        ],
    )
    cli("normalize", "bwb")
    cli("normalize", "bwb-history")
    since = dt.datetime.now(dt.UTC).isoformat()
    _store(
        store,
        [
            _history("2025-01-01", "2026-05-31", SECOND),
            _history("2026-06-01", "9999-12-31", THIRD),
        ],
    )
    cli("normalize", "bwb-history", "--since", since)
    cli("normalize", "bwb-history", "--since", since)  # a second run changes nothing
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, (path, response.text[:500])
    return response.json()


def _on(client: TestClient, date: str, query: str = "") -> dict[str, Any]:
    return {
        a["article_number"]: a
        for a in _get(client, f"/api/instruments/{LAW}/articles/at/{date}?{query}")[
            "items"
        ]
    }


def _crumbs(article: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(c["type"], c["label"], c["title"]) for c in article["breadcrumb"]]


def test_an_article_stands_under_the_divisions_of_that_day(
    client: TestClient,
) -> None:
    before, after, now = (
        _on(client, "2020-01-01"),
        _on(client, "2025-06-01"),
        _on(client, "2026-07-01"),
    )
    assert _crumbs(before["1:1"]) == [("hoofdstuk", "Hoofdstuk 1", OLD_TITLE)]
    assert _crumbs(after["1:1"]) == [("hoofdstuk", "Hoofdstuk 1", NEW_TITLE)]
    assert _crumbs(now["1:1"]) == [("hoofdstuk", "Hoofdstuk 1", NEWEST_TITLE)]
    assert _crumbs(before["1:3"]) == [("hoofdstuk", "Hoofdstuk 1", OLD_TITLE)]
    assert _crumbs(after["1:3"]) == [("hoofdstuk", "Hoofdstuk 2", "Slotbepalingen")]
    # an article that left the law has the place it had
    assert _crumbs(before["1:4"]) == [("hoofdstuk", "Hoofdstuk 1", OLD_TITLE)]
    assert (before["1:1"]["label"], before["1:1"]["heading"]) == (
        "Artikel 1:1",
        "Kop 1:1",
    )


def test_the_law_of_a_day_is_in_the_order_of_that_day(client: TestClient) -> None:
    assert list(_on(client, "2020-01-01")) == ["1:1", "1:2", "1:3", "1:4", "2:1", "2:2"]
    assert list(_on(client, "2025-06-01")) == [
        "1:1",
        "1:1a",
        "1:1b",
        "1:2",
        "1:3",
        "2:1",
    ]
    assert list(_on(client, "2026-07-01")) == [
        "1:1",
        "1:1c",
        "1:1a",
        "1:1b",
        "1:2",
        "1:3",
        "2:1",
    ]


def test_a_preview_leaves_the_text_out_unless_it_is_asked_for(
    client: TestClient,
) -> None:
    whole = _on(client, "2020-01-01")["1:1"]
    assert whole["text"].startswith("De tekst van artikel 1:1")
    preview = _on(client, "2020-01-01", "text_preview_chars=12")["1:1"]
    assert preview["text"] is None and preview["text_preview"] == whole["text"][:12]
    both = _on(client, "2020-01-01", "text_preview_chars=12&include_text=true")["1:1"]
    assert both["text"] == whole["text"] and both["text_preview"] == whole["text"][:12]


def test_before_the_first_toestand_the_source_gives_no_law(
    client: TestClient,
) -> None:
    body = _get(client, f"/api/instruments/{LAW}/articles/at/2000-01-01")
    assert (body["total"], body["items"]) == (0, [])
    assert body["first_version_from"] == "2018-01-01"
    versions = _get(client, f"/api/instruments/{LAW}/versions")["items"]
    assert min(v["valid_from"] for v in versions) == body["first_version_from"]
    # the articles keep the start the source gives them
    history = _get(client, f"/api/articles/{LAW}/1:1/history")["versions"]
    assert [v["valid_from"] for v in history] == ["1994-01-01"]
