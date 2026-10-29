"""Tests for the /api/search endpoint: tokens, ranking and the citation intent."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.routes.resolve import RESOLVE_MAX_LENGTH
from lawgraph.db import version_cache
from lawgraph.db.queries.resolve import NO_MATCH
from lawgraph.db.queries.search.clause import (
    Period,
    QueryWords,
    letters_joined,
    tokenize_search_query,
)
from lawgraph.db.queries.search.ranking import (
    SCORE_CONTAINS,
    SCORE_IDENTIFIER,
    SCORE_PREFIX,
    SCORE_TITLE,
    SCORE_WORDS,
    exact_hit,
    rank_hits,
    score_hit,
)
from tests.api.stubs import stub_route
from tests.asserts import assert_status

# ── Pure-function tests ───────────────────────────────────────────────────────


def test_tokenize_drops_short_tokens_and_lowercases():
    assert tokenize_search_query("Art. 1 Grondwet") == ["art.", "grondwet"]
    assert tokenize_search_query("BWBR0001854 a b cd") == ["bwbr0001854", "cd"]


@pytest.mark.parametrize(
    ("query", "joined"),
    [
        ("J en V", "jenv"),
        ("j & v", "jenv"),
        ("j&v", "jenv"),
        ("B Z K", "bzk"),
        ("BZ K", "bzk"),
        ("a en b", "aenb"),
        ("BZK", None),
        ("BZ EZ", None),
        ("lid a", None),
        ("art 6 a", None),
        ("Justitie en Veiligheid", None),
        ("en", None),
    ],
)
def test_loose_letters_are_one_abbreviation(query: str, joined: str | None) -> None:
    assert letters_joined(query) == joined


def hit(**fields: Any) -> dict[str, Any]:
    return {"id": "x/k", "key": "k", "display_name": None, "extra": {}, **fields}


@pytest.mark.parametrize(
    ("query", "the_hit", "score"),
    [
        # An identifier of the hit, in any case; the key of the node.
        ("BWBR0001854", hit(extra={"bwb_id": "BWBR0001854"}), SCORE_IDENTIFIER),
        ("bwbr0001854", hit(extra={"bwb_id": "BWBR0001854"}), SCORE_IDENTIFIER),
        ("Sr", hit(extra={"short_title": "Sr"}), SCORE_IDENTIFIER),
        ("36327", hit(extra={"number": "36327"}), SCORE_IDENTIFIER),
        # a paper is no identifier of its dossier: every paper of it holds its number
        (
            "36327",
            hit(collection="documents", extra={"dossier_number": "36327"}),
            SCORE_WORDS,
        ),
        ("BZK", hit(collection="ministries", extra={"abbreviation": "BZK"}), 1.0),
        (
            "ECLI:NL:HR:2020:7",
            hit(key="ecli_nl_hr_2020_7", extra={"ecli": "ECLI:NL:HR:2020:7"}),
            SCORE_IDENTIFIER,
        ),
        # The whole name.
        ("Grondwet", hit(display_name="Grondwet"), SCORE_TITLE),
        ("  grondwet ", hit(display_name="Grondwet"), SCORE_TITLE),
        (
            "Wetboek van Strafrecht",
            hit(extra={"citation_title": "Wetboek van Strafrecht"}),
            SCORE_TITLE,
        ),
        # The name of a judgment is a name of it.
        ("urgenda", hit(extra={"names": ["Urgenda"]}), SCORE_TITLE),
        ("Lindenbaum", hit(extra={"names": ["Lindenbaum/Cohen"]}), SCORE_PREFIX),
        ("moord", hit(extra={"names": None}), SCORE_WORDS),
        # The start of a name; a part of one; words only.
        ("wetboek van", hit(display_name="Wetboek van Strafrecht"), SCORE_PREFIX),
        ("strafrecht", hit(display_name="Wetboek van Strafrecht"), SCORE_CONTAINS),
        (
            "wetboek strafrecht",
            hit(display_name="Wetboek van Strafrecht"),
            SCORE_CONTAINS,
        ),
        ("moord", hit(display_name="Wetboek van Strafrecht"), SCORE_WORDS),
        ("moord", hit(), SCORE_WORDS),
        # The heading of an article and the aliases of a law are names of the hit.
        ("definities", hit(extra={"heading": "Definities"}), SCORE_TITLE),
        ("Boek 6 BW", hit(extra={"aliases": ["BW", "Boek 6 BW"]}), SCORE_TITLE),
        ("bw", hit(extra={"aliases": ["BW", "Boek 6 BW"]}), SCORE_TITLE),
        # The title of a division places an article without naming it.
        (
            "verhoging van strafbaarheid",
            hit(
                extra={
                    "division_titles": ["Uitsluiting en verhoging van strafbaarheid"]
                }
            ),
            SCORE_CONTAINS,
        ),
        # Letters with and without accents are one, as ``lg_fold`` folds them.
        ("yesilgoz", hit(display_name="Dilan Yeşilgöz-Zegerius"), SCORE_CONTAINS),
        ("Yeşilgöz", hit(display_name="dilan yesilgoz-zegerius"), SCORE_CONTAINS),
        ("dilan yesilgoz", hit(display_name="Dilan Yeşilgöz-Zegerius"), SCORE_PREFIX),
        ("cooperatie", hit(extra={"heading": "Coöperatie"}), SCORE_TITLE),
        ("", hit(display_name="Grondwet"), SCORE_WORDS),
        # The name of an article's law is not its name: every article of the Wet
        # conflictenrecht onrechtmatige daad would hold the words; art. 6:162 BW holds them
        # in the title of its division. The whole name, or its start, is still the article.
        (
            "onrechtmatige daad",
            hit(
                collection="articles",
                display_name="Artikel 5 Wet conflictenrecht onrechtmatige daad",
                extra={"instrument_title": "Wet conflictenrecht onrechtmatige daad"},
            ),
            SCORE_WORDS,
        ),
        (
            "onrechtmatige daad",
            hit(
                collection="articles",
                display_name="Artikel 162 Burgerlijk Wetboek Boek 6",
                extra={"division_titles": ["Titel 3. Onrechtmatige daad"]},
            ),
            SCORE_CONTAINS,
        ),
        (
            "wet conflictenrecht onrechtmatige daad",
            hit(
                collection="articles",
                display_name="Artikel 5 Wet conflictenrecht onrechtmatige daad",
                extra={"instrument_title": "Wet conflictenrecht onrechtmatige daad"},
            ),
            SCORE_TITLE,
        ),
        # a judgment's case number is no name: the type code of the case is not a word of it
        (
            "huur",
            hit(
                collection="judgments",
                display_name="Rechtbank Amsterdam 2009-07-08 / AWB 08/5197 HUUR",
            ),
            SCORE_WORDS,
        ),
        (
            "urgenda",
            hit(
                collection="judgments",
                display_name="Hoge Raad 2019-12-20 / 19/00135",
                extra={"names": ["Staat/Urgenda"]},
            ),
            SCORE_CONTAINS,
        ),
        (
            "rechtbank amsterdam",
            hit(
                collection="judgments",
                display_name="Rechtbank Amsterdam 2009-07-08 / AWB 08/5197 HUUR",
            ),
            SCORE_PREFIX,
        ),
        # with the article's number, the name of its law names it ("art 2 klimaatfonds")
        (
            "art 2 klimaatfonds",
            hit(
                collection="articles",
                display_name="Artikel 2 Tijdelijke wet Klimaatfonds",
                extra={"article_number": "2"},
            ),
            SCORE_CONTAINS,
        ),
        (
            "art 2 klimaatfonds",
            hit(
                collection="articles",
                display_name="Artikel 1 Tijdelijke wet Klimaatfonds",
                extra={"article_number": "1"},
            ),
            SCORE_WORDS,
        ),
        (
            "onrechtmatige daad",
            hit(
                collection="instruments",
                display_name="Wet conflictenrecht onrechtmatige daad",
            ),
            SCORE_CONTAINS,
        ),
        # a member by the name without the names or initials before it, not by a part of it
        ("Rutte", hit(collection="members", display_name="Mark Rutte"), SCORE_TITLE),
        (
            "rutte",
            hit(collection="members", display_name="P.J. Rutten"),
            SCORE_CONTAINS,
        ),
        # of a double surname each part, and the whole
        *(
            (q, hit(collection="members", display_name="Dilan Yeşilgöz-Zegerius"), 0.75)
            for q in ("Yeşilgöz", "yesilgoz", "Zegerius", "Yeşilgöz-Zegerius")
        ),
        (
            "Rutte",
            hit(collection="instruments", display_name="Besluit Rutte"),
            SCORE_CONTAINS,
        ),
    ],
)
def test_score_is_the_rank_tier_of_the_best_match(
    query: str, the_hit: dict[str, Any], score: float
) -> None:
    assert score_hit(query, the_hit) == score


def test_the_tiers_are_ordered() -> None:
    assert (
        SCORE_IDENTIFIER > SCORE_TITLE > SCORE_PREFIX > SCORE_CONTAINS > SCORE_WORDS > 0
    )


def test_hits_come_best_score_first_and_ties_keep_their_order() -> None:
    hits = [
        hit(id="a", display_name="Iets met grond"),
        hit(id="b", display_name="Grondwet"),
        hit(id="c", display_name="Grondwet voor het Koninkrijk"),
        hit(id="d", display_name="Nog iets met grond"),
    ]
    ranked = rank_hits("grondwet", hits)
    assert [h["id"] for h in ranked] == ["b", "c", "a", "d"]
    assert [h["score"] for h in ranked] == [
        SCORE_TITLE,
        SCORE_PREFIX,
        SCORE_WORDS,
        SCORE_WORDS,
    ]


@pytest.mark.parametrize(
    ("query", "the_hit", "exact"),
    [
        # what identifies it, or its own whole name
        ("AVG", hit(collection="instruments", extra={"aliases": ["AVG"]}), True),
        ("35925", hit(collection="dossiers", extra={"number": "35925"}), True),
        (
            "kelderluik",
            hit(collection="judgments", extra={"names": ["Kelderluik"]}),
            True,
        ),
        ("mark rutte", hit(collection="members", display_name="Mark Rutte"), True),
        ("VVD", hit(collection="factions", extra={"abbreviation": "VVD"}), True),
        (
            "Financiën",
            hit(collection="ministries", display_name="Financiën"),
            True,
        ),
        # found by its citation or its ECLI: its search says so
        ("art. 6:162 BW", hit(collection="articles", exact=True), True),
        # a heading, the dossier of a paper, a surname, words: no hit that is the thing
        (
            "huurverhoging",
            hit(collection="articles", extra={"heading": "Huurverhoging"}),
            False,
        ),
        (
            "35925",
            hit(collection="documents", extra={"dossier_number": "35925"}),
            False,
        ),
        ("rutte", hit(collection="members", display_name="Mark Rutte"), False),
        (
            "BWBR0001854",
            hit(collection="articles", extra={"bwb_id": "BWBR0001854"}),
            False,
        ),
        (
            "omgevingswet",
            hit(collection="documents", display_name="Omgevingswet"),
            False,
        ),
    ],
)
def test_a_hit_is_exact_when_the_query_names_it(
    query: str, the_hit: dict[str, Any], exact: bool
) -> None:
    assert exact_hit(query, the_hit) is exact


def test_what_no_longer_holds_comes_after_all_that_holds() -> None:
    """A law or article that expired goes after every one in force, whatever its score
    (``stikstof``: art. 2.8 of the Wet natuurbescherming, expired, below the words of a
    law in force); what the query names exactly or identifies goes first still."""
    gone = {"expired_on": "2024-01-01"}
    hits = [
        hit(id="wnb", collection="articles", score=SCORE_TITLE, extra=gone),
        hit(id="ow", collection="articles", score=SCORE_WORDS),
        hit(id="awb", collection="instruments", extra={**gone, "aliases": ["Awb"]}),
        hit(id="ab", collection="instruments", score=SCORE_PREFIX),
    ]
    ranked = rank_hits("awb", hits, today="2026-10-29")
    assert [h["id"] for h in ranked] == ["awb", "ab", "ow", "wnb"]


def test_a_hit_that_has_a_score_keeps_it() -> None:
    ranked = rank_hits("x", [hit(id="a", score=SCORE_IDENTIFIER)])
    assert ranked[0]["score"] == SCORE_IDENTIFIER


# ── The laws behind the citation parser ───────────────────────────────────────


# ── Route-level tests with the search stubbed ─────────────────────────────────


_SR_ART_287 = {
    "id": "articles/bwbr0001854_287",
    "key": "bwbr0001854_287",
    "collection": "articles",
    "type": "article",
    "display_name": "Artikel 287 Wetboek van Strafrecht",
    "snippet": "Tekst ...",
    "extra": {"bwb_id": "BWBR0001854", "article_number": "287"},
    "score": SCORE_IDENTIFIER,
}


@pytest.fixture(autouse=True)
def _cleanup():
    version_cache.clear()
    yield
    version_cache.clear()


@pytest.fixture(autouse=True)
def _no_stop_words(monkeypatch: pytest.MonkeyPatch) -> None:
    """The words of a query as typed: the stop words are the database's."""
    stub_route(
        monkeypatch,
        "search",
        query_words=lambda store, q: QueryWords(tokenize_search_query(q), []),
    )


