"""Article history, amended-by and instrument dossiers (AMENDS / LEGISLATED_IN model).

The query functions are replaced by stand-ins that record what the route asked for; how
the versions, amending publications and dossiers are found is in
``tests/pg/test_relation_history.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.db.queries.articles import ArticleHistoryData
from lawgraph.db.queries.instruments import AmendedByData
from lawgraph.db.queries.not_found import NotFound
from tests.api.stubs import stub_route
from tests.asserts import assert_status

client = TestClient(app)

BWB = "BWBR0001854"


def _article(stam_id: str | None = "stam-1") -> dict[str, Any]:
    props: dict[str, Any] = {"bwb_id": BWB, "article_number": "287"}
    if stam_id:
        props["stam_id"] = stam_id
    return {
        "id": f"articles/{BWB}_287",
        "key": f"{BWB}_287",
        "props": props,
    }


def _pub(number: int, dossiers: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": f"stb-2019-{number}",
        "kind": "Stb",
        "year": 2019,
        "number": str(number),
        "effect": "wijziging",
        "signed": "2019-01-01",
        "published": "2019-01-02",
        "dossiers": dossiers or [],
    }


def _version(
    i: int, *, effect: str | None = "wijziging", dossiers: list[str] | None = None
) -> dict[str, Any]:
    return {
        "id": f"article_versions/v{i}",
        "key": f"v{i}",
        "props": {
            "bwb_id": BWB,
            "stam_id": "stam-1",
            "versie_id": f"ver-{i}",
            "article_number": "287" if i else "286",
            "valid_from": f"2000-01-{i + 1:02d}",
            "valid_until": None,
            "current": False,
            "text": f"text {i}",
            "effect": effect,
            "source_publication": f"Stb.2019-{i}",
            "origin_publication": _pub(i, dossiers),
            "commencement_publication": _pub(100 + i, dossiers),
        },
    }


def _history(
    monkeypatch: pytest.MonkeyPatch,
    article: dict[str, Any] | None,
    versions: list[dict[str, Any]] | None = None,
    dossier_titles: dict[str, str | None] | None = None,
) -> list[tuple[str, str]]:
    """Stand in for ``get_article_history``; returns the (law, article) pairs asked for."""
    asked: list[tuple[str, str]] = []

    def get_article_history(
        store: Any, bwb_id: str, article_number: str
    ) -> ArticleHistoryData:
        asked.append((bwb_id, article_number))
        if article is None:
            raise NotFound("Article", bwb_id)
        return ArticleHistoryData(
            article=article,
            versions=versions or [],
            dossier_titles=dossier_titles or {},
        )

    stub_route(monkeypatch, "articles", get_article_history=get_article_history)
    return asked


def _amended_by(
    monkeypatch: pytest.MonkeyPatch, data: AmendedByData
) -> list[dict[str, Any]]:
    """Stand in for ``get_instrument_amended_by``; returns the calls it got."""
    asked: list[dict[str, Any]] = []

    def get_instrument_amended_by(
        store: Any, identifier: str, *, limit: int, offset: int, sort: str
    ) -> AmendedByData:
        asked.append({"identifier": identifier, "limit": limit, "offset": offset})
        return data

    stub_route(
        monkeypatch, "instruments", get_instrument_amended_by=get_instrument_amended_by
    )
    return asked


# ── GET /api/articles/{bwb_id}/{article_number}/history ─────────────────────


def test_history_returns_versions_with_documents_and_dossier_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _history(
        monkeypatch,
        _article(),
        versions=[
            _version(0, effect="nieuw", dossiers=["35786"]),
            _version(1, effect="wijziging"),
            _version(2, effect="vervallen"),
            _version(3, effect="onbekend"),
        ],
        dossier_titles={"35786": "Wijziging Burgerlijk Wetboek"},
    )

    response = client.get(f"/api/articles/{BWB}/287/history")

    assert_status(response, 200)
    assert asked == [(BWB, "287")]
    body = response.json()
    assert body["bwb_id"] == BWB
    assert body["article_number"] == "287"
    assert body["stam_id"] == "stam-1"
    assert [v["key"] for v in body["versions"]] == ["v0", "v1", "v2", "v3"]
    first = body["versions"][0]
    assert first["article_number"] == "286"  # number at that version
    assert first["effect"] == "nieuw"
    assert first["change"] == "introduces"
    assert body["versions"][1]["change"] == "amends"
    assert body["versions"][2]["change"] == "repeals"
    assert body["versions"][3]["change"] is None
    assert first["amended_by"]["id"] == "stb-2019-0"
    assert first["amended_by"]["kind"] == "Stb"
    assert first["amended_by"]["year"] == 2019
    assert first["amended_by"]["dossiers"] == [
        {
            "number": "35786",
            "key": "35786",
            "title": "Wijziging Burgerlijk Wetboek",
            "short_title": None,
            "exists": True,
            "path": "/dossiers/35786",
            "id": "dossiers/35786",
        }
    ]
    assert first["commencement"]["id"] == "stb-2019-100"


def test_history_unknown_article_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _history(monkeypatch, None)

    response = client.get(f"/api/articles/{BWB}/999/history")

    assert_status(response, 404)
    assert asked == [(BWB, "999")]


def test_history_without_stam_id_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    _history(monkeypatch, _article(stam_id=None), versions=[_version(1)])

    response = client.get(f"/api/articles/{BWB}/287/history")

    assert_status(response, 200)
    assert response.json()["stam_id"] is None
    assert [v["key"] for v in response.json()["versions"]] == ["v1"]


def test_history_without_versions_is_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _history(monkeypatch, _article(), versions=[])

    response = client.get(f"/api/articles/{BWB}/287/history")

    assert_status(response, 200)
    assert response.json()["versions"] == []


def test_a_dossier_not_in_the_data_has_no_id_and_no_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A publication names a dossier the data does not hold (7:611 BW, 23438): its number
    stays, but no id and no address, which would lead to a 404."""
    _history(
        monkeypatch,
        _article(),
        versions=[_version(1, dossiers=["12345", "35786"])],
        dossier_titles={"35786": None},
    )

    body = client.get(f"/api/articles/{BWB}/287/history").json()

    assert body["versions"][0]["amended_by"]["dossiers"] == [
        {
            "number": "12345",
            "key": "12345",
            "title": None,
            "short_title": None,
            "exists": False,
            "path": None,
            "id": None,
        },
        {
            "number": "35786",
            "key": "35786",
            "title": None,
            "short_title": None,
            "exists": True,
            "path": "/dossiers/35786",
            "id": "dossiers/35786",
        },
    ]


