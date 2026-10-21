"""The questions of the people the search is for, as they type them (productcheck 0.80):

* a term of practice of more words than name the article: "ontslag op staande voet" is
  art. 7:677 BW, though "op" is in every other summary and names nothing;
* the articles of a search of every type ranked as those of the articles alone:
  "onrechtmatige daad" is art. 6:162 BW, in the title "Onrechtmatige daad", before the
  articles of the Wet conflictenrecht onrechtmatige daad that its case law calls so too,
  however few are asked;
* a faction in the query: "motie stikstof VVD" asks for the motions on stikstof the VVD
  submitted and the votes on them, and the answer says so."""

from __future__ import annotations

from typing import Any

from lawgraph.db import EdgeWriter, GraphStore, version_cache
from lawgraph.db.queries.search import dispatch, ranking
from lawgraph.pipelines.semantic.graph_article_terms import (
    GraphArticleTermsSemanticPipeline,
)
from tests.databases import Api

# The summaries that cite none of the articles, on every subject: a word in each of them
# (``op``) is in far more than one in ``NAME_LIFT`` of all.
OTHERS = 5_000


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": [], "props": props}


def _cites(judgment: str, article: str) -> dict[str, Any]:
    return {
        "key": f"{judgment}-{article}",
        "from_id": f"judgments/{judgment}",
        "to_id": f"articles/{article}",
        "relation": "REFERS_TO",
        "source": "test",
        "status": "canoniek",
        "confidence": 1.0,
        "meta": {},
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def _cited_by(
    store: GraphStore, article: str, citers: int, holding: int, summary: str
) -> None:
    """*article* cited by *citers* judgments, *holding* of whose summaries are *summary*
    (``{j}`` the number of the case); the others are about rent."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(
                f"{article}_c{j}",
                "judgment",
                summary=summary.format(j=j)
                if j < holding
                else f"Een geschil over de huur in zaak {j}.",
            )
            for j in range(citers)
        ],
    )
    store.bulk_insert_or_update_edges(
        [_cites(f"{article}_c{j}", article) for j in range(citers)]
    )


def _judgments(store: GraphStore, summary: str, count: int, prefix: str) -> None:
    """*count* judgments that cite no article, each with *summary*."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(f"{prefix}{j}", "judgment", summary=summary.format(j=j))
            for j in range(count)
        ],
    )


def _terms(store: GraphStore) -> None:
    """The terms of the articles, as ``semantic graph-article-terms`` keeps them."""
    for table in ("articles", "judgments"):
        store.execute(f"ANALYZE {table}")
    GraphArticleTermsSemanticPipeline(store).run()
    version_cache.clear()


def _found(
    hits: dict[str, list[dict[str, Any]]], table: str = "articles"
) -> list[tuple[str, float]]:
    return [(hit["key"], hit["score"]) for hit in hits[table]]


def test_a_term_of_practice_is_named_by_its_words_that_can_name(
    store: GraphStore,
) -> None:
    """ "ontslag op staande voet": "ontslag", "staande" and "voet" each name art. 7:677
    BW, cited by most judgments that use them; "op" is in every summary and can name no
    article (one in more than ``NAME_LIFT`` of the summaries). The query names the article
    by the words that can (0.75)."""
    version_cache.clear()
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(
                "bwbr0005290_677",
                "article",
                bwb_id="BWBR0005290",
                article_number="677",
                display_name="Artikel 677 Burgerlijk Wetboek Boek 7",
                breadcrumb=[{"title": "Titel 10. Arbeidsovereenkomst"}],
                text="Ieder der partijen is bevoegd de arbeidsovereenkomst onverwijld op"
                " te zeggen om een dringende reden, onder gelijktijdige mededeling van die"
                " reden aan de wederpartij.",
                inbound_citation_count=60,
            ),
            _node(
                "bwbr0005290_669",
                "article",
                bwb_id="BWBR0005290",
                article_number="669",
                display_name="Artikel 669 Burgerlijk Wetboek Boek 7",
                text="De werkgever kan de arbeidsovereenkomst opzeggen indien daar een"
                " redelijke grond voor is; ontslag op staande voet is geen opzegging.",
                inbound_citation_count=30,
            ),
        ],
    )
    _cited_by(
        store,
        "bwbr0005290_677",
        60,
        40,
        "Ontslag op staande voet van een werknemer wegens diefstal, zaak {j}.",
    )
    _cited_by(store, "bwbr0005290_669", 30, 0, "")
    _judgments(store, "Een beroep op ontslag op staande voet, {j}.", 6, "u")
    _judgments(store, "Een besluit op bezwaar over iets anders, {j}.", OTHERS, "o")
    _terms(store)

    q = "ontslag op staande voet"
    full = dispatch.search_all(store, q=q, types=["articles"], limit=10)
    live, _ = dispatch.search_live(store, q=q, types=["articles"], limit=10)
    assert _found(full)[0] == ("bwbr0005290_677", ranking.SCORE_TITLE)
    assert _found(live)[0] == ("bwbr0005290_677", ranking.SCORE_TITLE)


