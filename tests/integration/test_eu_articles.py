"""EU articles from the CELLAR HTML through ``normalize eurlex`` to the API: heading, a clean
text and parts in the BWB format, for the Official Journal format and for the old one.

The fixtures are trimmed real acts: the Data Governance Act (32022R0868, Official Journal
format) and Directive 95/46/EG (31995L0046, the old format of flat paragraphs).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_EU_CELEX, SOURCE_EURLEX
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import FIXTURES

ACTS = {
    "32022R0868": "eurlex_32022r0868.html",
    "31995L0046": "eurlex_31995l0046.html",
}


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        for celex, fixture in ACTS.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_EURLEX,
                    kind=RAW_KIND_EU_CELEX,
                    external_id=celex,
                    payload_text=(FIXTURES / fixture).read_text(),
                    meta={"celex": celex, "lang": "NL"},
                )
            )
    cli("normalize", "eurlex")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _article(client: TestClient, celex: str, number: str) -> dict[str, Any]:
    response = client.get(f"/api/articles/{celex}/{number}")
    assert response.status_code == 200, response.text
    article: dict[str, Any] = response.json()["article"]
    text = article["text"]
    # A clean text: no empty or whitespace-only line, no heading in it.
    assert all(line.strip() for line in text.split("\n")), text
    assert not text.startswith(article["heading"] or "\0")
    for part in article["parts"]:
        assert text[part["start"] : part["end"]] == part["text"]
    return article


def _ids(article: dict[str, Any]) -> list[str]:
    return [part["id"] for part in article["parts"]]


def test_an_article_of_the_official_journal_has_its_heading_leden_and_points(
    client: TestClient,
) -> None:
    article = _article(client, "32022R0868", "1")

    assert article["heading"] == "Onderwerp en toepassingsgebied"
    assert _ids(article) == [
        "lid-1",
        "lid-1-aanhef",
        "lid-1-onder-a",
        "lid-1-onder-b",
        "lid-1-onder-c",
        "lid-1-onder-d",
        "lid-2",
        "lid-2-aanhef",
        "lid-2-onder-a",
        "lid-2-onder-b",
        "lid-3",
        "lid-4",
        "lid-5",
    ]
    parts = {part["id"]: part for part in article["parts"]}
    assert parts["lid-1-aanhef"]["text"] == "Deze verordening bevat:"
    assert parts["lid-1-onder-a"]["number"] == "a"
    assert parts["lid-1-onder-d"]["text"] == (
        "een kader voor de oprichting van een Europees Comité voor gegevensinnovatie."
    )
    assert parts["lid-2-aanhef"]["text"].endswith(
        "\nDeze verordening doet geen afbreuk aan:"
    )
    assert parts["lid-4"]["text"] == (
        "Deze verordening doet geen afbreuk aan de toepassing van het mededingingsrecht."
    )
    # The marker stands on the line of its point, the number of a lid before its text.
    assert "\na) voorwaarden voor het hergebruik" in article["text"]
    assert article["text"].startswith("1. Deze verordening bevat:\na) ")


def test_a_point_inside_a_point_is_a_part_of_it(client: TestClient) -> None:
    article = _article(client, "32022R0868", "5")

    assert article["heading"] == "Voorwaarden voor hergebruik"
    ids = _ids(article)
    assert "lid-3-onder-a-onder-i" in ids and "lid-3-onder-a-onder-ii" in ids
    parts = {part["id"]: part for part in article["parts"]}
    assert parts["lid-3-onder-a-onder-i"]["text"] == (
        "geanonimiseerd zijn, in het geval van persoonsgegevens, en"
    )
    assert "\ni) geanonimiseerd zijn" in article["text"]


def test_an_article_of_the_old_format_has_its_heading_leden_and_points(
    client: TestClient,
) -> None:
    first = _article(client, "31995L0046", "1")
    assert first["heading"] == "Onderwerp van de richtlijn"
    assert _ids(first) == ["lid-1", "lid-2"]
    assert first["text"].startswith("1. De Lid-Staten waarborgen")

    definitions = _article(client, "31995L0046", "2")
    assert definitions["heading"] == "Definities"
    assert _ids(definitions) == ["aanhef"] + [f"onder-{c}" for c in "abcdefgh"]
    assert definitions["parts"][0]["text"] == (
        "In de zin van deze richtlijn wordt verstaan onder:"
    )

    scope = _article(client, "31995L0046", "3")
    assert _ids(scope) == [
        "lid-1",
        "lid-2",
        "lid-2-aanhef",
        "lid-2-onder-_1",
        "lid-2-onder-_2",
    ]

    # A division heading after the last article of a chapter is not part of that article.
    law = _article(client, "31995L0046", "4")
    assert "HOOFDSTUK" not in law["text"]
    assert _ids(law)[-1] == "lid-2"


def test_the_closing_formula_is_not_part_of_the_last_article(
    client: TestClient,
) -> None:
    last = _article(client, "31995L0046", "34")
    assert last["heading"] is None
    assert last["text"] == "Deze richtlijn is gericht tot de Lid-Staten."
    assert last["parts"] == []
