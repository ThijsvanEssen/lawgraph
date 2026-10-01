"""`/api/resolve` and the citation search, run for real on the small test server.

The nodes are written directly, with the props the normalize steps give them: articles of the
Burgerlijk Wetboek stored without their book, articles of the Awb with it (``3:4``), a dossier
with suffixes, a Tweede Kamer and an Eerste Kamer paper.
"""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.edges import make_edge_doc
from lawgraph.db.queries import search as search_module
from lawgraph.db.queries.resolve import ALTERNATIVES, resolve
from lawgraph.db.queries.search import SCORE_IDENTIFIER, SCORE_WORDS, search_all
from lawgraph.db.store import _text

SR, GW, AWB, BW6 = "BWBR0001854", "BWBR0001840", "BWBR0005537", "BWBR0005289"
GDPR = "32016R0679"
ECLI = "ECLI:NL:HR:2020:7"


def _put(store: GraphStore, collection: str, key: str, **props: Any) -> None:
    doc = {"_key": key, "type": collection.rstrip("s"), "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


def _instrument(
    store: GraphStore, law_id: str, title: str, short: str | None = None, **more: Any
) -> None:
    ids = {"celex": law_id} if law_id[0].isdigit() else {"bwb_id": law_id}
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        make_node_key(law_id),
        title=title,
        display_name=title,
        citation_title=title,
        short_title=short,
        **ids,
        **more,
    )


def _article(
    store: GraphStore, law_id: str, number: str, cited: int = 0, **more: Any
) -> None:
    ids = {"celex": law_id} if law_id[0].isdigit() else {"bwb_id": law_id}
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(law_id, number),
        article_number=number,
        display_name=f"Artikel {number}",
        text=f"Tekst van artikel {number}.",
        inbound_citation_count=cited,
        **ids,
        **more,
    )


@pytest.fixture()
def store(database: str) -> GraphStore:
    store = GraphStore()
    _instrument(store, GW, "Grondwet")
    _instrument(store, SR, "Wetboek van Strafrecht", "Sr")
    _instrument(store, AWB, "Algemene wet bestuursrecht", "Awb")
    _instrument(store, BW6, "Burgerlijk Wetboek Boek 6", "BW6")
    _instrument(store, "BWBR0009001", "Besluit ruimte")  # two laws, one name
    _instrument(store, "BWBR0009002", "Besluit ruimte")
    _instrument(store, GDPR, "Algemene verordening gegevensbescherming")
    for law, number, cited in (
        (GW, "1", 5),
        (SR, "1", 2),
        (SR, "287", 9),
        (SR, "36e", 0),
        (AWB, "1", 1),
        (AWB, "3:4", 4),
        (BW6, "162", 30),
    ):
        _article(store, law, number, cited)
    _article(store, GDPR, "5", 3)
    _put(store, COLLECTION_JUDGMENTS, make_node_key(ECLI), ecli=ECLI, display_name=ECLI)
    _put(store, COLLECTION_DOSSIERS, "36327", number="36327", suffix="", title="Wet X")
    _put(store, COLLECTION_DOSSIERS, "29684_i", number="29684", suffix="I", title="A")
    _put(store, COLLECTION_DOSSIERS, "29684_ii", number="29684", suffix="II", title="B")
    _put(store, COLLECTION_DOSSIERS, "35925", number="35925", suffix="", title="EK")
    _put(
        store,
        COLLECTION_DOCUMENTS,
        "tk-3",
        source="tk",
        sequence=3,
        kind="Voorstel van wet",
        dossier_numbers=["36327"],
        dossier_number="36327",
        display_name="Kamerstuk 36327, nr. 3",
    )
    _put(
        store,
        COLLECTION_DOCUMENTS,
        "ek_a",
        source="eerstekamer",
        number="A",
        dossier_number="35925",
        dossier_numbers=["35925"],
        display_name="EK 35925, nr. A",
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                f"{COLLECTION_DOCUMENTS}/tk-3",
                f"{COLLECTION_DOSSIERS}/36327",
                RELATION_PART_OF,
            ),
            make_edge_doc(
                f"{COLLECTION_DOCUMENTS}/ek_a",
                f"{COLLECTION_DOSSIERS}/35925",
                RELATION_PART_OF,
            ),
        ]
    )
    return store


