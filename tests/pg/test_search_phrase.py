"""A phrase in quotes and the order of the words (test of 30 Oct 2026, "Hoe worden de Te
Beschermen Belangen van de Staat bepaald?"): a quoted phrase is found where its words stand
in that order, stop words and all; an article that holds the words of the query in that
order ranks above one that holds them scattered, however often the other is cited."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import _bm25
from lawgraph.db.queries.search.ranking import SCORE_CONTAINS, SCORE_WORDS
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
BARD_91A = "articles/bwbr0006040_91a"
MAW_12E = "articles/bwbr0001952_12e"


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
                "veiligheidsonderzoeken als bedoeld in de Wet veiligheidsonderzoeken; c. "
                "het bevorderen van maatregelen ter bescherming van de onder a genoemde "
                "belangen, waaronder begrepen maatregelen ter beveiliging van gegevens "
                "waarvan de geheimhouding door de nationale veiligheid wordt geboden en "
                "van die onderdelen van de overheidsdienst en van het bedrijfsleven die "
                "naar het oordeel van Onze ter zake verantwoordelijke Ministers van "
                "vitaal belang zijn voor de instandhouding van het maatschappelijk "
                "leven; d. het verrichten van onderzoek betreffende andere landen; e. "
                "het opstellen van dreigings- en risicoanalyses op verzoek van Onze "
                "Minister van Binnenlandse Zaken en Koninkrijksrelaties en Onze Minister "
                "van Veiligheid en Justitie gezamenlijk ten behoeve van de beveiliging "
                "van de personen, bedoeld in de artikelen 4, derde lid, onderdeel b, en "
                "42, eerste lid, onder c, van de Politiewet 2012 en de bewaking en de "
                "beveiliging van de objecten en de diensten die zijn aangewezen op grond "
                "van artikel 16 van die wet; f. het op een daartoe strekkend verzoek van "
                "een bij regeling van Onze betrokken Ministers gezamenlijk aangewezen "
                "persoon of instantie doen van mededeling omtrent door de dienst "
                "verwerkte gegevens omtrent personen of instanties in bij die regeling "
                "aangewezen gevallen.",
                cited=7,
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
            # the whole query in a row, in short articles that no judgment cites (or one)
            _article(
                "BWBR0006040",
                "91a",
                "BARD",
                "1. De ambtenaar die werkzaam is in een vertrouwensfunctie waarin hij "
                "toegang heeft tot zeer geheime of geheime gegevens waarvan de "
                "kennisneming door niet-gerechtigden zeer ernstige of ernstige schade "
                "aan de veiligheid of andere gewichtige belangen van de staat kan "
                "veroorzaken, is verplicht van een, anders dan in de uitoefening van zijn "
                "functie, voorgenomen reis naar of verblijf in bij koninklijk besluit "
                "aangewezen landen, ten minste zes weken voor vertrek mededeling te doen "
                "aan de Directeur Militaire Inlichtingen- en Veiligheidsdienst. 2. Een "
                "ambtenaar die tijdens het verblijf in een land als bedoeld in het eerste "
                "lid betrokken is geweest bij een incident dat van belang kan zijn uit "
                "het oogpunt van veiligheid of andere gewichtige belangen van de staat, "
                "is verplicht daarvan onmiddellijk bij terugkomst melding te doen aan "
                "een daartoe aangewezen functionaris van de Militaire Inlichtingen- en "
                "Veiligheidsdienst.",
            ),
            _article(
                "BWBR0001952",
                "12e",
                "MAW",
                "Het is de militaire ambtenaar verboden te verblijven in landen waarin "
                "het verblijf een bijzonder risico voor de veiligheid of andere "
                "gewichtige belangen van de Staat of zijn bondgenoten kan opleveren.",
                cited=1,
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
    assert sorted(_found(api, '"andere gewichtige belangen van de staat"')) == sorted(
        [WIV_8, BARD_91A, MAW_12E]
    )
    assert sorted(_found(api, '"Te Beschermen Belangen"')) == [BVA_1, VIRBI_4]
    # by their stems, as every word is found: "belang" in "belangen van de Staat" too
    assert sorted(_found(api, '"belang van de Staat"')) == sorted(
        [SR_98, WIV_8, BVA_1, VIRBI_4, BARD_91A, MAW_12E]
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
    assert set(found) == {WIV_8, BARD_91A, MAW_12E, SV_225, MIFID_65}
    assert set(found[3:]) == {SV_225, MIFID_65}
    found = _found(api, "te beschermen belangen van de staat")
    assert found[:2] == [BVA_1, VIRBI_4]


@pytest.fixture()
def counted(graph: GraphStore) -> GraphStore:
    """The graph among articles that hold none of the words, or one (as on prod: "staat"
    and "belangen" common, "gewichtige" rare), with its statistics kept: lengths and
    frequencies weigh as they do in a search of the whole graph."""
    graph.bulk_insert_or_update_nodes(
        "articles",
        [
            _article(
                "BWBR0088888",
                str(n),
                "Wet ter vulling",
                "De minister stelt regels over de uitvoering van deze wet"
                + (" en de staat" if n % 3 == 0 else "")
                + (" in het belang van de burger" if n % 5 == 0 else "")
                + ".",
            )
            for n in range(1, 301)
        ],
    )
    _bm25.table_statistics(graph, "articles")
    return graph


def test_the_case_law_ranks_the_articles_that_say_what_the_query_says(
    counted: GraphStore, api: Api
) -> None:
    """Of the articles that hold the whole query in a row, the one the case law cites
    first, above shorter ones that hold it as well (art. 8 Wiv 2017, cited by seven
    judgments, above art. 12e MAW, one, and art. 91a BARD, none, the query twice); and
    every hit scores by its rank, the best the most."""
    q = "gewichtige belangen van de staat"
    _found(api, q)  # the frequencies of its words counted, for the next search
    answer = api.get_json("/api/search", q=q, types=["articles"], limit=8)
    hits = answer["results"]["articles"]
    assert [hit["id"] for hit in hits][:3] == [WIV_8, MAW_12E, BARD_91A]
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)
    assert [s for s in scores if not SCORE_WORDS <= s < SCORE_CONTAINS] == []
    assert scores[0] > scores[2] > scores[-1]