def _wcod(n: int) -> dict[str, Any]:
    return _node(
        f"bwbr0012408_{n}",
        "article",
        bwb_id="BWBR0012408",
        article_number=str(n),
        display_name=f"Artikel {n} Wet conflictenrecht onrechtmatige daad",
        text="Verbintenissen uit onrechtmatige daad worden beheerst door het recht van de"
        " Staat op welks grondgebied de daad plaatsvindt.",
        inbound_citation_count=6,
    )


def test_the_articles_of_every_type_are_ranked_as_the_articles_alone(
    store: GraphStore,
) -> None:
    """ "onrechtmatige daad" with six hits a type, as the search box asks: art. 6:162 BW
    stands in the title "Onrechtmatige daad" (part of its name, 0.25) and is cited on
    every subject, under the share that makes the words its terms. The ten articles of
    the Wet conflictenrecht onrechtmatige daad hold the words in their law's name and
    text, and its case law calls them so (terms, ranked higher by them, 0.1). The best tier
    goes first before the limit, in the full search and while typing, with the papers or
    without."""
    version_cache.clear()
    title = [{"title": "Titel 3. Onrechtmatige daad"}]
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(
                "bwbr0005289_162",
                "article",
                bwb_id="BWBR0005289",
                article_number="162",
                display_name="Artikel 162 Burgerlijk Wetboek Boek 6",
                breadcrumb=title,
                text="Hij die jegens een ander een onrechtmatige daad pleegt, welke hem"
                " kan worden toegerekend, is verplicht de schade die de ander dientengevolge"
                " lijdt, te vergoeden.",
                inbound_citation_count=400,
            ),
            *(_wcod(n) for n in range(1, 11)),
        ],
    )
    _cited_by(
        store,
        "bwbr0005289_162",
        400,
        50,
        "Aansprakelijkheid uit onrechtmatige daad, {j}.",
    )
    for n in range(1, 11):
        _cited_by(
            store,
            f"bwbr0012408_{n}",
            6,
            5,
            "Toepasselijk recht op een onrechtmatige daad in het buitenland, {j}.",
        )
    _judgments(store, "Een vordering uit onrechtmatige daad, {j}.", 300, "u")
    _judgments(store, "Een besluit over iets anders, {j}.", OTHERS, "o")
    _terms(store)

    q = "onrechtmatige daad"
    alone = dispatch.search_all(store, q=q, types=["articles"], limit=20)
    mixed = dispatch.search_all(store, q=q, types=["articles", "documents"], limit=6)
    live, _ = dispatch.search_live(store, q=q, types=["articles", "documents"], limit=6)
    assert _found(alone)[0] == ("bwbr0005289_162", ranking.SCORE_CONTAINS)
    assert _found(mixed) == _found(alone)[:6]
    assert _found(live)[0] == ("bwbr0005289_162", ranking.SCORE_CONTAINS)


# ── a faction in the query ────────────────────────────────────────────────────

VVD = "7476e97a-3243-4122-9df6-ba7d82a5279b"
BBB = "626555ac-e836-44e3-9978-a6a7f0abc3ce"
CDA = "62c1a13c-85ff-40ed-90f7-a9546d61f869"
OMTZIGT = "acc6e04b-e53e-489b-8904-dc91d3af2e11"


def _actor(name: str, faction_id: str, faction: str) -> dict[str, Any]:
    return {
        "person_id": f"p-{name}",
        "faction_id": faction_id,
        "name": name,
        "faction": faction,
        "role": "Eerste ondertekenaar",
        "function": "Tweede Kamerlid",
        "capacity": "kamerlid",
    }


def _motion(key: str, title: str, date: str, *actors: dict[str, Any]) -> dict[str, Any]:
    return _node(
        key,
        "document",
        title=title,
        kind="Motie",
        date=date,
        dossier_numbers=["35334"],
        actors=list(actors),
    )


def _vote(key: str, subject: str, date: str, case: str) -> dict[str, Any]:
    return _node(
        key,
        "decision",
        subject=subject,
        kind="Motie",
        date=date,
        primary_case_id=case,
        passed=True,
    )