def test_the_search_route_passes_its_period(monkeypatch: pytest.MonkeyPatch) -> None:
    """``from`` and ``to`` are the period, both days in it; ``from`` after ``to`` is 422."""
    asked: dict[str, Any] = {}

    def search_live(store: Any, **kwargs: Any) -> tuple[dict[str, Any], set[str]]:
        asked.update(kwargs)
        return {}, set()

    stub_route(monkeypatch, "search", signed_of=None, search_live=search_live)
    client = TestClient(app)
    params = {"q": "klimaat", "mode": "live", "from": "2019-01-01", "to": "2019-12-31"}
    assert_status(client.get("/api/search", params=params), 200)
    assert asked["period"] == Period("2019-01-01", "2019-12-31")
    params = {"q": "klimaat", "from": "2020-01-01", "to": "2019-12-31"}
    assert_status(client.get("/api/search", params=params), 422)
    assert_status(client.get("/api/search", params={"q": "x", "from": "2019"}), 422)


def test_the_search_route_passes_its_parameters_and_keeps_the_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, Any] = {}

    def search_full(
        store: Any, **kwargs: Any
    ) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
        asked.update(kwargs)
        weaker = {**_SR_ART_287, "id": "articles/x", "key": "x", "score": SCORE_WORDS}
        return {"articles": [_SR_ART_287, weaker]}, set()

    stub_route(monkeypatch, "search", signed_of=None, search_full=search_full)

    response = TestClient(app).get(
        "/api/search",
        params={"q": "Sr 287", "types": "articles", "kind": "Motie, Brief", "limit": 5},
    )

    assert_status(response, 200)
    assert asked == {
        "q": "Sr 287",
        "types": ["articles"],
        "kinds": ["Motie", "Brief"],
        "limit": 5,
        "period": Period(),
        "signed": None,
        "words": QueryWords(["sr", "287"], []),
        "motion_kinds": None,
    }
    articles = response.json()["results"]["articles"]
    assert [(a["key"], a["score"]) for a in articles] == [
        ("bwbr0001854_287", SCORE_IDENTIFIER),
        ("x", SCORE_WORDS),
    ]
    assert articles[0]["extra"]["article_number"] == "287"