def _keys(answer: dict[str, Any]) -> list[str]:
    return [m["key"] for m in [answer["match"], *answer["alternatives"]] if m]


# ── identifiers ───────────────────────────────────────────────────────────────


def test_an_identifier_resolves_to_its_node_with_full_confidence(
    store: GraphStore,
) -> None:
    ecli = resolve(store, "ecli:nl:hr:2020:7")
    assert ecli["kind"] == "judgment" and ecli["confidence"] == 1.0
    assert ecli["match"]["id"] == f"judgments/{make_node_key(ECLI)}"
    assert ecli["match"]["collection"] == "judgments"

    bwb = resolve(store, "bwbr0001854")
    assert (bwb["kind"], bwb["match"]["key"]) == ("instrument", "bwbr0001854")
    assert bwb["match"]["display_name"] == "Wetboek van Strafrecht"

    celex = resolve(store, "32016R0679")
    assert (celex["kind"], celex["match"]["key"]) == ("instrument", "32016r0679")


def test_an_identifier_nobody_loaded_is_no_match_not_an_error(
    store: GraphStore,
) -> None:
    for query in (
        "ECLI:NL:HR:1999:1",
        "BWBR0999999",
        "32000R9999",
        "moord en doodslag",
    ):
        assert resolve(store, query) == {
            "kind": "none",
            "confidence": 0.0,
            "match": None,
            "alternatives": [],
            "qualifier": None,
        }


# ── articles ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("query", "key"),
    [
        ("artikel 287 Sr", "bwbr0001854_287"),
        ("art. 287 sr", "bwbr0001854_287"),
        ("Sr 287", "bwbr0001854_287"),
        ("artikel 36e Sr", "bwbr0001854_36e"),
        ("artikel 287 Wetboek van Strafrecht", "bwbr0001854_287"),
        ("art. 1 Grondwet", "bwbr0001840_1"),
        ("art. 3:4 Awb", "bwbr0005537_3_4"),
        ("Algemene wet bestuursrecht artikel 3:4", "bwbr0005537_3_4"),
        ("art. 6:162 BW", "bwbr0005289_162"),
        ("art. 6:162 lid 2 BW", "bwbr0005289_162"),
        ("artikel 287 BWBR0001854", "bwbr0001854_287"),
        ("artikel 5 32016R0679", "32016r0679_5"),
    ],
)
def test_an_article_of_a_named_law_is_one_key(
    store: GraphStore, query: str, key: str
) -> None:
    answer = resolve(store, query)
    assert answer["kind"] == "article"
    assert answer["match"]["key"] == key
    assert answer["match"]["collection"] == "articles"
    assert answer["confidence"] == 0.95 == answer["match"]["confidence"]
    assert answer["alternatives"] == []


def test_the_book_is_not_an_article_of_its_own(store: GraphStore) -> None:
    """`art. 6:162 BW` is article 162 of book 6, never article 6 of any law."""
    answer = resolve(store, "art. 6:162 BW")
    assert answer["match"]["key"] == "bwbr0005289_162"
    assert not any(k.endswith("_6") for k in _keys(answer))


def test_the_qualifier_of_a_citation_is_returned(store: GraphStore) -> None:
    assert resolve(store, "artikel 287, derde lid, Sr")["qualifier"] == "derde lid"
    assert resolve(store, "art. 6:162 lid 2 BW")["qualifier"] == "lid 2"
    assert resolve(store, "artikel 287 Sr")["qualifier"] is None


def test_an_article_that_the_law_does_not_have_is_no_match(store: GraphStore) -> None:
    assert resolve(store, "artikel 999 Sr")["kind"] == "none"
    assert resolve(store, "art. 9:1 BW")["kind"] == "none"
    assert resolve(store, "artikel 5 Onbekende wet")["kind"] == "none"