def _worded(key: str, text: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    """A version of article 287 with *text* and its *parts* (``id``, ``kind``,
    ``number``, ``term`` and the span of ``text`` they cover)."""
    return {
        "id": f"article_versions/{key}",
        "key": key,
        "props": {"bwb_id": BWB, "stam_id": "stam-1", "text": text, "parts": parts},
    }


def _lid(number: str, text: str, at: int) -> dict[str, Any]:
    return {
        "id": f"lid-{number}",
        "kind": "lid",
        "number": number,
        "start": at,
        "end": at + len(text),
    }


def _leden(*leden: str) -> tuple[str, list[dict[str, Any]]]:
    """The text of an article with these leden, numbered from 1, and its parts."""
    text, parts = "", []
    for number, lid in enumerate(leden, 1):
        head = f"{number}. "
        parts.append(_lid(str(number), lid, len(text) + len(head)))
        text += f"{head}{lid}\n"
    return text.rstrip("\n"), parts


def test_history_lists_the_versions_without_their_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _history(monkeypatch, _article(), versions=[_version(0), _version(1)])

    body = client.get(f"/api/articles/{BWB}/287/history").json()

    for version in body["versions"]:
        assert not {"text", "parts", "tables"} & version.keys()


def test_history_says_which_versions_changed_the_text_and_which_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _leden("Een.", "Twee.")
    # The same wording again, with a non-breaking space where the last had a space.
    moved = (first[0].replace("1. ", "1.\u00a0"), first[1])
    amended = _leden("Een.", "Twee, anders.", "Drie.")
    defined: tuple[str, list[dict[str, Any]]] = (
        "verstaan onder:\nbank: een bank;\nkas: een kas.",
        [
            {"id": "aanhef", "kind": "aanhef", "number": None, "start": 0, "end": 15},
            {"id": "tekst-1", "kind": "tekst", "term": "bank", "start": 16, "end": 31},
            {"id": "tekst-2", "kind": "tekst", "term": "kas", "start": 32, "end": 45},
        ],
    )
    redefined: tuple[str, list[dict[str, Any]]] = (
        "verstaan onder:\nkas: een geldkas.",
        [
            {"id": "aanhef", "kind": "aanhef", "number": None, "start": 0, "end": 15},
            {"id": "tekst-1", "kind": "tekst", "term": "kas", "start": 16, "end": 33},
        ],
    )
    _history(
        monkeypatch,
        _article(),
        versions=[
            _worded("v0", *first),
            _worded("v1", *moved),
            _worded("v2", *amended),
            _worded("v3", *defined),
            _worded("v4", *redefined),
        ],
    )

    versions = client.get(f"/api/articles/{BWB}/287/history").json()["versions"]

    assert [v["text_changed"] for v in versions] == [True, False, True, True, True]
    assert [v["changes"] for v in versions[:3]] == [
        [],
        [],
        [
            {"change": "changed", "kind": "lid", "number": "2", "term": None},
            {"change": "added", "kind": "lid", "number": "3", "term": None},
        ],
    ]
    assert versions[4]["changes"] == [
        {"change": "changed", "kind": "tekst", "number": None, "term": "kas"},
        {"change": "removed", "kind": "tekst", "number": None, "term": "bank"},
    ]


def _one_version(
    monkeypatch: pytest.MonkeyPatch, version: dict[str, Any] | None
) -> list[tuple[str, str, str]]:
    """Stand in for ``get_article_version``; returns what it was asked for."""
    asked: list[tuple[str, str, str]] = []

    def get_article_version(
        store: Any, bwb_id: str, article_number: str, key: str
    ) -> ArticleHistoryData:
        asked.append((bwb_id, article_number, key))
        if version is None:
            raise NotFound("Article version", key)
        return ArticleHistoryData(
            article=_article(),
            versions=[version],
            dossier_titles={"35786": "Wijziging Burgerlijk Wetboek"},
        )

    stub_route(monkeypatch, "articles", get_article_version=get_article_version)
    return asked


def test_one_version_with_its_text_and_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    version = _worded("v2", *_leden("Een.", "Twee."))
    version["props"]["origin_publication"] = _pub(2, ["35786"])
    asked = _one_version(monkeypatch, version)

    response = client.get(f"/api/articles/{BWB}/287/history/v2")

    assert_status(response, 200)
    assert asked == [(BWB, "287", "v2")]
    body = response.json()
    assert body["key"] == "v2"
    assert body["text"] == "1. Een.\n2. Twee."
    assert [(p["id"], p["text"]) for p in body["parts"]] == [
        ("lid-1", "Een."),
        ("lid-2", "Twee."),
    ]
    assert body["amended_by"]["dossiers"][0]["title"] == "Wijziging Burgerlijk Wetboek"


def test_a_version_of_another_article_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _one_version(monkeypatch, None)

    response = client.get(f"/api/articles/{BWB}/287/history/v9")

    assert_status(response, 404)


# ── GET /api/instruments/{bwb_id}/amended-by ────────────────────────────────


def _amending(number: int, **extra: Any) -> dict[str, Any]:
    props = {
        "display_name": f"Stb. 2019, {number}",
        "publication_kind": "Stb",
        "publication_year": 2019,
        "publication_number": str(number),
        "date_signed": "2019-01-01",
        "date_published": "2019-01-02",
        "dossier_numbers": ["35786"],
    }
    props.update(extra)
    return {
        "id": f"instruments/stb-2019-{number}",
        "key": f"stb-2019-{number}",
        "props": props,
    }


def _aggregate(number: int, **counts: Any) -> dict[str, Any]:
    row = {
        "instrument": _amending(number),
        "amends": 2,
        "introduces": 1,
        "repeals": 0,
        "articles_affected": 3,
        "first_effective_date": "2019-07-01",
    }
    row.update(counts)
    return row


def test_amended_by_maps_rows_and_dossier_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _amended_by(
        monkeypatch,
        AmendedByData(
            items=[_aggregate(33), _aggregate(12, repeals=4)],
            total=7,
            dossier_titles={"35786": "Klimaatwet"},
        ),
    )

    response = client.get(f"/api/instruments/{BWB}/amended-by?limit=2&offset=5")

    assert_status(response, 200)
    assert asked == [{"identifier": BWB, "limit": 2, "offset": 5}]
    body = response.json()
    assert body["bwb_id"] == BWB
    assert body["total"] == 7  # absolute count, not len(items)
    assert len(body["items"]) == 2
    item = body["items"][0]
    assert item["id"] == "instruments/stb-2019-33"
    assert item["key"] == "stb-2019-33"
    assert item["identifier"] == "stb-2019-33"
    assert item["display_name"] == "Stb. 2019, 33"
    assert (item["kind"], item["year"], item["number"]) == ("Stb", 2019, "33")
    assert item["date_signed"] == "2019-01-01"
    assert item["date_published"] == "2019-01-02"
    assert item["dossiers"] == [
        {
            "number": "35786",
            "key": "35786",
            "title": "Klimaatwet",
            "short_title": None,
            "exists": True,
            "path": "/dossiers/35786",
            "id": "dossiers/35786",
        }
    ]
    assert (item["amends"], item["introduces"], item["repeals"]) == (2, 1, 0)
    assert item["articles_affected"] == 3
    assert item["first_effective_date"] == "2019-07-01"
    assert body["items"][1]["repeals"] == 4


def test_amended_by_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _amended_by(monkeypatch, AmendedByData(items=[], total=0, dossier_titles={}))

    response = client.get(f"/api/instruments/{BWB}/amended-by")

    assert_status(response, 200)
    assert response.json() == {
        "bwb_id": BWB,
        "total": 0,
        "items": [],
        "proposals_total": 0,
        "proposals": [],
    }


def test_amended_by_rejects_bad_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _amended_by(
        monkeypatch, AmendedByData(items=[], total=0, dossier_titles={})
    )
    assert_status(client.get(f"/api/instruments/{BWB}/amended-by?limit=0"), 422)
    assert_status(client.get(f"/api/instruments/{BWB}/amended-by?offset=-1"), 422)
    assert asked == []


# ── GET /api/instruments/{bwb_id}/dossiers (LEGISLATED_IN) ──────────────────


def _dossier(number: str, opened: str) -> dict[str, Any]:
    return {
        "id": f"dossiers/{number}",
        "key": number,
        "props": {
            "number": number,
            "label": number,
            "title": f"Dossier {number}",
            "opened_on": opened,
        },
    }


def _instrument_dossiers(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]], total: int
) -> list[tuple[str, int]]:
    """Stand in for ``get_instrument_dossiers``; returns the calls it got."""
    asked: list[tuple[str, int]] = []

    def get_instrument_dossiers(
        store: Any, identifier: str, *, limit: int, sort: str
    ) -> tuple[list[dict[str, Any]], int]:
        asked.append((identifier, limit))
        return rows, total

    stub_route(
        monkeypatch, "instruments", get_instrument_dossiers=get_instrument_dossiers
    )
    return asked


