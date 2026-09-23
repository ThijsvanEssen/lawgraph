"""`/api/resolve` and the citation search, run for real on the small test server.

The nodes are written directly, with the props the normalize steps give them: articles of the
Burgerlijk Wetboek stored without their book, articles of the Awb with it (``3:4``), a dossier
with suffixes, a Tweede Kamer and an Eerste Kamer paper.
"""

from __future__ import annotations

import time
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
from lawgraph.db import ArangoStore
from lawgraph.db.edges import make_edge_doc
from lawgraph.db.queries import search as search_module
from lawgraph.db.queries.resolve import ALTERNATIVES, resolve
from lawgraph.db.queries.search import search_all

SR, GW, AWB, BW6 = "BWBR0001854", "BWBR0001840", "BWBR0005537", "BWBR0005289"
GDPR = "32016R0679"
ECLI = "ECLI:NL:HR:2020:7"


def _put(store: ArangoStore, collection: str, key: str, **props: Any) -> None:
    doc = {"_key": key, "type": collection.rstrip("s"), "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


def _instrument(
    store: ArangoStore, law_id: str, title: str, short: str | None = None, **more: Any
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
    store: ArangoStore, law_id: str, number: str, cited: int = 0, **more: Any
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
def store(database: str) -> ArangoStore:
    store = ArangoStore()
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
    _wait_for_views(store, {"search_articles": 8, "search_documents": 2})
    return store


def _wait_for_views(store: ArangoStore, sizes: dict[str, int]) -> None:
    """The search views fill asynchronously: wait until they hold what was written."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if all(
            next(iter(store.query(f"RETURN LENGTH(FOR d IN {view} RETURN 1)"))) >= size
            for view, size in sizes.items()
        ):
            return
        time.sleep(0.2)
    raise AssertionError(f"views not filled: {sizes}")


def _keys(answer: dict[str, Any]) -> list[str]:
    return [m["key"] for m in [answer["match"], *answer["alternatives"]] if m]


# ── identifiers ───────────────────────────────────────────────────────────────


def test_an_identifier_resolves_to_its_node_with_full_confidence(
    store: ArangoStore,
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
    store: ArangoStore,
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
    store: ArangoStore, query: str, key: str
) -> None:
    answer = resolve(store, query)
    assert answer["kind"] == "article"
    assert answer["match"]["key"] == key
    assert answer["match"]["collection"] == "articles"
    assert answer["confidence"] == 0.95 == answer["match"]["confidence"]
    assert answer["alternatives"] == []


def test_the_book_is_not_an_article_of_its_own(store: ArangoStore) -> None:
    """`art. 6:162 BW` is article 162 of book 6, never article 6 of any law."""
    answer = resolve(store, "art. 6:162 BW")
    assert answer["match"]["key"] == "bwbr0005289_162"
    assert not any(k.endswith("_6") for k in _keys(answer))


def test_the_qualifier_of_a_citation_is_returned(store: ArangoStore) -> None:
    assert resolve(store, "artikel 287, derde lid, Sr")["qualifier"] == "derde lid"
    assert resolve(store, "art. 6:162 lid 2 BW")["qualifier"] == "lid 2"
    assert resolve(store, "artikel 287 Sr")["qualifier"] is None


def test_an_article_that_the_law_does_not_have_is_no_match(store: ArangoStore) -> None:
    assert resolve(store, "artikel 999 Sr")["kind"] == "none"
    assert resolve(store, "art. 9:1 BW")["kind"] == "none"
    assert resolve(store, "artikel 5 Onbekende wet")["kind"] == "none"


def test_an_enumeration_lists_the_other_articles_as_alternatives(
    store: ArangoStore,
) -> None:
    answer = resolve(store, "artikelen 287 en 36e Sr")
    assert sorted(_keys(answer)) == ["bwbr0001854_287", "bwbr0001854_36e"]


def test_an_article_without_a_law_is_the_most_cited_of_several(
    store: ArangoStore,
) -> None:
    answer = resolve(store, "artikel 1")
    assert answer["kind"] == "article"
    assert _keys(answer) == ["bwbr0001840_1", "bwbr0001854_1", "bwbr0005537_1"]
    assert answer["confidence"] == 0.3
    assert len(answer["alternatives"]) == 2 <= ALTERNATIVES


def test_an_article_without_a_law_that_only_one_law_has(store: ArangoStore) -> None:
    answer = resolve(store, "art. 3:4")
    assert answer["match"]["key"] == "bwbr0005537_3_4"
    assert answer["confidence"] == 0.5
    assert answer["alternatives"] == []


# ── dossiers and papers ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query", ["36327", "Kamerstuk 36327", "36 327", "dossier 36327"]
)
def test_a_dossier_number_is_the_dossier(store: ArangoStore, query: str) -> None:
    answer = resolve(store, query)
    assert (answer["kind"], answer["match"]["key"]) == ("dossier", "36327")
    assert answer["confidence"] == 0.95
    assert answer["match"]["display_name"] == "Wet X"


def test_a_suffix_picks_its_dossier_and_a_bare_number_lists_them(
    store: ArangoStore,
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
    store: ArangoStore, query: str
) -> None:
    answer = resolve(store, query)
    assert (answer["kind"], answer["match"]["key"]) == ("document", "tk-3")
    assert answer["match"]["collection"] == "documents"
    assert answer["confidence"] == 0.95


def test_an_eerste_kamer_paper_is_found_by_its_letter(store: ArangoStore) -> None:
    answer = resolve(store, "Kamerstuk I 35925, nr. A")
    assert (answer["kind"], answer["match"]["key"]) == ("document", "ek_a")


def test_a_paper_the_graph_lacks_is_answered_with_its_dossier(
    store: ArangoStore,
) -> None:
    answer = resolve(store, "36327-99")
    assert (answer["kind"], answer["match"]["key"]) == ("dossier", "36327")
    assert answer["confidence"] == 0.6
    assert resolve(store, "99999-1")["kind"] == "none"


# ── law names ─────────────────────────────────────────────────────────────────


def test_a_law_by_exact_name_or_abbreviation(store: ArangoStore) -> None:
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


def test_a_name_two_laws_share_lists_both_and_is_not_sure(store: ArangoStore) -> None:
    answer = resolve(store, "Besluit ruimte")
    assert sorted(_keys(answer)) == ["bwbr0009001", "bwbr0009002"]
    assert answer["confidence"] == 0.5


def test_a_law_by_the_start_or_part_of_its_name_is_less_sure(
    store: ArangoStore,
) -> None:
    prefix = resolve(store, "algemene wet")
    assert prefix["match"]["key"] == "bwbr0005537" and prefix["confidence"] == 0.6
    assert [a["key"] for a in prefix["alternatives"]] == []  # the EU act is no BWB law
    contained = resolve(store, "bestuursrecht")
    assert contained["match"]["key"] == "bwbr0005537" and contained["confidence"] == 0.4


def test_an_exact_name_comes_before_names_that_start_with_it(
    store: ArangoStore,
) -> None:
    _instrument(store, "BWBR0009100", "Grondwet voor het Koninkrijk der Nederlanden")
    search_module._law_cache.clear()
    answer = resolve(store, "Grondwet")
    assert _keys(answer) == ["bwbr0001840", "bwbr0009100"]
    assert [answer["confidence"], answer["alternatives"][0]["confidence"]] == [0.9, 0.6]


# ── what it costs ─────────────────────────────────────────────────────────────


def test_resolving_reads_by_key_or_index_never_every_document(
    store: ArangoStore,
) -> None:
    """Only the reading of the laws (once a minute, cached) may walk a collection."""
    queries: list[tuple[str, dict[str, Any]]] = []
    run = store.query

    def recording(aql: str, bind_vars: dict[str, Any] | None = None, **kw: Any) -> Any:
        queries.append((aql, bind_vars or {}))
        return run(aql, bind_vars, **kw)

    store.query = recording  # type: ignore[method-assign]
    for q in (
        ECLI,
        "BWBR0001854",
        "art. 6:162 BW",
        "artikel 1",
        "36327",
        "Kamerstuk 36327 nr. 3",
        "Wetboek van Strafrecht",
    ):
        resolve(store, q)
    asked = [
        (aql, bind)
        for aql, bind in queries
        if "names: [" not in aql and "RETURN [i.props.short_title" not in aql
    ]
    assert len(asked) >= 6
    for aql, bind in asked:
        plan = store.db.aql.explain(aql, bind_vars=bind)
        kinds = {node["type"] for node in plan["nodes"]}
        assert "EnumerateCollectionNode" not in kinds, aql


# ── search: rank, parent title, dossier number ────────────────────────────────


def test_search_finds_a_citation_the_old_parser_lost(store: ArangoStore) -> None:
    hits = search_all(store, q="art. 6:162 BW", types=["articles"], limit=5)["articles"]
    assert hits[0]["key"] == "bwbr0005289_162"
    assert hits[0]["score"] == 1.0
    assert hits[0]["extra"]["instrument_title"] == "Burgerlijk Wetboek Boek 6"
    assert hits[0]["extra"]["short_title"] == "BW6"


def test_search_articles_carry_the_title_of_their_law_also_for_eu_acts(
    store: ArangoStore,
) -> None:
    hits = search_all(store, q="artikel 287 Sr", types=["articles"], limit=5)[
        "articles"
    ]
    assert hits[0]["extra"]["instrument_title"] == "Wetboek van Strafrecht"
    eu = search_all(store, q="artikel 5 32016R0679", types=["articles"], limit=5)
    extra = eu["articles"][0]["extra"]
    assert extra["celex"] == GDPR and extra["bwb_id"] is None
    assert extra["instrument_title"] == "Algemene verordening gegevensbescherming"


def test_search_orders_by_score_and_documents_carry_their_dossier(
    store: ArangoStore,
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


def test_search_one_article_hit_costs_no_query_of_its_own(store: ArangoStore) -> None:
    """The parent title comes in the one query, not one lookup per hit."""
    queries: list[str] = []
    run = store.query

    def recording(aql: str, bind_vars: dict[str, Any] | None = None, **kw: Any) -> Any:
        queries.append(aql)
        return run(aql, bind_vars, **kw)

    store.query = recording  # type: ignore[method-assign]
    search_all(store, q="Tekst artikel", types=["articles"], limit=10)
    article_queries = [q for q in queries if "search_articles" in q or "articles" in q]
    assert len(article_queries) <= 2