def test_search_resolves_q_in_the_same_request_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved: dict[str, Any] = {
        "kind": "instrument",
        "confidence": 0.9,
        "match": {
            "id": "instruments/32016r0679",
            "key": "32016r0679",
            "collection": "instruments",
            "kind": "instrument",
            "display_name": "AVG",
            "title": "Algemene verordening gegevensbescherming",
            "confidence": 0.9,
            "expired_on": None,
        },
        "alternatives": [],
        "alternatives_total": 0,
        "qualifier": None,
        "notation": None,
    }
    asked: list[str] = []

    def resolve_query(store: Any, q: str) -> dict[str, Any]:
        asked.append(q)
        return resolved

    stub_route(
        monkeypatch,
        "search",
        signed_of=None,
        search_full=({}, set()),
        resolve_query=resolve_query,
        kept_notation_parser=lambda store, wait: object(),
    )
    client = TestClient(app)

    body = client.get("/api/search", params={"q": "AVG", "resolve": "true"}).json()
    match = {**resolved["match"], "path": "/wetten/32016R0679"}
    assert body["resolved"] == {"q": "AVG", **resolved, "match": match}
    # without it nothing is resolved
    assert client.get("/api/search", params={"q": "AVG"}).json()["resolved"] is None
    assert asked == ["AVG"]