def test_instrument_dossiers_report_how_they_are_linked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _instrument_dossiers(
        monkeypatch,
        [
            {
                "dossier": _dossier("111", "2020-01-01"),
                "via": "instrument",
                "publication": None,
            },
            {
                "dossier": _dossier("222", "2019-01-01"),
                "via": "amending_publication",
                "publication": "stb-2019-33",
            },
        ],
        total=3,
    )

    response = client.get(f"/api/instruments/{BWB}/dossiers")

    assert_status(response, 200)
    assert [identifier for identifier, _ in asked] == [BWB]
    body = response.json()
    assert body["total"] == 3  # absolute count, not len(items)
    by_number = {i["dossier_number"]: i for i in body["items"]}
    assert by_number["111"]["via"] == "instrument"
    assert by_number["111"]["publication"] is None
    assert by_number["222"]["via"] == "amending_publication"
    assert by_number["222"]["publication"] == "stb-2019-33"
    assert by_number["111"]["id"] == "dossiers/111"
    assert by_number["111"]["title"] == "Dossier 111"
    assert by_number["111"]["opened_on"] == "2020-01-01"


def test_instrument_dossiers_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _instrument_dossiers(monkeypatch, [], total=0)

    body = client.get(f"/api/instruments/{BWB}/dossiers").json()

    assert body == {"bwb_id": BWB, "total": 0, "items": []}


