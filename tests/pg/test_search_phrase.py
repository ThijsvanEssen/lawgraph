"""A phrase in quotes and the order of the words (test of 30 Oct 2026, "Hoe worden de Te
Beschermen Belangen van de Staat bepaald?"): a quoted phrase is found where its words stand
in that order, stop words and all; an article that holds the words of the query in that
order ranks above one that holds them scattered, however often the other is cited."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore, version_cache
from tests.databases import Api


def _article(
    bwb_id: str, number: str, law: str, text: str, cited: int = 0, **props: Any
) -> dict[str, Any]:
    return {
        "key": f"{bwb_id.lower()}_{number}",
        "type": "article",
        "labels": [],
        "props": {
            "bwb_id": bwb_id,
            "article_number": number,
            "display_name": f"Artikel {number} {law}",
            "text": text,
            "inbound_citation_count": cited,
            **props,
        },
    }


WIV_8 = "articles/bwbr0039896_8"
BVA_1 = "articles/bwbr0044617_1"
VIRBI_4 = "articles/bwbr0051482_4"
SR_98 = "articles/bwbr0001854_98"
SV_225 = "articles/bwbr0001903_225"
MIFID_65 = "articles/bwbr0099999_65"


@pytest.fixture()
def graph(store: GraphStore) -> GraphStore:
    version_cache.clear()
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _article(
                "BWBR0039896",
                "8",
                "Wet op de inlichtingen- en veiligheidsdiensten 2017",
                "1. Er is een Algemene Inlichtingen- en Veiligheidsdienst. 2. De "
                "Algemene Inlichtingen- en Veiligheidsdienst heeft in het belang van de "
                "nationale veiligheid tot taak: a. het verrichten van onderzoek met "
                "betrekking tot organisaties en personen die door de doelen die zij "
                "nastreven, dan wel door hun activiteiten aanleiding geven tot het "
                "ernstige vermoeden dat zij een gevaar vormen voor het voortbestaan van "
                "de democratische rechtsorde, dan wel voor de veiligheid of voor andere "
                "gewichtige belangen van de staat; b. het verrichten van "
                "veiligheidsonderzoeken; c. het bevorderen van maatregelen ter "
                "bescherming van de onder a genoemde belangen.",
                cited=3,
            ),
            _article(
                "BWBR0044617",
                "1",
                "Besluit BVA-stelsel Rijksdienst 2021",
                "In dit besluit en de daarop berustende bepalingen wordt verstaan onder: "
                "a. Onze Minister: Onze Minister van Binnenlandse Zaken; k. Te "
                "Beschermen Belangen van de Staat: belangen van de Staat die vanwege "
                "hun aard bijzondere bescherming behoeven.",
                heading="Begripsbepalingen",
            ),
            _article(
                "BWBR0051482",
                "4",
                "Voorschrift Informatiebeveiliging Rijksdienst Bijzondere Informatie 2025",
                "Bijzondere informatie wordt gerubriceerd naar de schade die kennisname "
                "door niet geautoriseerden kan toebrengen aan de te beschermen belangen "
                "van de Staat of zijn bondgenoten.",
            ),
            _article(
                "BWBR0001854",
                "98",
                "Wetboek van Strafrecht",
                "1. Hij die inlichtingen betreffende een aangelegenheid waarvan de "
                "geheimhouding door het belang van de Staat of van zijn bondgenoten "
                "wordt geboden, opzettelijk aan een buitenlandse mogendheid verstrekt, "
                "wordt gestraft met gevangenisstraf van ten hoogste zes jaren.",
                cited=43,
            ),
            # the words of the query, scattered, and cited far more
            _article(
                "BWBR0001903",
                "225",
                "Wetboek van Strafvordering",
                "Indien gewichtige redenen dit vorderen, kan de staat van het onderzoek "
                "worden aangehouden; de belangen van de verdachte worden daarbij "
                "gewogen.",
                cited=900,
            ),
            _article(
                "BWBR0099999",
                "65",
                "Gedelegeerde Verordening (EU) 2017/565",
                "Belangen van cliënten wegen gewichtige zwaarder; de lidstaat van "
                "herkomst en de staat van ontvangst houden toezicht.",
                cited=400,
            ),
        ],
    )
    return store


def _found(api: Api, q: str) -> list[str]:
    answer = api.get_json("/api/search", q=q, types=["articles"], limit=8)
    return [hit["id"] for hit in answer["results"]["articles"]]


def test_a_quoted_phrase_finds_the_articles_that_hold_it(
    graph: GraphStore, api: Api
) -> None:
    """The words in quotes in that order, stop words and capitals as they come: not one
    of the articles that hold them scattered."""
    assert _found(api, '"andere gewichtige belangen van de staat"') == [WIV_8]
    assert sorted(_found(api, '"Te Beschermen Belangen"')) == [BVA_1, VIRBI_4]
    # by their stems, as every word is found: "belang" in "belangen van de Staat" too
    assert sorted(_found(api, '"belang van de Staat"')) == sorted(
        [SR_98, WIV_8, BVA_1, VIRBI_4]
    )
    # a phrase and a word beside it: both hold
    assert _found(api, '"te beschermen belangen" bondgenoten') == [VIRBI_4]
    # a phrase no article holds in that order
    assert _found(api, '"staat van de belangen"') == []


def test_the_stop_words_of_a_phrase_are_kept(graph: GraphStore, api: Api) -> None:
    answer = api.get_json(
        "/api/search", q='"belangen van de staat"', types=["articles"]
    )
    assert answer["left_out"] == []


def test_the_words_in_their_order_rank_first(graph: GraphStore, api: Api) -> None:
    """Without quotes every article with the words is a hit, the one that holds them in
    the order of the query first, above the articles cited far more that hold them
    scattered."""
    found = _found(api, "gewichtige belangen van de staat")
    assert found[0] == WIV_8
    assert set(found) == {WIV_8, SV_225, MIFID_65}
    found = _found(api, "te beschermen belangen van de staat")
    assert found[:2] == [BVA_1, VIRBI_4]
