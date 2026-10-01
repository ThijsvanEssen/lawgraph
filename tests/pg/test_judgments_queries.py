"""The judgment queries on a real PostgreSQL: the list with its facets, a judgment with
its articles, the judgments it cites and its series."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore
from lawgraph.db.queries import judgments as judgment_queries
from lawgraph.db.queries.judgments import JudgmentFilters, get_judgments_list

HR1 = "ECLI:NL:HR:2020:1"
HR10 = "ECLI:NL:HR:2020:10"
RB = "ECLI:NL:RBAMS:2019:7"
STUB = "ECLI:NL:HR:2001:1"
COPY = "ECLI:NL:PHR:2020:1"
ECHR = "001-123"


def _key(ecli: str) -> str:
    return make_node_key(ecli)


def _jid(ecli: str) -> str:
    return f"judgments/{_key(ecli)}"


def _judgment(name: str, **props: Any) -> dict[str, Any]:
    return {"_key": _key(name), "type": "judgment", "labels": [], "props": props}


def _edge(key: str, source: str, target: str, relation: str, **rest: Any) -> dict:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "status": "canoniek",
        **rest,
    }


@pytest.fixture()
def corpus(store: ArangoStore) -> ArangoStore:
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _judgment(
                HR1,
                ecli=HR1,
                display_name="HR 1",
                date_eff="2020-05-01",
                tier="hoogste",
                court_kind="civiel",
                court_code="HR",
                source="rechtspraak",
                subjects=["Civiel recht"],
                inbound_citation_count=5,
                outbound_citation_count=2,
                series_id="s1",
                series_size=2,
            ),
            _judgment(
                HR10,
                ecli=HR10,
                display_name="HR 10",
                date_eff="2020-05-01",
                tier="hoogste",
                court_kind="civiel",
                court_code="HR",
                source="rechtspraak",
                subjects=["Civiel recht", "Strafrecht"],
                inbound_citation_count=9,
                series_id="s1",
            ),
            _judgment(
                RB,
                ecli=RB,
                display_name="Rb 7",
                date_eff="2019-02-03",
                tier="rechtbank",
                court_kind="straf",
                court_code="RBAMS",
                source="rechtspraak",
                subjects=["Strafrecht"],
                case_number_keys=["18/04298", "c/19/117301"],
            ),
            _judgment(STUB, ecli=STUB, stub=True),
            _judgment(
                COPY,
                ecli=COPY,
                date_eff="2021-01-01",
                tier="hoogste",
                source="rechtspraak",
                same_as=_jid(HR1),
            ),
            # an ECHR decision without an ECLI or a date
            _judgment(ECHR, display_name="X v. NL", source="echr", tier="ehrm"),
        ],
    )
    return store


def _ids(result: dict[str, Any]) -> list[str]:
    return [item["_id"] for item in result["items"]]


def test_the_list_unfiltered_newest_first_with_the_key_settling_ties(
    corpus: ArangoStore,
) -> None:
    result = get_judgments_list(corpus)
    assert list(result) == ["total", "items", "facets"]
    # the stub and the replaced publication are left out; the undated ECHR one comes last
    assert _ids(result) == [_jid(HR10), _jid(HR1), _jid(RB), _jid(ECHR)]
    assert result["total"] == 4
    first = result["items"][1]
    assert first == {
        "_id": _jid(HR1),
        "_key": _key(HR1),
        "ecli": HR1,
        "display_name": "HR 1",
        "summary": None,
        "names": None,
        "decision_kind": None,
        "court_code": "HR",
        "tier": "hoogste",
        "court_kind": "civiel",
        "date": "2020-05-01",
        "source": "rechtspraak",
        "subjects": ["Civiel recht"],
        "inbound_citation_count": 5,
        "outbound_citation_count": 2,
        "series_id": "s1",
        "series_size": 2,
    }
    assert list(first)[:4] == ["_id", "_key", "ecli", "display_name"]  # as AQL RETURNed
    assert list(first)[-3:] == ["outbound_citation_count", "series_id", "series_size"]
    # a judgment without an ECLI shows its key
    assert result["items"][3]["ecli"] == _key(ECHR)
    assert result["items"][3]["date"] is None


def test_the_facets_by_count_then_value_and_the_years_by_year(
    corpus: ArangoStore,
) -> None:
    facets = get_judgments_list(corpus)["facets"]
    assert list(facets) == ["tier", "court_kind", "source", "year"]
    assert facets["tier"] == [
        {"value": "hoogste", "count": 2},
        {"value": "ehrm", "count": 1},
        {"value": "rechtbank", "count": 1},
    ]
    # a count tie: null sorts first
    assert facets["court_kind"] == [
        {"value": "civiel", "count": 2},
        {"value": None, "count": 1},
        {"value": "straf", "count": 1},
    ]
    assert facets["source"] == [
        {"value": "rechtspraak", "count": 3},
        {"value": "echr", "count": 1},
    ]
    assert facets["year"] == [
        {"value": None, "count": 1},
        {"value": "2019", "count": 1},
        {"value": "2020", "count": 2},
    ]


def test_each_facet_leaves_its_own_filter_out(corpus: ArangoStore) -> None:
    result = get_judgments_list(
        corpus, JudgmentFilters(tier="hoogste", court_kind="civiel")
    )
    assert _ids(result) == [_jid(HR10), _jid(HR1)]
    assert result["total"] == 2
    facets = result["facets"]
    # tier drops tier and court_kind; court_kind drops court_kind only
    assert [f["value"] for f in facets["tier"]] == ["hoogste", "ehrm", "rechtbank"]
    assert facets["court_kind"] == [{"value": "civiel", "count": 2}]
    assert facets["source"] == [{"value": "rechtspraak", "count": 2}]

    years = get_judgments_list(corpus, JudgmentFilters(date_from="2020-01-01"))
    assert _ids(years) == [_jid(HR10), _jid(HR1)]  # no date is not after a date
    assert [f["value"] for f in years["facets"]["year"]] == [None, "2019", "2020"]
    assert years["facets"]["tier"] == [{"value": "hoogste", "count": 2}]


def test_the_filters(corpus: ArangoStore) -> None:
    def ids(**kw: Any) -> list[str]:
        return _ids(get_judgments_list(corpus, JudgmentFilters(**kw)))

    assert ids(court="rbams") == [_jid(RB)]
    assert ids(source="echr") == [_jid(ECHR)]
    assert ids(subject="Strafrecht") == [_jid(HR10), _jid(RB)]
    assert ids(date_to="2019-12-31") == [_jid(RB)]
    assert ids(date_from="2019-01-01", date_to="2020-05-01") == [
        _jid(HR10),
        _jid(HR1),
        _jid(RB),
    ]
    # a judgment without a count is not cited at least once
    assert ids(cited_by_min=6) == [_jid(HR10)]
    assert ids(cited_by_min=0) == [_jid(HR10), _jid(HR1)]
    with_stubs = get_judgments_list(corpus, JudgmentFilters(include_stubs=True))
    # two undated: the key, descending
    assert _ids(with_stubs) == [_jid(HR10), _jid(HR1), _jid(RB), _jid(STUB), _jid(ECHR)]
    assert with_stubs["total"] == 5


def test_the_sorts_and_paging(corpus: ArangoStore) -> None:
    asc = get_judgments_list(corpus, sort="date_asc")
    assert _ids(asc) == [_jid(ECHR), _jid(RB), _jid(HR1), _jid(HR10)]
    cited = get_judgments_list(corpus, sort="citation_count")
    # no count sorts last; among those the key, descending
    assert _ids(cited) == [_jid(HR10), _jid(HR1), _jid(RB), _jid(ECHR)]
    page = get_judgments_list(corpus, limit=2, offset=1)
    assert _ids(page) == [_jid(HR1), _jid(RB)]
    assert page["total"] == 4
    assert get_judgments_list(corpus, limit=2, offset=10)["items"] == []


def test_a_query_that_is_an_ecli_or_a_case_number(corpus: ArangoStore) -> None:
    # the exact ECLI also finds a replaced publication
    found = get_judgments_list(corpus, JudgmentFilters(q=COPY.lower()))
    assert _ids(found) == [_jid(COPY)]
    assert found["total"] == 1
    by_number = get_judgments_list(corpus, JudgmentFilters(q="18/04298"))
    assert _ids(by_number) == [_jid(RB)]
    assert by_number["facets"]["tier"] == [{"value": "rechtbank", "count": 1}]


def test_the_unfiltered_total_takes_a_replaced_stub_off_twice(
    corpus: ArangoStore,
) -> None:
    corpus.bulk_insert_or_update_nodes(
        "judgments",
        [_judgment("ECLI:NL:HR:2002:2", stub=True, same_as=_jid(STUB))],
    )
    result = get_judgments_list(corpus)
    assert len(result["items"]) == 4
    assert result["total"] == 3  # 7 - 2 stubs - 2 replaced, as COLLECTION_COUNT did
    assert get_judgments_list(corpus, JudgmentFilters(tier="hoogste"))["total"] == 2


def test_an_empty_table(store: ArangoStore) -> None:
    assert get_judgments_list(store) == {
        "total": 0,
        "items": [],
        "facets": {"tier": [], "court_kind": [], "source": [], "year": []},
    }


@pytest.fixture()
def detail(corpus: ArangoStore) -> ArangoStore:
    corpus.bulk_insert_or_update_nodes(
        "articles",
        [
            {"_key": k, "type": "article", "labels": [], "props": {"n": k}}
            for k in ("BWBR1_1", "BWBR1_2", "BWBR2_1")
        ],
    )
    corpus.bulk_insert_or_update_nodes(
        "instruments",
        [
            {"_key": k, "type": "instrument", "labels": [], "props": {"bwb_id": k}}
            for k in ("BWBR1", "BWBR2")
        ],
    )
    hr1 = _jid(HR1)
    corpus.bulk_insert_or_update_edges(
        [
            _edge(
                "r2",
                hr1,
                "articles/BWBR1_2",
                "REFERS_TO",
                confidence=0.9,
                meta={"mentions": ["art. 2"], "mention_count": 1},
            ),
            _edge("r1", hr1, "articles/BWBR1_1", "REFERS_TO", confidence=1),
            _edge("r0", hr1, "articles/BWBR2_1", "REFERS_TO"),
            _edge("rx", hr1, "articles/gone", "REFERS_TO"),
            _edge("p1", "articles/BWBR1_1", "instruments/BWBR1", "PART_OF"),
            _edge("p2", "articles/BWBR1_2", "instruments/BWBR1", "PART_OF"),
            # the first PART_OF by target is gone: no instrument, as DOCUMENT gave null
            _edge("p3", "articles/BWBR2_1", "instruments/AAA", "PART_OF"),
            _edge("p4", "articles/BWBR2_1", "instruments/BWBR2", "PART_OF"),
            # cited judgments, and one that is not a judgment
            _edge("c1", hr1, _jid(RB), "REFERS_TO"),
            _edge("c2", hr1, _jid(HR10), "REFERS_TO"),
            _edge("c3", hr1, _jid(ECHR), "REFERS_TO"),
            _edge("c4", hr1, _jid("ECLI:NL:XX:1:1"), "REFERS_TO"),
            # SAME_AS both ways
            _edge("s1", _jid(COPY), hr1, "SAME_AS"),
            _edge("s2", hr1, _jid(RB), "SAME_AS"),
        ]
    )
    return corpus


def test_a_judgment_with_its_articles(detail: ArangoStore) -> None:
    data = judgment_queries.get_judgment_with_relations(detail, HR1.lower())
    assert data.judgment["_id"] == _jid(HR1)
    assert [a.article["_id"] for a in data.articles] == [
        "articles/BWBR1_1",
        "articles/BWBR1_2",
        "articles/BWBR2_1",
    ]
    first, second, third = data.articles
    assert first.article == {
        "_key": "BWBR1_1",
        "_id": "articles/BWBR1_1",
        "type": "article",
        "labels": [],
        "props": {"n": "BWBR1_1"},
    }
    assert (
        first.instrument is not None and first.instrument["_id"] == "instruments/BWBR1"
    )
    assert (first.confidence, first.meta) == (1, {})
    assert isinstance(first.confidence, int)
    assert second.confidence == 0.9
    assert second.meta == {"mentions": ["art. 2"], "mention_count": 1}
    assert third.instrument is None and third.confidence is None
    assert data.metadata == {"article_count": 3}


def test_the_judgments_it_cites_and_the_same_decision(detail: ArangoStore) -> None:
    data = judgment_queries.get_judgment_with_relations(detail, HR1)
    assert data.cited_judgments == [
        {
            "_id": _jid(HR10),
            "_key": _key(HR10),
            "props": {"display_name": "HR 10", "ecli": HR10},
        },
        {
            "_id": _jid(RB),
            "_key": _key(RB),
            "props": {"display_name": "Rb 7", "ecli": RB},
        },
        # no date sorts last; a missing ECLI is null
        {
            "_id": _jid(ECHR),
            "_key": _key(ECHR),
            "props": {"display_name": "X v. NL", "ecli": None},
        },
    ]
    assert [j["_id"] for j in data.same_as] == [_jid(COPY), _jid(RB)]
    assert data.same_as[0]["props"] == {"display_name": None, "ecli": COPY}


def test_the_series_by_ecli_number(detail: ArangoStore) -> None:
    detail.bulk_insert_or_update_nodes(
        "judgments",
        [
            _judgment("ECLI:NL:HR:2020:2", ecli="ECLI:NL:HR:2020:2", series_id="s1"),
            # no ECLI: length 0, first; and no display name: the key is left out
            _judgment("zzz", series_id="s1", other="x"),
        ],
    )
    members = judgment_queries.get_series_members(detail, "s1")
    assert members == [
        {"_id": "judgments/zzz", "_key": "zzz", "props": {}},
        {
            "_id": _jid(HR1),
            "_key": _key(HR1),
            "props": {"ecli": HR1, "display_name": "HR 1"},
        },
        {
            "_id": _jid("ECLI:NL:HR:2020:2"),
            "_key": _key("ECLI:NL:HR:2020:2"),
            "props": {"ecli": "ECLI:NL:HR:2020:2"},
        },
        {
            "_id": _jid(HR10),
            "_key": _key(HR10),
            "props": {"ecli": HR10, "display_name": "HR 10"},
        },
    ]
    # the order of its props, as KEEP kept it
    assert list(members[1]["props"]) == ["ecli", "display_name"]
    data = judgment_queries.get_judgment_with_relations(detail, HR1)
    assert [j["_id"] for j in data.series] == [
        "judgments/zzz",
        _jid("ECLI:NL:HR:2020:2"),
        _jid(HR10),
    ]
    assert judgment_queries.get_judgment_with_relations(detail, RB).series == []


def test_an_unknown_judgment(detail: ArangoStore) -> None:
    with pytest.raises(ValueError, match="judgment not found"):
        judgment_queries.get_judgment_with_relations(detail, "ECLI:NL:XX:0000:0")