def test_an_enumeration_lists_the_other_articles_as_alternatives(
    store: GraphStore,
) -> None:
    answer = resolve(store, "artikelen 287 en 36e Sr")
    assert sorted(_keys(answer)) == ["bwbr0001854_287", "bwbr0001854_36e"]


def test_an_article_without_a_law_is_the_most_cited_of_several(
    store: GraphStore,
) -> None:
    answer = resolve(store, "artikel 1")
    assert answer["kind"] == "article"
    assert _keys(answer) == ["bwbr0001840_1", "bwbr0001854_1", "bwbr0005537_1"]
    assert answer["confidence"] == 0.3
    assert len(answer["alternatives"]) == 2 <= ALTERNATIVES


def test_an_article_without_a_law_that_only_one_law_has(store: GraphStore) -> None:
    answer = resolve(store, "art. 3:4")
    assert answer["match"]["key"] == "bwbr0005537_3_4"
    assert answer["confidence"] == 0.5
    assert answer["alternatives"] == []


def _treaty_and_eu_act(store: GraphStore) -> None:
    """The EVRM as ``normalize bwb`` writes it, and the AVG with the short title of
    EUR-Lex; its abbreviation is the one ``curated instrument-abbreviations`` keeps."""
    _evrm(store)
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        make_node_key(GDPR),
        celex=GDPR,
        title="Verordening (EU) 2016/679 van het Europees Parlement en de Raad",
        citation_title="Verordening (EU) 2016/679",
        short_title="Algemene verordening gegevensbescherming",
    )
    _article(store, GDPR, "6")
    search_module._law_cache.clear()


@pytest.mark.parametrize(
    ("query", "key"),
    [
        ("art. 8 EVRM", "bwbv0001000_8"),
        ("artikel 8, eerste lid, van het EVRM", "bwbv0001000_8"),
        ("art. 6 AVG", "32016r0679_6"),
        ("artikel 6, eerste lid, AVG", "32016r0679_6"),
    ],
)
def test_an_article_of_a_treaty_or_eu_act_by_its_abbreviation(
    store: GraphStore, query: str, key: str
) -> None:
    _treaty_and_eu_act(store)
    answer = resolve(store, query)
    assert (answer["kind"], answer["match"]["key"]) == ("article", key)
    assert answer["confidence"] == 0.95


def test_a_treaty_or_eu_act_by_its_abbreviation(store: GraphStore) -> None:
    _treaty_and_eu_act(store)
    for query, key in (("EVRM", "bwbv0001000"), ("AVG", "32016r0679")):
        answer = resolve(store, query)
        assert (answer["kind"], answer["match"]["key"]) == ("instrument", key), query
        assert answer["confidence"] == 0.9


def test_an_article_of_a_law_that_is_not_loaded_is_no_match(
    store: GraphStore,
) -> None:
    assert resolve(store, "art. 350 Sv")["kind"] == "none"


# ── dossiers and papers ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query", ["36327", "Kamerstuk 36327", "36 327", "dossier 36327"]
)
def test_a_dossier_number_is_the_dossier(store: GraphStore, query: str) -> None:
    answer = resolve(store, query)
    assert (answer["kind"], answer["match"]["key"]) == ("dossier", "36327")
    assert answer["confidence"] == 0.95
    assert answer["match"]["display_name"] == "Wet X"


def test_a_suffix_picks_its_dossier_and_a_bare_number_lists_them(
    store: GraphStore,
) -> None:
    answer = resolve(store, "29684-I")
    assert answer["match"]["key"] == "29684_i" and answer["confidence"] == 0.95
    assert [a["key"] for a in answer["alternatives"]] == ["29684_ii"]

    bare = resolve(store, "Kamerstuk 29684")  # only its suffixed variants exist
    assert sorted(_keys(bare)) == ["29684_i", "29684_ii"]
    assert bare["confidence"] == 0.5