def _parliament(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            _node(
                "vvd",
                "faction",
                name="Volkspartij voor Vrijheid en Democratie",
                abbreviation="VVD",
                aliases=["VVD", "Volkspartij voor Vrijheid en Democratie"],
                external_id=VVD,
                external_ids=[VVD],
            ),
            _node(
                "ek_volkspartij_voor_vrijheid_en",
                "faction",
                name="VVD-fractie",
                abbreviation="VVD",
                chamber="EK",
            ),
            _node(
                "bbb",
                "faction",
                name="BoerBurgerBeweging",
                abbreviation="BBB",
                aliases=["BBB", "BoerBurgerBeweging"],
                external_id=BBB,
            ),
            _node(
                "cda",
                "faction",
                name="Christen-Democratisch Appèl",
                abbreviation="CDA",
                external_id=CDA,
            ),
            # a faction named after its one member, who sat for the CDA before
            _node(
                "omtzigt",
                "faction",
                name="Omtzigt",
                abbreviation="Omtzigt",
                external_id=OMTZIGT,
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "members", [_node("omtzigt_p", "member", name="P.H. Omtzigt")]
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _motion(
                "motion_vvd",
                "Motie van het lid Van Campen over de stikstofaanpak",
                "2024-05-02",
                _actor("Van Campen", VVD, "VVD"),
            ),
            _motion(
                "motion_vvd_bbb",
                "Motie van de leden Van Campen en Van der Plas over stikstofruimte",
                "2024-05-01",
                _actor("Van der Plas", BBB, "BBB"),
                _actor("Van Campen", VVD, "VVD"),
            ),
            _motion(
                "motion_bbb",
                "Motie van het lid Van der Plas over stikstofregels",
                "2024-05-03",
                _actor("Van der Plas", BBB, "BBB"),
            ),
            _motion(
                "motion_vvd_housing",
                "Motie van het lid Van Campen over woningbouw",
                "2024-05-04",
                _actor("Van Campen", VVD, "VVD"),
            ),
            _motion(
                "motion_omtzigt",
                "Motie van het lid Omtzigt over stikstofdepositie",
                "2019-05-01",
                _actor("Omtzigt", CDA, "CDA"),
            ),
        ],
    )
    cases = {"motion_vvd": "case-vvd", "motion_bbb": "case-bbb"}
    store.bulk_insert_or_update_nodes(
        "cases",
        [
            _node(case.replace("-", "_"), "case", kind="Motie")
            for case in cases.values()
        ],
    )
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _vote(
                "vote_vvd",
                "Motie van het lid Van Campen over de stikstofaanpak",
                "2024-05-14",
                "case-vvd",
            ),
            _vote(
                "vote_bbb",
                "Motie van het lid Van der Plas over stikstofregels",
                "2024-05-14",
                "case-bbb",
            ),
        ],
    )
    with EdgeWriter(store, what=None) as edges:
        for motion, case in cases.items():
            edges.add(
                f"documents/{motion}",
                f"cases/{case.replace('-', '_')}",
                "PART_OF",
                source="t",
            )


def test_a_faction_in_the_query_keeps_what_was_signed_for_it(
    store: GraphStore, api: Api
) -> None:
    """ "motie stikstof VVD": the motions on stikstof a Kamerlid of the VVD signed for it
    (alone or with others) and the votes on them, in full and while typing;
    "VVD" is no word of their titles. The answer names the faction it filtered on."""
    version_cache.clear()
    _parliament(store)

    for mode in ("full", "live"):
        answer = api.get_json(
            "/api/search",
            q="motie stikstof VVD",
            types=["decisions", "documents"],
            mode=mode,
        )
        keys = {t: {h["key"] for h in hits} for t, hits in answer["results"].items()}
        assert keys == {
            "decisions": {"vote_vvd"},
            "documents": {"motion_vvd", "motion_vvd_bbb"},
        }, mode
        by = [
            {
                "words": "vvd",
                "name": "VVD",
                "factions": ["vvd", "ek_volkspartij_voor_vrijheid_en"],
            }
        ]
        assert answer["searched"]["decisions"]["signed_for"] == by
        assert answer["searched"]["documents"]["signed_for"] == by


def test_a_faction_that_is_all_of_the_query_or_a_member_is_a_word(
    store: GraphStore, api: Api
) -> None:
    """ "VVD" alone asks for the faction: nothing is filtered. "Omtzigt" is a faction and
    the name of a member, which the title of a motion holds ("Motie van het lid Omtzigt"),
    signed for the CDA: a word."""
    version_cache.clear()
    _parliament(store)

    alone = api.get_json("/api/search", q="VVD", types=["factions", "documents"])
    assert [h["key"] for h in alone["results"]["factions"]][:1] == ["vvd"]
    assert alone["searched"]["documents"]["signed_for"] == []

    member = api.get_json("/api/search", q="motie omtzigt", types=["documents"])
    assert [h["key"] for h in member["results"]["documents"]] == ["motion_omtzigt"]
    assert member["searched"]["documents"]["signed_for"] == []