def test_an_instrument_dossier_and_a_history_entry_name_the_dossier_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each dossier of a law, and the dossier of each change of an article, has the name it
    goes by (``short_title``, ``dossier_short_title``): from its title, null without one."""
    named = _dossier("36764", "2025-01-01")
    named["props"]["title"] = "Regels over cyberbeveiliging (Cyberbeveiligingswet)"
    rows = [
        {"dossier": named, "via": "instrument", "publication": None},
        {
            "dossier": _dossier("111", "2020-01-01"),
            "via": "instrument",
            "publication": None,
        },
    ]
    _instrument_dossiers(monkeypatch, rows, total=2)
    entry = {
        "date": "2025-03-01", "kind": "Wetsvoorstel", "change": "introduces",
        "status": "voorgesteld", "summary": None, "document_id": "documents/b",
        "dossier_id": "dossiers/36764", "dossier_number": "36764",
    }  # fmt: skip
    stub_route(
        monkeypatch,
        "articles",
        get_article_legislative_history=[
            {**entry, "dossier_title": named["props"]["title"]},
            {**entry, "dossier_title": None},
        ],
    )

    items = client.get(f"/api/instruments/{BWB}/dossiers").json()["items"]
    history = client.get(f"/api/articles/{BWB}/287/legislative-history").json()

    assert [i["short_title"] for i in items] == ["Cyberbeveiligingswet", None]
    assert [e["dossier_short_title"] for e in history["entries"]] == [
        "Cyberbeveiligingswet",
        None,
    ]


# ── OpenAPI ─────────────────────────────────────────────────────────────────


def test_openapi_lists_new_endpoints():
    schema = app.openapi()
    assert "/api/articles/{bwb_id}/{article_number}/history" in schema["paths"]
    assert "/api/instruments/{bwb_id}/amended-by" in schema["paths"]