@pytest.mark.parametrize(
    "query",
    [
        "36327-3",
        "Kamerstuk 36327-3",
        "Kamerstuk 36327 nr. 3",
        "Kamerstukken II 2020/21, 36327, nr. 3",
        "kst-36327-3",
    ],
)
def test_a_paper_is_found_through_its_dossier_and_ondernummer(
    store: GraphStore, query: str
) -> None:
    answer = resolve(store, query)
    assert (answer["kind"], answer["match"]["key"]) == ("document", "tk-3")
    assert answer["match"]["collection"] == "documents"
    assert answer["confidence"] == 0.95


def test_an_eerste_kamer_paper_is_found_by_its_letter(store: GraphStore) -> None:
    answer = resolve(store, "Kamerstuk I 35925, nr. A")
    assert (answer["kind"], answer["match"]["key"]) == ("document", "ek_a")


def test_a_paper_the_graph_lacks_is_answered_with_its_dossier(
    store: GraphStore,
) -> None:
    answer = resolve(store, "36327-99")
    assert (answer["kind"], answer["match"]["key"]) == ("dossier", "36327")
    assert answer["confidence"] == 0.6
    assert resolve(store, "99999-1")["kind"] == "none"


# ── law names ─────────────────────────────────────────────────────────────────


def test_a_law_by_exact_name_or_abbreviation(store: GraphStore) -> None:
    for query in (
        "Wetboek van Strafrecht",
        "wetboek van strafrecht",
        "de Grondwet",
        "Sr",
    ):
        answer = resolve(store, query)
        assert answer["kind"] == "instrument", query
        assert answer["confidence"] == 0.9, query
    assert resolve(store, "Wetboek van Strafrecht")["match"]["key"] == "bwbr0001854"
    assert resolve(store, "Sr")["match"]["key"] == "bwbr0001854"
    assert resolve(store, "de Grondwet")["match"]["key"] == "bwbr0001840"


def test_a_name_two_laws_share_lists_both_and_is_not_sure(store: GraphStore) -> None:
    answer = resolve(store, "Besluit ruimte")
    assert sorted(_keys(answer)) == ["bwbr0009001", "bwbr0009002"]
    assert answer["confidence"] == 0.5


def test_a_law_by_the_start_or_part_of_its_name_is_less_sure(
    store: GraphStore,
) -> None:
    prefix = resolve(store, "algemene wet")
    assert prefix["match"]["key"] == "bwbr0005537" and prefix["confidence"] == 0.6
    assert [a["key"] for a in prefix["alternatives"]] == []  # the EU act is no BWB law
    contained = resolve(store, "bestuursrecht")
    assert contained["match"]["key"] == "bwbr0005537" and contained["confidence"] == 0.4


def test_an_exact_name_comes_before_names_that_start_with_it(
    store: GraphStore,
) -> None:
    _instrument(store, "BWBR0009100", "Grondwet voor het Koninkrijk der Nederlanden")
    search_module._law_cache.clear()
    answer = resolve(store, "Grondwet")
    assert _keys(answer) == ["bwbr0001840", "bwbr0009100"]
    assert [answer["confidence"], answer["alternatives"][0]["confidence"]] == [0.9, 0.6]


# ── search: rank, parent title, dossier number ────────────────────────────────


def test_search_finds_a_citation_the_old_parser_lost(store: GraphStore) -> None:
    hits = search_all(store, q="art. 6:162 BW", types=["articles"], limit=5)["articles"]
    assert hits[0]["key"] == "bwbr0005289_162"
    assert hits[0]["score"] == 1.0
    assert hits[0]["extra"]["instrument_title"] == "Burgerlijk Wetboek Boek 6"
    assert hits[0]["extra"]["short_title"] == "BW6"


def test_search_articles_carry_the_title_of_their_law_also_for_eu_acts(
    store: GraphStore,
) -> None:
    hits = search_all(store, q="artikel 287 Sr", types=["articles"], limit=5)[
        "articles"
    ]
    assert hits[0]["extra"]["instrument_title"] == "Wetboek van Strafrecht"
    eu = search_all(store, q="artikel 5 32016R0679", types=["articles"], limit=5)
    extra = eu["articles"][0]["extra"]
    assert extra["celex"] == GDPR and extra["bwb_id"] is None
    assert extra["instrument_title"] == "Algemene verordening gegevensbescherming"


