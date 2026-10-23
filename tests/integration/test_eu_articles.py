"""EU articles from the CELLAR HTML through ``normalize eurlex`` to the API: heading, a clean
text and parts in the BWB format, for the Official Journal format and for the old one.

The fixtures are trimmed real acts: the Data Governance Act (32022R0868, Official Journal
format), the AVG (32016R0679, its title and first article) and Directive 95/46/EG
(31995L0046, the old format of flat paragraphs).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import RAW_KIND_EURLEX_CELEX, SOURCE_EURLEX
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.databases import Api, module_store
from tests.integration.seed import FIXTURES

ACTS = {
    "32022R0868": "eurlex_32022r0868.html",
    "32016R0679": "eurlex_32016r0679.html",
    "31995L0046": "eurlex_31995l0046.html",
    "51993PC0476": "eurlex_51993pc0476.html",
}


PROPOSAL_TITLE = (
    "Voorstel voor een VERORDENING (EG) VAN DE RAAD betreffende de statistieken van het "
    "goederenverkeer van de Gemeenschap en haar Lid-Staten met derde landen"
)

# The tests read one database built for them all (``store``), on the worker that built it.
pytestmark = pytest.mark.xdist_group("eu_articles")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests here, on a database of its own: they only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        with RawSourceWriter(store) as writer:
            for celex, fixture in ACTS.items():
                writer.add(
                    raw_source_doc(
                        source=SOURCE_EURLEX,
                        kind=RAW_KIND_EURLEX_CELEX,
                        external_id=celex,
                        payload_text=(FIXTURES / fixture).read_text(),
                        meta={"celex": celex, "lang": "NL"},
                    )
                )
        cli("normalize", "eurlex")
        yield store


def _article(api: Api, celex: str, number: str) -> dict[str, Any]:
    article: dict[str, Any] = api.get_json(f"/api/articles/{celex}/{number}")["article"]
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
    api: Api,
) -> None:
    article = _article(api, "32022R0868", "1")

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


def test_a_point_inside_a_point_is_a_part_of_it(api: Api) -> None:
    article = _article(api, "32022R0868", "5")

    assert article["heading"] == "Voorwaarden voor hergebruik"
    ids = _ids(article)
    assert "lid-3-onder-a-onder-i" in ids and "lid-3-onder-a-onder-ii" in ids
    parts = {part["id"]: part for part in article["parts"]}
    assert parts["lid-3-onder-a-onder-i"]["text"] == (
        "geanonimiseerd zijn, in het geval van persoonsgegevens, en"
    )
    assert "\ni) geanonimiseerd zijn" in article["text"]


def test_an_article_of_the_old_format_has_its_heading_leden_and_points(
    api: Api,
) -> None:
    first = _article(api, "31995L0046", "1")
    assert first["heading"] == "Onderwerp van de richtlijn"
    assert _ids(first) == ["lid-1", "lid-2"]
    assert first["text"].startswith("1. De Lid-Staten waarborgen")

    definitions = _article(api, "31995L0046", "2")
    assert definitions["heading"] == "Definities"
    assert _ids(definitions) == ["aanhef"] + [f"onder-{c}" for c in "abcdefgh"]
    assert definitions["parts"][0]["text"] == (
        "In de zin van deze richtlijn wordt verstaan onder:"
    )

    scope = _article(api, "31995L0046", "3")
    assert _ids(scope) == [
        "lid-1",
        "lid-2",
        "lid-2-aanhef",
        "lid-2-onder-_1",
        "lid-2-onder-_2",
    ]

    # A division heading after the last article of a chapter is not part of that article.
    law = _article(api, "31995L0046", "4")
    assert "HOOFDSTUK" not in law["text"]
    assert _ids(law)[-1] == "lid-2"


def test_the_closing_formula_is_not_part_of_the_last_article(
    api: Api,
) -> None:
    last = _article(api, "31995L0046", "34")
    assert last["heading"] is None
    assert last["text"] == "Deze richtlijn is gericht tot de Lid-Staten."
    assert last["parts"] == []


def _articles(api: Api, celex: str, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = api.get_json(
        f"/api/instruments/{celex}/articles", **params
    )["items"]
    return items


def test_the_articles_of_an_eu_act_are_listed_in_document_order(
    api: Api,
) -> None:
    numbers = [a["article_number"] for a in _articles(api, "32022R0868")]
    assert numbers == ["1", "3", "5", "10"]

    first = _articles(api, "32022R0868", limit=3)
    assert [a["article_number"] for a in first] == ["1", "3", "5"]
    rest = _articles(api, "32022R0868", limit=3, offset=3)
    assert [a["article_number"] for a in rest] == ["10"]


def test_an_article_of_the_official_journal_has_its_breadcrumb(
    api: Api,
) -> None:
    crumbs = {
        a["article_number"]: a["breadcrumb"] for a in _articles(api, "32022R0868")
    }
    assert crumbs["1"] == [
        {
            "type": "hoofdstuk",
            "label": "Hoofdstuk I",
            "title": "Algemene bepalingen",
            "anchor": "deel-hoofdstuk-i",
        }
    ]
    assert [c["label"] for c in crumbs["5"]] == ["Hoofdstuk II"]
    assert crumbs["10"] == [
        {
            "type": "hoofdstuk",
            "label": "Hoofdstuk III",
            "title": "Vereisten voor aanbieders van databemiddelingsdiensten",
            "anchor": "deel-hoofdstuk-iii",
        }
    ]


def test_an_article_of_the_old_format_has_its_breadcrumb(api: Api) -> None:
    crumbs = {
        a["article_number"]: a["breadcrumb"] for a in _articles(api, "31995L0046")
    }
    chapter_1 = {
        "type": "hoofdstuk",
        "label": "Hoofdstuk I",
        "title": "ALGEMENE BEPALINGEN",
        "anchor": "deel-hoofdstuk-i",
    }
    assert crumbs["1"] == crumbs["4"] == [chapter_1]
    assert [c["label"] for c in crumbs["5"]] == ["Hoofdstuk II"]
    assert crumbs["6"][1:] == [
        {
            "type": "afdeling",
            "label": "Afdeling I",
            "title": "BEGINSELEN BETREFFENDE DE KWALITEIT VAN DE GEGEVENS",
            "anchor": "deel-hoofdstuk-ii-afdeling-i",
        }
    ]
    # A heading without a number stands at the top: it ends the chapter before it.
    assert crumbs["34"] == [
        {
            "type": "hoofdstuk",
            "label": None,
            "title": "SLOTBEPALINGEN",
            "anchor": "deel-slotbepalingen",
        }
    ]
    assert "SLOTBEPALINGEN" not in _article(api, "31995L0046", "6")["text"]


def test_the_reference_of_a_proposal_is_no_part_of_its_title(api: Api) -> None:
    proposal = api.get_json("/api/instruments/51993PC0476")
    title = PROPOSAL_TITLE
    assert (proposal["title"], proposal["display_name"]) == (title, title)


def test_an_eu_act_has_its_official_names(api: Api) -> None:
    body = api.get_json("/api/articles/32022R0868/1")
    instrument = body["instrument"]
    assert instrument["celex"] == "32022R0868"
    assert instrument["citation_title"] == "Verordening (EU) 2022/868"
    assert instrument["display_name"] == "Verordening (EU) 2022/868"
    assert instrument["short_title"] == "Datagovernanceverordening"
    assert instrument["title"] == (
        "Verordening (EU) 2022/868 van het Europees Parlement en de Raad van 30 mei "
        "2022 betreffende Europese datagovernance en tot wijziging van Verordening "
        "(EU) 2018/1724 (Datagovernanceverordening)"
    )
    assert body["article"]["display_name"] == "Art. 1 Verordening (EU) 2022/868"

    directive = api.get_json("/api/instruments/31995L0046")
    assert directive["citation_title"] == "Richtlijn 95/46/EG"
    assert directive["display_name"] == "Richtlijn 95/46/EG"
    assert directive["short_title"] is None
    assert directive["title"] == (
        "Richtlijn 95/46/EG van het Europees Parlement en de Raad van 24 oktober 1995 "
        "betreffende de bescherming van natuurlijke personen in verband met de "
        "verwerking van persoonsgegevens en betreffende het vrije verkeer van die "
        "gegevens"
    )
    assert _article(api, "31995L0046", "1")["display_name"] == (
        "Art. 1 Richtlijn 95/46/EG"
    )


def test_the_instrument_of_an_article_has_the_day_the_act_was_signed(api: Api) -> None:
    article = api.get_json("/api/articles/32016R0679/1")
    assert article["instrument"]["signed_on"] == "2016-04-27"

    directive = api.get_json("/api/instruments/31995L0046")
    assert directive["date_signed"] == "1995-10-24"


def test_the_list_of_eu_acts_names_every_act(api: Api) -> None:
    names = {
        item["celex"]: (item["display_name"], item["citation_title"])
        for item in api.get_json("/api/instruments", jurisdiction="eu")["items"]
    }
    assert names == {
        "32022R0868": ("Verordening (EU) 2022/868", "Verordening (EU) 2022/868"),
        "32016R0679": ("Verordening (EU) 2016/679", "Verordening (EU) 2016/679"),
        "31995L0046": ("Richtlijn 95/46/EG", "Richtlijn 95/46/EG"),
        # a proposal has no citation title: the printed one, without the reference
        "51993PC0476": (PROPOSAL_TITLE, PROPOSAL_TITLE),
    }