def test_a_query_is_at_most_as_long_as_resolve_takes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``q`` of more than ``RESOLVE_MAX_LENGTH`` characters is 422, before the search."""
    stub_route(monkeypatch, "search", signed_of=None, search_full=({}, set()))
    client = TestClient(app)
    longest = "w" * RESOLVE_MAX_LENGTH
    assert_status(client.get("/api/search", params={"q": longest}), 200)
    longer = longest + "w"
    assert_status(client.get("/api/search", params={"q": longer}), 422)


def test_an_unknown_type_is_refused_before_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_route(
        monkeypatch,
        "search",
        search_full=lambda store, **kwargs: pytest.fail("searched"),
    )
    response = TestClient(app).get("/api/search", params={"q": "x", "types": "nope"})
    assert response.status_code == 422, response.text


def test_the_answer_says_what_each_type_is_searched_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``searched``: per type asked, the fields its search reads and its text ``none``
    when it has one the search does not read, so no hit does not read as "not there"."""
    stub_route(monkeypatch, "search", signed_of=None, search_live=({}, set()))
    body = (
        TestClient(app)
        .get(
            "/api/search",
            params={"q": "huur", "mode": "live", "types": ["documents", "articles"]},
        )
        .json()
    )
    assert body["searched"] == {
        "documents": {
            "fields": ["title", "number"],
            "completeness": {
                "text": {
                    "state": "none",
                    "as_of": None,
                    "missing": None,
                    "reason": None,
                }
            },
            "signed_for": [],
        },
        "articles": {
            "fields": ["title", "number", "text"],
            "completeness": {
                "text": {
                    "state": "done",
                    "as_of": None,
                    "missing": None,
                    "reason": None,
                }
            },
            "signed_for": [],
        },
    }