@pytest.mark.parametrize(
    ("query", "key"),
    [
        ("Art. 1 Grondwet", "bwbr0001840_1"),
        ("Sr 287", "bwbr0001854_287"),
        ("artikel 287 Sr", "bwbr0001854_287"),
        ("art. 6:162 BW", "bwbr0005289_162"),  # the book picks the regulation
    ],
)
def test_search_a_citation_finds_its_article_first_with_the_top_score(
    store: GraphStore, query: str, key: str
) -> None:
    hits = search_all(store, q=query, types=["articles"], limit=5)["articles"]
    assert hits[0]["key"] == key
    assert hits[0]["score"] == SCORE_IDENTIFIER
    assert hits[0]["extra"]["instrument_title"]


def test_search_an_article_without_law_looks_at_every_law_with_that_number(
    store: GraphStore,
) -> None:
    hits = search_all(store, q="artikel 1", types=["articles"], limit=5)["articles"]
    precise = [h["key"] for h in hits if h["score"] == SCORE_IDENTIFIER]
    assert precise == ["bwbr0001840_1", "bwbr0001854_1", "bwbr0005537_1"]


def test_search_falls_back_to_text_for_free_form_queries(store: GraphStore) -> None:
    hits = search_all(store, q="Tekst", types=["articles"], limit=10)["articles"]
    assert hits and {h["score"] for h in hits} == {SCORE_WORDS}


def test_search_orders_by_score_and_documents_carry_their_dossier(
    store: GraphStore,
) -> None:
    articles = search_all(store, q="Tekst", types=["articles"], limit=10)["articles"]
    assert articles and all(0 < a["score"] <= 1 for a in articles)
    assert [a["score"] for a in articles] == sorted(
        (a["score"] for a in articles), reverse=True
    )
    documents = search_all(store, q="Kamerstuk", types=["documents"], limit=5)
    assert documents["documents"][0]["key"] == "tk-3"
    assert documents["documents"][0]["extra"]["dossier_number"] == "36327"
    papers = search_all(store, q="EK", types=["documents"], limit=5)["documents"]
    assert papers[0]["key"] == "ek_a"
    assert papers[0]["extra"]["dossier_number"] == "35925"


def test_search_one_article_hit_costs_no_query_of_its_own(store: GraphStore) -> None:
    """The parent title comes in the one query, not one lookup per hit."""
    queries: list[str] = []
    run = store.query

    def recording(statement: Any, params: Any = None, **kw: Any) -> Any:
        queries.append(_text(statement))
        return iter(list(run(statement, params, **kw)))

    store.query = recording  # type: ignore[method-assign]
    search_all(store, q="Tekst artikel", types=["articles"], limit=10)
    article_queries = [q for q in queries if "articles" in q]
    # the mean field lengths (once a minute), the document frequencies of the words and
    # the search itself, with the titles of the laws
    assert len(article_queries) <= 3


def _evrm(store: GraphStore) -> None:
    """The ECHR Convention as ``normalize bwb`` writes BWBV0001000: EVRM from its WTI."""
    store.bulk_insert_or_update_nodes(
        COLLECTION_INSTRUMENTS,
        [
            {
                "_key": "bwbv0001000",
                "type": "instrument",
                "labels": [],
                "props": {
                    "bwb_id": "BWBV0001000",
                    "title": "Verdrag tot bescherming van de rechten van de mens en de "
                    "fundamentele vrijheden",
                    "short_title": "EVRM",
                    "aliases": ["EVRM"],
                },
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_ARTICLES,
        [
            {
                "_key": "bwbv0001000_8",
                "type": "article",
                "labels": [],
                "props": {"bwb_id": "BWBV0001000", "article_number": "8"},
            }
        ],
    )
