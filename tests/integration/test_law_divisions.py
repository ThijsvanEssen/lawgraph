"""One division of a law alone: ``division`` on the articles of a law and on the law of a
day, after the real ``normalize bwb`` and ``normalize bwb-history``.

- The Awb: Afdeling 10.2.2 stands in Titel 10.2 of Hoofdstuk 10. Article 10:35 comes into
  it in 2025, and 10:32 moves into it from Afdeling 10.2.1 under the same version.
- BW Boek 7: Afdeling 2 of Titel 10, under the book itself (``Boek 7``).
- A law without divisions: no division to cut it to.
"""

from __future__ import annotations

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
from tests.asserts import assert_status

AWB = "BWBR0005537"
BW7 = "BWBR0005290"
FLAT = "BWBR0099002"

# A division: (element, label word, number, title, the divisions or articles in it). An
# article is its number.
Tree = list[Any]


def _div(element: str, word: str, nr: str, title: str, inside: Tree) -> tuple:
    return (element, word, nr, title, inside)


# The articles that came into force with the toestand of 2025; the others are older.
LATE = {"10:35": "2025-01-01"}


def _article(number: str) -> str:
    stam = "".join(c for c in number if c.isdigit())
    inwerking = LATE.get(number, "1994-01-01")
    return (
        f'<artikel stam-id="{stam}" versie-id="{stam}1" inwerking="{inwerking}">'
        f"<kop><label>Artikel</label><nr>{number}</nr></kop>"
        f"<al>De tekst van artikel {number}.</al></artikel>"
    )


def _xml(inside: Tree) -> str:
    out = []
    for item in inside:
        if isinstance(item, str):
            out.append(_article(item))
            continue
        element, word, nr, title, nested = item
        out.append(
            f"<{element}><kop><label>{word}</label><nr>{nr}</nr>"
            f"<titel>{title}</titel></kop>{_xml(nested)}</{element}>"
        )
    return "".join(out)


def _toestand(law: str, start: str, inside: Tree) -> str:
    return (
        f'<toestand bwb-id="{law}" inwerkingtreding="{start}">'
        f'<wetgeving soort="wet"><intitule>{law}</intitule><citeertitel>{law}</citeertitel>'
        f"<wet-besluit><wettekst>{_xml(inside)}</wettekst></wet-besluit></wetgeving>"
        "</toestand>"
    )


def _awb(late: bool) -> Tree:
    """Hoofdstuk 10 of the Awb; *late*: as from 2025."""
    first = ["10:25", "10:32"] if not late else ["10:25"]
    second = ["10:32", "10:33", "10:34", "10:35"] if late else ["10:33", "10:34"]
    return [
        _div("hoofdstuk", "Hoofdstuk", "1", "Inleidende bepalingen", ["1:1", "1:2"]),
        _div(
            "hoofdstuk",
            "Hoofdstuk",
            "10",
            "Bepalingen over bestuursorganen",
            [
                _div("titeldeel", "Titel", "10.1", "Mandaat", ["10:1"]),
                _div(
                    "titeldeel",
                    "Titel",
                    "10.2",
                    "Toezicht op bestuursorganen",
                    [
                        _div("afdeling", "Afdeling", "10.2.1", "Goedkeuring", first),
                        _div("afdeling", "Afdeling", "10.2.2", "Vernietiging", second),
                    ],
                ),
            ],
        ),
    ]


BW7_TREE: Tree = [
    _div(
        "boek",
        "Boek",
        "7",
        "Bijzondere overeenkomsten",
        [
            _div("titeldeel", "Titel", "1", "Koop", ["7:1", "7:2"]),
            _div(
                "titeldeel",
                "Titel",
                "10",
                "De arbeidsovereenkomst",
                [
                    _div("afdeling", "Afdeling", "1", "Algemene bepalingen", ["7:610"]),
                    _div(
                        "afdeling",
                        "Afdeling",
                        "2",
                        "Loon",
                        ["7:616", "7:617", "7:618"],
                    ),
                ],
            ),
        ],
    )
]


def _raw(law: str, kind: str, start: str, end: str | None, xml: str) -> Any:
    external = law if kind == RAW_KIND_BWB_TOESTAND else f"{law}@{start}"
    return raw_source_doc(
        source=SOURCE_BWB,
        kind=kind,
        external_id=external,
        payload_text=xml,
        meta={
            "bwb_id": law,
            "state_url": f"https://repo/{law}/{start}.xml",
            "start_date": start,
            "end_date": end,
        },
    )


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = GraphStore()
    awb_old = _toestand(AWB, "2018-01-01", _awb(False))
    awb_new = _toestand(AWB, "2025-01-01", _awb(True))
    bw7 = _toestand(BW7, "2020-01-01", BW7_TREE)
    flat = _toestand(FLAT, "2020-01-01", ["1", "2"])
    with RawSourceWriter(store) as writer:
        writer.add(_raw(AWB, RAW_KIND_BWB_TOESTAND, "2025-01-01", None, awb_new))
        writer.add(
            _raw(AWB, RAW_KIND_BWB_TOESTAND_ALL, "2018-01-01", "2024-12-31", awb_old)
        )
        writer.add(
            _raw(AWB, RAW_KIND_BWB_TOESTAND_ALL, "2025-01-01", "9999-12-31", awb_new)
        )
        for law, xml in ((BW7, bw7), (FLAT, flat)):
            writer.add(_raw(law, RAW_KIND_BWB_TOESTAND, "2020-01-01", None, xml))
            writer.add(
                _raw(law, RAW_KIND_BWB_TOESTAND_ALL, "2020-01-01", "9999-12-31", xml)
            )
    cli("normalize", "bwb")
    cli("normalize", "bwb-history")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, (path, response.text[:500])
    return response.json()