# ── /api/resolve ──────────────────────────────────────────────────────────────


def test_resolve_is_in_the_schema_with_its_answer_typed() -> None:
    spec = app.openapi()
    operation = spec["paths"]["/api/resolve"]["get"]
    assert "resolve" in operation["tags"] and operation["summary"]
    schemas = spec["components"]["schemas"]
    assert set(schemas["ResolveResponse"]["properties"]) == {
        "q",
        "kind",
        "confidence",
        "match",
        "alternatives",
        "alternatives_total",
        "qualifier",
        "notation",
    }
    assert set(schemas["ResolveMatch"]["properties"]) == {
        "id",
        "key",
        "collection",
        "kind",
        "display_name",
        "title",
        "confidence",
        "expired_on",
        "path",
    }
    q = next(p for p in operation["parameters"] if p["name"] == "q")
    assert q["required"] and q["schema"]["maxLength"] == 200


def test_resolve_answers_no_match_with_200_and_a_citation_with_its_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    match = {
        "id": "articles/bwbr0005289_162",
        "key": "bwbr0005289_162",
        "collection": "articles",
        "kind": "article",
        "display_name": "Artikel 162",
        "confidence": 0.95,
    }
    answers = {
        "art. 6:162 BW": {
            "kind": "article",
            "confidence": 0.95,
            "match": match,
            "alternatives": [],
            "alternatives_total": 0,
            "qualifier": None,
        },
        "zzzz onbekend": dict(NO_MATCH),
    }
    stub_route(monkeypatch, "resolve", resolve_query=lambda store, q: answers[q])
    client = TestClient(app)

    found = client.get("/api/resolve", params={"q": "art. 6:162 BW"})
    assert_status(found, 200)
    body = found.json()
    assert (body["kind"], body["match"]["id"]) == (
        "article",
        "articles/bwbr0005289_162",
    )
    assert body["confidence"] == 0.95 and body["alternatives"] == []

    nothing = client.get("/api/resolve", params={"q": "zzzz onbekend"})
    assert_status(nothing, 200)
    assert nothing.json() == {
        "q": "zzzz onbekend",
        "kind": "none",
        "confidence": 0.0,
        "match": None,
        "alternatives": [],
        "alternatives_total": 0,
        "qualifier": None,
        "notation": None,
    }
    assert_status(client.get("/api/resolve", params={"q": ""}), 422)


