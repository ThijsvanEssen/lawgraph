"""The questions of the search test of 21 October (E4, onderzoek/E4-search-ux.md) that found
nothing or the wrong thing, run for real on the small test server:

* Enter opened a "Beste treffer" whatever its words: ``best`` is only what the query names
  exactly ("Awb", "LJN AU3313"), never an article whose heading is the word
  ("huurverhoging": Art. IX of a Reparatiewet);
* a question in a sentence and two words found nothing: the stop words are left out
  ("wat is de opzegtermijn van mijn huurcontract"), "toezeggingen" names the type, and
  without a hit of every word the hits of one say so (``matched``);
* "Rutte" found the Besluit archief Rutten before the member;
* an LJN was not read as the judgment it numbers;
* a term ("wanprestatie", "GDPR", "minimum wage") found the words, not the article or law it
  is about: the curated list of concepts names it (``core.concepts``).
"""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.commands.curated import concept_notes
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_COMMITMENTS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
)
from lawgraph.core import concepts
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.search import dispatch
from lawgraph.db.queries.search.ranking import SCORE_CONTAINS, SCORE_TITLE
from tests.databases import Api

AWB, BW6, BW7, REPAIR = "BWBR0005537", "BWBR0005289", "BWBR0005290", "BWBR0035000"
RSKR, WML, AVG = "BWBR0036000", "BWBR0002638", "32016R0679"
LJN_ECLI = "ECLI:NL:HR:2005:AU3313"


def _put(store: GraphStore, collection: str, key: str, **props: Any) -> None:
    doc = {"key": key, "type": collection.rstrip("s"), "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


@pytest.fixture()
def store(store: GraphStore, monkeypatch: pytest.MonkeyPatch) -> GraphStore:
    # a budget no type of the small graph runs past, however busy the server
    monkeypatch.setattr(dispatch, "LIVE_BUDGET", 30.0)
    version_cache.clear()
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        make_node_key(AWB),
        bwb_id=AWB,
        title="Algemene wet bestuursrecht",
        citation_title="Algemene wet bestuursrecht",
        short_title="Awb",
        aliases=["Awb"],
    )
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        "bwbr0040000",
        bwb_id="BWBR0040000",
        title="Besluit archief Rutten",
        citation_title="Besluit archief Rutten",
    )
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(REPAIR, "IX"),
        bwb_id=REPAIR,
        article_number="IX",
        heading="Huurverhoging",
        display_name="Artikel IX Reparatiewet BZK 2014",
        text="In artikel 10 van de Uitvoeringswet huurprijzen woonruimte vervalt het derde lid.",
    )
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(BW7, "271"),
        bwb_id=BW7,
        article_number="271",
        display_name="Artikel 271 Burgerlijk Wetboek Boek 7",
        text="Bij opzegging van een huurcontract geldt een opzegtermijn van ten minste "
        "een maand.",
    )
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(BW6, "74"),
        bwb_id=BW6,
        article_number="74",
        display_name="Artikel 74 Burgerlijk Wetboek Boek 6",
        text="Iedere tekortkoming in de nakoming van een verbintenis verplicht de "
        "schuldenaar de schade die de schuldeiser daardoor lijdt te vergoeden.",
    )
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(RSKR, "4:5"),
        bwb_id=RSKR,
        article_number="4:5",
        heading="Wanprestatie",
        display_name="Artikel 4:5 Rskr",
        text="Bij wanprestatie van de subsidieontvanger kan de subsidie worden verlaagd.",
    )
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(BW7, "248"),
        bwb_id=BW7,
        article_number="248",
        display_name="Artikel 248 Burgerlijk Wetboek Boek 7",
        text="De verhuurder kan tot aan het tijdstip waarop de huurprijs door de rechter "
        "is vastgesteld, jaarlijks een voorstel doen tot verhoging van de huurprijs.",
    )
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(WML, "7"),
        bwb_id=WML,
        article_number="7",
        display_name="Artikel 7 Wet minimumloon en minimumvakantiebijslag",
        text="De werknemer heeft aanspraak op ten minste het minimumloon.",
    )
    _put(
        store,
        COLLECTION_ARTICLES,
        "stuwage_6",
        bwb_id="BWBR0039000",
        article_number="6",
        display_name="Artikel 6 Besluit stuwage",
        text="Stuwage van ten minimum wage cargo.",
    )
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        make_node_key(AVG),
        celex=AVG,
        title="Verordening (EU) 2016/679 (algemene verordening gegevensbescherming)",
        citation_title="Verordening (EU) 2016/679",
    )
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        "bwbr0045000",
        bwb_id="BWBR0045000",
        title="NL accreditation requirements for GDPR code of conduct monitoring bodies",
        citation_title="NL accreditation requirements for GDPR code of conduct monitoring "
        "bodies",
    )
    _put(
        store,
        COLLECTION_MEMBERS,
        "mark_rutte",
        name="Mark Rutte",
        party="VVD",
        slug="mark-rutte",
    )
    _put(
        store,
        COLLECTION_JUDGMENTS,
        make_node_key(LJN_ECLI),
        ecli=LJN_ECLI,
        display_name="Hoge Raad 2005-11-11 / C04/327HR",
        summary="Aansprakelijkheid van de werkgever.",
    )
    _put(
        store,
        COLLECTION_COMMITMENTS,
        "tz_1",
        number="TZ202601-001",
        made_on="2026-01-10",
        text="De minister komt in de startbrief terug op het nabestaandenpensioen.",
        display_name="De minister komt in de startbrief terug op het nabestaandenpensioen.",
    )
    return store