def _numbers(body: dict[str, Any]) -> list[str]:
    return [a["article_number"] for a in body["items"]]


AFDELING_10_2_2 = "deel-hoofdstuk-10-titel-10.2-afdeling-10.2.2"


def test_a_nested_division_alone_with_its_heading(client: TestClient) -> None:
    whole = _get(client, f"/api/instruments/{AWB}/articles")
    body = _get(client, f"/api/instruments/{AWB}/articles?division={AFDELING_10_2_2}")
    assert _numbers(body) == ["10:32", "10:33", "10:34", "10:35"]
    assert body["total"] == 4
    division = body["division"]
    assert (division["anchor"], division["type"], division["label"]) == (
        AFDELING_10_2_2,
        "afdeling",
        "Afdeling 10.2.2",
    )
    assert division["title"] == "Vernietiging"
    assert [c["label"] for c in division["breadcrumb"]] == [
        "Hoofdstuk 10",
        "Titel 10.2",
        "Afdeling 10.2.2",
    ]
    # its first article stands there in the whole law: read on from it
    assert _numbers(whole)[division["offset"]] == "10:32"
    # each article as the whole list gives it
    by_number = {a["article_number"]: a for a in whole["items"]}
    assert body["items"] == [by_number[n] for n in _numbers(body)]
    assert whole["division"] is None


def test_a_division_holds_the_divisions_inside_it(client: TestClient) -> None:
    body = _get(client, f"/api/instruments/{AWB}/articles?division=hoofdstuk-10")
    assert _numbers(body) == ["10:1", "10:25", "10:32", "10:33", "10:34", "10:35"]
    assert body["division"]["anchor"] == "deel-hoofdstuk-10"
    assert body["division"]["title"] == "Bepalingen over bestuursorganen"
    assert body["division"]["offset"] == 2


def test_a_division_pages_like_the_whole_list(client: TestClient) -> None:
    url = f"/api/instruments/{AWB}/articles?division=%23{AFDELING_10_2_2.upper()}"
    body = _get(client, f"{url}&limit=2&offset=1")
    assert (_numbers(body), body["total"]) == (["10:33", "10:34"], 4)
    past = _get(client, f"{url}&offset=9")
    assert (past["items"], past["total"]) == ([], 4)
    assert past["division"]["label"] == "Afdeling 10.2.2"


def test_a_division_of_the_law_of_a_day(client: TestClient) -> None:
    path = f"/api/instruments/{AWB}/articles/at"
    before = _get(client, f"{path}/2020-01-01?division={AFDELING_10_2_2}")
    after = _get(client, f"{path}/2025-06-01?division={AFDELING_10_2_2}")
    # 10:32 stood in Afdeling 10.2.1 then, and 10:35 was not yet in the law
    assert _numbers(before) == ["10:33", "10:34"]
    assert _numbers(after) == ["10:32", "10:33", "10:34", "10:35"]
    assert before["first_version_from"] == "2018-01-01"
    assert before["division"]["breadcrumb"][-1] == {
        "type": "afdeling",
        "label": "Afdeling 10.2.2",
        "title": "Vernietiging",
        "anchor": AFDELING_10_2_2,
    }
    day = _get(client, f"{path}/2020-01-01")
    assert _numbers(day)[before["division"]["offset"]] == "10:33"
    assert before["items"] == [
        a for a in day["items"] if a["article_number"] in {"10:33", "10:34"}
    ]
    earlier = _get(client, f"{path}/2020-01-01?division=deel-hoofdstuk-10-titel-10.2")
    assert _numbers(earlier) == ["10:25", "10:32", "10:33", "10:34"]
    assert_status(client.get(f"{path}/2010-01-01?division={AFDELING_10_2_2}"), 404)


def test_a_division_under_the_book_of_the_bw(client: TestClient) -> None:
    anchor = "deel-boek-7-titel-10-afdeling-2"
    body = _get(client, f"/api/instruments/{BW7}/articles?division={anchor}")
    assert _numbers(body) == ["7:616", "7:617", "7:618"]
    assert [c["label"] for c in body["division"]["breadcrumb"]] == [
        "Boek 7",
        "Titel 10",
        "Afdeling 2",
    ]
    assert body["division"]["offset"] == 3
    on = _get(
        client, f"/api/instruments/{BW7}/articles/at/2024-01-01?division={anchor}"
    )
    assert _numbers(on) == ["7:616", "7:617", "7:618"]
    assert on["division"]["title"] == "Loon"


def test_a_law_without_divisions_has_none_to_cut_to(client: TestClient) -> None:
    whole = _get(client, f"/api/instruments/{FLAT}/articles")
    assert (_numbers(whole), whole["division"]) == (["1", "2"], None)
    for url in (
        f"/api/instruments/{FLAT}/articles?division=deel-hoofdstuk-1",
        f"/api/instruments/{FLAT}/articles/at/2024-01-01?division=deel-hoofdstuk-1",
        f"/api/instruments/{AWB}/articles?division=deel-hoofdstuk-99",
        "/api/instruments/BWBR9999999/articles?division=deel-hoofdstuk-1",
    ):
        response = client.get(url)
        assert response.status_code == 404, url
        division = url.rsplit("=", 1)[1]
        assert response.json()["detail"] == f"Division '{division}' not found."
