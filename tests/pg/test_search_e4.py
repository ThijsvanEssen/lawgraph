"""The questions of the search test of 21 October (E4, onderzoek/E4-search-ux.md) that found
nothing or the wrong thing, run for real on the small test server:

* Enter opened a "Beste treffer" whatever its words: ``best`` is only what the query names
  exactly ("Awb", "LJN AU3313"), never an article whose heading is the word
  ("huurverhoging": Art. IX of a Reparatiewet);
* a question in a sentence and two words found nothing: the stop words are left out
  ("wat is de opzegtermijn van mijn huurcontract"), "toezeggingen" names the type, and
  without a hit of every word the hits of one say so (``matched``);
* "Rutte" found the Besluit archief Rutten before the member;
* an LJN was not read as the judgment it numbers.
"""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_COMMITMENTS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.search import dispatch
from lawgraph.db.queries.search.ranking import SCORE_CONTAINS, SCORE_TITLE
from tests.databases import Api

AWB, BW7, REPAIR = "BWBR0005537", "BWBR0005290", "BWBR0035000"
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
    store: GraphStore, api: Api, mode: str
) -> None:
    """ "huurverhoging" is the heading of Art. IX of a Reparatiewet, no hit it names: no
    ``best``. "Awb" is the abbreviation of the Awb, "LJN AU3313" the number of the ECLI of
    a judgment (``ECLI:NL:HR:2005:AU3313``): each the ``best`` and ``exact``."""
    words = _search(api, "huurverhoging", mode=mode, resolve="true")
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