def _search(api: Api, q: str, **params: Any) -> dict[str, Any]:
    answer: dict[str, Any] = api.get_json("/api/search", q=q, **params)
    return answer


def _keys(answer: dict[str, Any], kind: str) -> list[str]:
    return [h["key"] for h in answer["results"].get(kind, [])]


@pytest.mark.parametrize("mode", ["full", "live"])
def test_best_is_only_what_the_query_names_exactly(
    store: GraphStore, api: Api, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "huurverhoging" is the heading of Art. IX of a Reparatiewet, no hit it names: no
    ``best`` (without the list of concepts, which names art. 7:248 BW by it). "Awb" is the
    abbreviation of the Awb, "LJN AU3313" the number of the ECLI of a judgment
    (``ECLI:NL:HR:2005:AU3313``): each the ``best`` and ``exact``."""
    monkeypatch.setattr(concepts, "concepts", dict)
    words = _search(api, "huurverhoging", mode=mode, resolve="true")
    # art. 7:248 BW, whose words do not hold it, is no hit
    assert _keys(words, "articles") == [make_node_key(REPAIR, "IX")]
    assert words["best"] is None
    exact = [h["key"] for hits in words["results"].values() for h in hits if h["exact"]]
    assert exact == []

    awb = _search(api, "Awb", mode=mode, types="instruments")
    assert awb["best"] == f"instruments/{make_node_key(AWB)}"

    for q in ("LJN AU3313", "au3313"):
        ljn = _search(api, q, mode=mode, resolve="true")
        judgment = f"judgments/{make_node_key(LJN_ECLI)}"
        assert ljn["best"] == judgment, q
        assert ljn["resolved"]["match"]["id"] == judgment, q
        assert [h["exact"] for h in ljn["results"]["judgments"]] == [True], q


def test_two_letters_and_four_digits_of_no_judgment_are_words(
    store: GraphStore, api: Api
) -> None:
    answer = _search(api, "IB2001", resolve="true")
    assert answer["resolved"]["notation"] is None
    assert answer["best"] is None


@pytest.mark.parametrize("mode", ["full", "live"])
def test_a_question_in_a_sentence_is_searched_by_its_words(
    store: GraphStore, api: Api, mode: str
) -> None:
    """The stop words of a sentence are left out: art. 7:271 BW holds "opzegtermijn" and
    "huurcontract", not "mijn"."""
    answer = _search(
        api, "wat is de opzegtermijn van mijn huurcontract", mode=mode, types="articles"
    )
    assert _keys(answer, "articles") == [make_node_key(BW7, "271")]
    assert answer["words"] == ["opzegtermijn", "huurcontract"]
    assert answer["left_out"] == ["wat", "is", "de", "van", "mijn"]
    assert answer["matched"] == "all"


def test_without_a_hit_of_every_word_the_hits_of_one_say_so(
    store: GraphStore, api: Api
) -> None:
    """No article holds "opzegtermijn" and "ontslagvergoeding": those with one of them,
    ``matched`` ``any``; while typing nothing yet. A citation is not searched by its
    parts."""
    q = "opzegtermijn ontslagvergoeding"
    answer = _search(api, q, types="articles")
    assert _keys(answer, "articles") == [make_node_key(BW7, "271")]
    assert answer["matched"] == "any"
    typing = _search(api, q, types="articles", mode="live")
    assert (typing["total"], typing["matched"]) == (0, "all")

    cited = _search(api, "Kamerstuk 35925 VI nr. 5", types="articles")
    assert (cited["total"], cited["matched"]) == (0, "all")


@pytest.mark.parametrize("mode", ["full", "live"])
def test_the_commitments_on_a_subject(store: GraphStore, api: Api, mode: str) -> None:
    """ "toezeggingen" names the type, "pensioenen" finds the nabestaandenpensioen by its
    stem."""
    answer = _search(api, "toezeggingen pensioenen", mode=mode, types="commitments")
    assert _keys(answer, "commitments") == ["tz_1"]
    assert answer["matched"] == "all"


@pytest.mark.parametrize("mode", ["full", "live"])
def test_a_surname_finds_the_member_before_a_title_that_holds_it(
    store: GraphStore, api: Api, mode: str
) -> None:
    answer = _search(api, "Rutte", mode=mode, types=["members", "instruments"])
    scores = {t: [h["score"] for h in hits] for t, hits in answer["results"].items()}
    assert scores == {"members": [SCORE_TITLE], "instruments": [SCORE_CONTAINS]}
    # two members may have the name: no hit it names exactly
    assert answer["best"] is None


# The questions of E4 a term answers: the query, the article or law the list names by it.
E4_CONCEPTS = [
    ("wanprestatie", f"articles/{make_node_key(BW6, '74')}"),  # 23: Art. 4:5 Rskr
    (
        "huurverhoging",
        f"articles/{make_node_key(BW7, '248')}",
    ),  # 2: Art. IX Reparatiewet
    ("GDPR", f"instruments/{make_node_key(AVG)}"),  # 20: a title that holds GDPR
    ("minimum wage", f"articles/{make_node_key(WML, '7')}"),  # 21: Besluit stuwage
    # 30: its words without the stop words
    (
        "wat is de opzegtermijn van mijn huurcontract",
        f"articles/{make_node_key(BW7, '271')}",
    ),
]


@pytest.mark.parametrize("mode", ["full", "live"])
@pytest.mark.parametrize(("q", "named"), E4_CONCEPTS)
def test_a_term_opens_the_article_or_law_the_list_names_by_it(
    store: GraphStore,
    api: Api,
    mode: str,
    q: str,
    named: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before the list (none): no ``best``, or the wrong one. With it: the article or law
    first among the hits of its type, ``exact``, ``concept`` its term, and ``best``."""
    collection = named.split("/")[0]
    with monkeypatch.context() as before:
        before.setattr(concepts, "concepts", dict)
        answer = _search(api, q, mode=mode, resolve="true")
        assert answer["best"] != named
        by_concept = [
            h["id"] for hits in answer["results"].values() for h in hits if h["concept"]
        ]
        assert by_concept == []

    answer = _search(api, q, mode=mode, resolve="true")
    assert answer["best"] == named
    first = answer["results"][collection][0]
    assert (first["id"], first["exact"], first["score"]) == (named, True, 1.0)
    assert first["concept"] in {
        "wanprestatie",
        "huurverhoging",
        "gdpr",
        "minimumloon",
        "opzegtermijn huur",
    }
    assert [h["id"] for h in answer["results"][collection]].count(named) == 1


def test_a_term_is_no_hit_of_a_type_not_searched_or_within_a_period(
    store: GraphStore, api: Api
) -> None:
    other = _search(api, "wanprestatie", types="instruments")
    assert other["best"] is None
    dated = _search(api, "wanprestatie", types="articles", **{"from": "2020-01-01"})
    assert dated["best"] is None


def test_the_check_names_a_concept_whose_article_the_graph_lacks(
    store: GraphStore,
) -> None:
    found = concept_notes(store)
    lacking = [p for p in found if p.startswith("concepts: ontslag op staande voet: ")]
    assert len(lacking) == 1, found
    named = {
        "wanprestatie",
        "huurverhoging",
        "gdpr",
        "minimumloon",
        "opzegtermijn huur",
    }
    assert not [p for p in found if p.split(": ")[1] in named]