def test_a_resolve_answer_says_how_many_alternatives_it_found() -> None:
    """``alternatives_total`` in every answer; a choice has no ``match``."""
    from lawgraph.api.schemas.resolve import ResolveResponse

    choice = ResolveResponse(
        q="art. 3 BW",
        kind="article",
        confidence=0.5,
        match=None,
        alternatives=[],
        alternatives_total=9,
        qualifier=None,
    )
    assert choice.model_dump()["alternatives_total"] == 9
    assert (
        ResolveResponse(
            q="x", kind="none", confidence=0, match=None, alternatives=[]
        ).alternatives_total
        == 0
    )


def test_a_search_says_which_types_it_cut_off(monkeypatch) -> None:
    """``partial`` names the types cut off: of a live search at its budget, of the full
    search those that answered their live hits."""
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.routes import search as route

    monkeypatch.setattr(
        route,
        "search_live",
        lambda store, **k: ({"judgments": [], "articles": []}, {"judgments"}),
    )
    monkeypatch.setattr(
        route,
        "search_full",
        lambda store, **k: ({"judgments": [], "articles": []}, {"judgments"}),
    )
    client = TestClient(app)
    live = client.get(
        "/api/search",
        params={"q": "huur", "mode": "live", "types": ["judgments", "articles"]},
    )
    assert_status(live, 200)
    assert live.json()["partial"] == {"judgments": True}
    full = client.get("/api/search", params={"q": "huur", "types": ["articles"]})
    assert_status(full, 200)
    assert full.json()["partial"] == {"judgments": True}
    assert_status(client.get("/api/search", params={"q": "huur", "mode": "x"}), 422)


def test_an_article_hit_is_named_as_it_is_cited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = {
        **_SR_ART_287,
        "display_name": "Artikel 162 Burgerlijk Wetboek Boek 6",
        "extra": {
            "bwb_id": "BWBR0005289",
            "article_number": "162",
            "citation_title": "Burgerlijk Wetboek Boek 6",
        },
    }

    def search_full(store: Any, **kwargs: Any) -> tuple[dict[str, Any], set[str]]:
        return {"articles": [article]}, set()

    stub_route(monkeypatch, "search", signed_of=None, search_full=search_full)
    results = TestClient(app).get("/api/search", params={"q": "x"}).json()["results"]
    assert results["articles"][0]["display_name"] == "Art. 6:162 BW"


def test_a_judgment_hit_has_its_cite_and_a_paper_its_dossier_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judgment = {
        "id": "judgments/ecli_eu_c_2023_492",
        "key": "ecli_eu_c_2023_492",
        "collection": "judgments",
        "type": "judgment",
        "display_name": "HvJ EU, C-160/20",
        "extra": {"ecli": "ECLI:EU:C:2023:492", "appno": None, "names": None},
        "cite_props": {
            "date": "2023-06-22",
            "court": "Hof van Justitie van de Europese Unie",
            "case_number": "C-160/20",
        },
        "score": SCORE_WORDS,
    }
    paper = {
        "id": "documents/d",
        "key": "d",
        "collection": "documents",
        "type": "document",
        "display_name": "Memorie van toelichting",
        "extra": {"dossier_number": "36000", "sequence": 3},
        "score": SCORE_WORDS,
    }

    def search_full(store: Any, **kwargs: Any) -> tuple[dict[str, Any], set[str]]:
        return {"judgments": [judgment], "documents": [paper]}, set()

    stub_route(monkeypatch, "search", signed_of=None, search_full=search_full)
    results = TestClient(app).get("/api/search", params={"q": "x"}).json()["results"]
    (found,) = results["judgments"]
    assert found["extra"]["cite"] == {
        "short": "HvJ EU 22 juni 2023, C-160/20",
        "full": "HvJ EU 22 juni 2023, C-160/20, ECLI:EU:C:2023:492",
    }
    assert "cite_props" not in found
    assert results["documents"][0]["extra"]["dossier_short_title"] == (
        "Wet beter voorbeeld"
    )


def _item(key: str, collection: str, score: float, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"{collection}/{key}",
        "key": key,
        "collection": collection,
        "type": collection.rstrip("s"),
        "display_name": key,
        "extra": extra,
        "score": score,
    }


def test_best_is_the_one_hit_the_query_names_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``best``: the one ``exact`` hit; none when only words match ("huurtoeslag": an
    article whose heading it is) or when several are exact ("BW": every book)."""
    found: dict[str, list[dict[str, Any]]] = {}
    stub_route(
        monkeypatch,
        "search",
        signed_of=None,
        search_full=lambda store, **kwargs: ({**found}, set()),
    )
    client = TestClient(app)

    found["articles"] = [_item("ix", "articles", SCORE_TITLE, heading="huurtoeslag")]
    found["documents"] = [_item("d", "documents", SCORE_CONTAINS)]
    body = client.get("/api/search", params={"q": "huurtoeslag"}).json()
    assert body["best"] is None
    assert [h["exact"] for h in body["results"]["articles"]] == [False]

    found["instruments"] = [_item("awb", "instruments", SCORE_TITLE, aliases=["Awb"])]
    body = client.get("/api/search", params={"q": "Awb"}).json()
    assert body["best"] == "instruments/awb"

    found["instruments"] = [
        _item(f"bw{book}", "instruments", SCORE_TITLE, aliases=["BW"])
        for book in (1, 6)
    ]
    assert client.get("/api/search", params={"q": "BW"}).json()["best"] is None

    # a ministry named exactly, before the committee for it
    found.clear()
    found["committees"] = [_item("bzk", "committees", 1.0, abbreviation="BZK")]
    body = client.get("/api/search", params={"q": "BZK"}).json()
    assert body["best"] == "committees/bzk"
    found["ministries"] = [_item("bzk", "ministries", 1.0, abbreviation="BZK")]
    body = client.get("/api/search", params={"q": "BZK"}).json()
    assert body["best"] == "ministries/bzk"


def test_best_is_the_match_of_the_resolver_when_it_is_sure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    match = {
        "id": "articles/bwbr0001840_1",
        "key": "bwbr0001840_1",
        "collection": "articles",
        "kind": "article",
        "display_name": "Art. 1 Gw",
        "title": "Art. 1 Gw",
    }
    answers = {"Grondwet artikel 1": 0.95, "grondwet": 0.6}

    def resolve_query(store: Any, q: str) -> dict[str, Any]:
        confidence = answers[q]
        return {
            **NO_MATCH,
            "kind": "article",
            "confidence": confidence,
            "match": {**match, "confidence": confidence},
        }

    stub_route(
        monkeypatch,
        "search",
        signed_of=None,
        search_full=({}, set()),
        resolve_query=resolve_query,
        kept_notation_parser=lambda store, wait: object(),
    )
    client = TestClient(app)
    for q, best in (("Grondwet artikel 1", match["id"]), ("grondwet", None)):
        body = client.get("/api/search", params={"q": q, "resolve": "true"}).json()
        assert body["best"] == best, q


def test_no_hit_of_every_word_answers_those_of_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a hit that holds every word, the hits of one at least, ``matched`` ``any``;
    the stop words are left out first and said in ``left_out``."""
    asked: list[bool] = []

    def search_full(store: Any, **kwargs: Any) -> tuple[dict[str, Any], set[str]]:
        asked.append(kwargs.get("any_word", False))
        if not kwargs.get("any_word"):
            return {"articles": []}, set()
        return {"articles": [_item("271", "articles", SCORE_WORDS)]}, set()

    stub_route(
        monkeypatch,
        "search",
        signed_of=None,
        search_full=search_full,
        query_words=lambda store, q: QueryWords(
            ["opzegtermijn", "huurcontract"], ["wat", "is", "de", "van", "mijn"]
        ),
        concept_named=lambda q, words: None,  # no term of the list of concepts
    )
    body = (
        TestClient(app)
        .get(
            "/api/search", params={"q": "wat is de opzegtermijn van mijn huurcontract"}
        )
        .json()
    )
    assert asked == [False, True]
    assert body["matched"] == "any"
    assert body["words"] == ["opzegtermijn", "huurcontract"]
    assert body["left_out"] == ["wat", "is", "de", "van", "mijn"]
    assert [h["key"] for h in body["results"]["articles"]] == ["271"]

    # one word: nothing is nothing
    asked.clear()
    stub_route(
        monkeypatch,
        "search",
        query_words=lambda store, q: QueryWords(["huurcontract"], []),
    )
    body = TestClient(app).get("/api/search", params={"q": "huurcontract"}).json()
    assert asked == [False]
    assert (body["matched"], body["total"]) == ("all", 0)
