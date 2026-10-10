"""The judgment queries on a real PostgreSQL: the list with its facets, a judgment with
its articles, the judgments it cites and its series."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, version_cache
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
def corpus(store: GraphStore) -> GraphStore:
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
                judgment_metadata={"type": "Cassatie", "court": "Hoge Raad"},
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
                judgment_metadata={"type": "Cassatie"},
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
                judgment_metadata={"type": "Eerste aanleg - meervoudig"},
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
    corpus: GraphStore,
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
    corpus: GraphStore,
) -> None:
    facets = get_judgments_list(corpus)["facets"]
    assert list(facets) == [
        "tier",
        "court_kind",
        "source",
        "year",
        "subjects",
        "subject_area",
        "procedure",
    ]
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


def test_each_facet_leaves_its_own_filter_out(corpus: GraphStore) -> None:
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


def test_the_filters(corpus: GraphStore) -> None:
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


def test_the_sorts_and_paging(corpus: GraphStore) -> None:
    asc = get_judgments_list(corpus, sort="date_asc")
    assert _ids(asc) == [_jid(ECHR), _jid(RB), _jid(HR1), _jid(HR10)]
    cited = get_judgments_list(corpus, sort="citation_count")
    # no count sorts last; among those the key, descending
    assert _ids(cited) == [_jid(HR10), _jid(HR1), _jid(RB), _jid(ECHR)]
    page = get_judgments_list(corpus, limit=2, offset=1)
    assert _ids(page) == [_jid(HR1), _jid(RB)]
    assert page["total"] == 4
    assert get_judgments_list(corpus, limit=2, offset=10)["items"] == []


def test_a_query_that_is_an_ecli_or_a_case_number(corpus: GraphStore) -> None:
    # the exact ECLI also finds a replaced publication
    found = get_judgments_list(corpus, JudgmentFilters(q=COPY.lower()))
    assert _ids(found) == [_jid(COPY)]
    assert found["total"] == 1
    by_number = get_judgments_list(corpus, JudgmentFilters(q="18/04298"))
    assert _ids(by_number) == [_jid(RB)]
    assert by_number["facets"]["tier"] == [{"value": "rechtbank", "count": 1}]


def test_the_unfiltered_total_takes_a_replaced_stub_off_twice(
    corpus: GraphStore,
) -> None:
    corpus.bulk_insert_or_update_nodes(
        "judgments",
        [_judgment("ECLI:NL:HR:2002:2", stub=True, same_as=_jid(STUB))],
    )
    result = get_judgments_list(corpus)
    assert len(result["items"]) == 4
    assert result["total"] == 3  # 7 - 2 stubs - 2 replaced, as COLLECTION_COUNT did
    assert get_judgments_list(corpus, JudgmentFilters(tier="hoogste"))["total"] == 2


def test_an_empty_table(store: GraphStore) -> None:
    assert get_judgments_list(store) == {
        "total": 0,
        "items": [],
        "facets": {
            "tier": [],
            "court_kind": [],
            "source": [],
            "year": [],
            "subjects": [],
            "subject_area": [],
            "procedure": [],
        },
    }


@pytest.fixture()
def detail(corpus: GraphStore) -> GraphStore:
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


def test_a_judgment_with_its_articles(detail: GraphStore) -> None:
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


def test_the_judgments_it_cites_and_the_same_decision(detail: GraphStore) -> None:
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


def test_a_connected_case_carries_the_sentence_that_names_it(
    detail: GraphStore,
) -> None:
    named = {"basis": "summary_text", "text": "Samenhang met ECLI:NL:RBAMS:2019:7"}
    names_back = {"basis": "summary_text", "text": "Zie ook: ECLI:NL:HR:2020:1"}
    detail.bulk_insert_or_update_edges(
        [
            _edge("rel1", _jid(HR1), _jid(RB), "RELATED_TO", meta=named),
            _edge("rel2", _jid(RB), _jid(HR1), "RELATED_TO", meta=names_back),
            _edge("rel3", _jid(HR10), _jid(HR1), "RELATED_TO", meta=names_back),
        ]
    )
    data = judgment_queries.get_judgment_with_relations(detail, HR1)
    links = {j["_id"]: j["links"] for j in data.related_to}
    # each case once, with an edge each way: its own summary first
    assert links == {
        _jid(HR10): [{"direction": "inbound", **names_back}],
        _jid(RB): [
            {"direction": "outbound", **named},
            {"direction": "inbound", **names_back},
        ],
    }
    assert [j["_id"] for j in data.related_to] == [_jid(HR10), _jid(RB)]


def test_its_conclusions_named_as_their_light_nodes_name_them(
    detail: GraphStore,
) -> None:
    """``conclusions``: per ECLI of ``conclusion_eclis``, in its order, the A-G (or P-G)
    and the date its light node gives (``lg_judgment_light``), as the front end names the
    conclusion; one the graph lacks is its ECLI alone."""
    phr = "ECLI:NL:PHR:2019:887"
    gone = "ECLI:NL:PHR:2019:999"
    detail.bulk_insert_or_update_nodes(
        "judgments",
        [
            _judgment(
                phr,
                ecli=phr,
                date="2019-09-13",
                advocate_general="Langemeijer en Wissink",
                advocate_general_role="procureur-generaal",
                text="De conclusie, die niet gelezen wordt.",
            ),
            _judgment(HR10, ecli=HR10, conclusion_eclis=[gone, phr]),
        ],
    )

    data = judgment_queries.get_judgment_with_relations(detail, HR10)

    assert data.conclusions == [
        {"ecli": gone, "author": None, "role": None, "date": None},
        {
            "ecli": phr,
            "author": "Langemeijer en Wissink",
            "role": "procureur-generaal",
            "date": "2019-09-13",
        },
    ]
    assert judgment_queries.get_judgment_with_relations(detail, HR1).conclusions == []


def test_the_series_by_ecli_number(detail: GraphStore) -> None:
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


def test_an_unknown_judgment(detail: GraphStore) -> None:
    with pytest.raises(ValueError, match="judgment not found"):
        judgment_queries.get_judgment_with_relations(detail, "ECLI:NL:XX:0000:0")


def test_the_areas_of_law_and_the_procedures_are_counted_and_filtered(
    corpus: GraphStore,
) -> None:
    """BE-44: a judgment counts for each of its areas of law; the procedure is the
    ``psi:procedure`` of its metadata as written; each facet leaves its own filter out."""
    facets = get_judgments_list(corpus)["facets"]
    assert facets["subjects"] == [
        {"value": "Civiel recht", "count": 2},
        {"value": "Strafrecht", "count": 2},
    ]
    assert facets["procedure"] == [
        {"value": "Cassatie", "count": 2},
        {"value": None, "count": 1},  # the ECHR decision: no metadata
        {"value": "Eerste aanleg - meervoudig", "count": 1},
    ]
    cassatie = get_judgments_list(corpus, JudgmentFilters(procedure="Cassatie"))
    assert _ids(cassatie) == [_jid(HR10), _jid(HR1)]
    assert [f["value"] for f in cassatie["facets"]["procedure"]][:1] == ["Cassatie"]
    assert len(cassatie["facets"]["procedure"]) == 3  # without its own filter
    assert cassatie["facets"]["subjects"] == [
        {"value": "Civiel recht", "count": 2},
        {"value": "Strafrecht", "count": 1},
    ]
    straf = get_judgments_list(corpus, JudgmentFilters(subject="Strafrecht"))
    assert {f["value"] for f in straf["facets"]["subjects"]} == {
        "Civiel recht",
        "Strafrecht",
    }
    assert straf["facets"]["procedure"] == [
        {"value": "Cassatie", "count": 1},
        {"value": "Eerste aanleg - meervoudig", "count": 1},
    ]


def test_the_main_areas_of_law_hold_their_subjects(store: GraphStore) -> None:
    """BE-57: ``subject_area`` is a subject up to its first ';'. A judgment counts once for
    each of its main areas, however many of its subjects are in one; the facet leaves its
    own filter out, and the exact ``subject`` still matches the whole subject."""

    def judgment(key: str, date: str, *subjects: str) -> dict[str, Any]:
        return {
            "_key": key,
            "type": "judgment",
            "labels": [],
            "props": {"ecli": key, "date_eff": date, "subjects": list(subjects)},
        }

    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            judgment("b1", "2026-01-03", "Bestuursrecht"),
            judgment("b2", "2026-01-02", "Bestuursrecht; Belastingrecht"),
            judgment(
                "b3",
                "2026-01-01",
                "Bestuursrecht; Omgevingsrecht",
                "Bestuursrecht; Ruimtelijk bestuursrecht",
                "Civiel recht; Verbintenissenrecht",
            ),
            judgment("c1", "2025-12-31", "Civiel recht"),
            judgment("none", "2025-12-30"),
        ],
    )

    def ids(**kw: Any) -> list[str]:
        return _ids(get_judgments_list(store, JudgmentFilters(**kw)))

    assert ids(subject_area="Bestuursrecht") == [
        "judgments/b1",
        "judgments/b2",
        "judgments/b3",
    ]
    assert ids(subject="Bestuursrecht") == ["judgments/b1"]
    assert ids(subject_area="Civiel recht") == ["judgments/b3", "judgments/c1"]
    assert ids(subject_area="Belastingrecht") == []  # a sub-area is no main area
    found = get_judgments_list(store, JudgmentFilters(subject_area="Civiel recht"))
    assert found["total"] == 2
    # counted without its own filter: every main area, a judgment once in each
    assert found["facets"]["subject_area"] == [
        {
            "value": "Bestuursrecht",
            "count": 3,
            # the subjects of the source under it, without the area and subject filters
            "narrower": [
                {
                    "value": "Bestuursrecht; Belastingrecht",
                    "label": "Belastingrecht",
                    "count": 1,
                },
                {
                    "value": "Bestuursrecht; Omgevingsrecht",
                    "label": "Omgevingsrecht",
                    "count": 1,
                },
                {
                    "value": "Bestuursrecht; Ruimtelijk bestuursrecht",
                    "label": "Ruimtelijk bestuursrecht",
                    "count": 1,
                },
            ],
        },
        {
            "value": "Civiel recht",
            "count": 2,
            "narrower": [
                {
                    "value": "Civiel recht; Verbintenissenrecht",
                    "label": "Verbintenissenrecht",
                    "count": 1,
                },
            ],
        },
    ]
    # the whole subjects under the area filter
    assert {f["value"] for f in found["facets"]["subjects"]} == {
        "Bestuursrecht; Omgevingsrecht",
        "Bestuursrecht; Ruimtelijk bestuursrecht",
        "Civiel recht; Verbintenissenrecht",
        "Civiel recht",
    }


def test_the_tree_of_the_areas_of_law_is_counted_without_both_its_filters(
    store: GraphStore,
) -> None:
    """With a subject chosen (`Bestuursrecht; Belastingrecht`), the main areas and the
    subjects under them still count every judgment, not only the chosen subject's."""

    def judgment(key: str, *subjects: str) -> dict[str, Any]:
        return {
            "_key": key,
            "type": "judgment",
            "labels": [],
            "props": {
                "ecli": key,
                "date_eff": "2026-01-01",
                "subjects": list(subjects),
            },
        }

    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            judgment("t1", "Bestuursrecht; Belastingrecht"),
            judgment("v1", "Bestuursrecht; Vreemdelingenrecht"),
            judgment("b1", "Bestuursrecht"),
            judgment("s1", "Strafrecht"),
        ],
    )
    for filters in (
        JudgmentFilters(subject="Bestuursrecht; Belastingrecht"),
        JudgmentFilters(subject_area="Strafrecht"),
        JudgmentFilters(),
    ):
        tree = get_judgments_list(store, filters)["facets"]["subject_area"]
        assert [(a["value"], a["count"]) for a in tree] == [
            ("Bestuursrecht", 3),
            ("Strafrecht", 1),
        ], filters
        assert [(n["label"], n["count"]) for n in tree[0]["narrower"]] == [
            ("Belastingrecht", 1),
            ("Vreemdelingenrecht", 1),
        ]
    chosen = get_judgments_list(
        store, JudgmentFilters(subject="Bestuursrecht; Belastingrecht")
    )
    assert chosen["total"] == 1


def test_without_facets_the_page_and_the_total_alone(
    corpus: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``facets=False``: the same page and total, ``facets`` None, and no count of a facet
    sent to the database (eight statements over every judgment on the full graph)."""
    with_facets = get_judgments_list(corpus, JudgmentFilters(tier="hoge_raad"))
    statements: list[str] = []
    query = corpus.query

    def counting(statement: Any, params: Any = None, **options: Any) -> Any:
        statements.append(str(statement))
        return query(statement, params, **options)

    monkeypatch.setattr(corpus, "query", counting)
    without = get_judgments_list(
        corpus, JudgmentFilters(tier="hoge_raad"), facets=False
    )
    assert without["items"] == with_facets["items"]
    assert without["total"] == with_facets["total"]
    assert without["facets"] is None
    assert not [s for s in statements if "GROUP BY" in s]


def _words(store: GraphStore, rare: int) -> None:
    """2,000 judgments of 2000 to 2019, all with ``huur`` in their summary and one in
    every *rare* with ``pacht``."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [_judgment(f"ECLI:NL:RBAMS:{2000 + n % 20}:{n}",
                   ecli=f"ECLI:NL:RBAMS:{2000 + n % 20}:{n}",
                   date_eff=f"{2000 + n % 20}-01-{1 + n % 28:02d}",
                   source="rechtspraak", stub=False, inbound_citation_count=n % 7,
                   summary="huur pacht" if n % rare == 0 else "huur woning")
         for n in range(2000)],
    )  # fmt: skip
    with store.pool.connection() as conn:
        conn.execute("ANALYZE judgments")


def _items_statement(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, filters: JudgmentFilters
) -> tuple[str, Any]:
    """The statement (and its parameters) that reads the page of the list *filters*."""
    seen: list[tuple[str, Any]] = []
    query = store.query

    def recorded(statement: Any, params: Any = None, **options: Any) -> Any:
        seen.append((str(statement), params))
        return query(statement, params, **options)

    monkeypatch.setattr(store, "query", recorded)
    get_judgments_list(store, filters, limit=100, facets=False)
    monkeypatch.setattr(store, "query", query)
    (found,) = [(s, p) for s, p in seen if "row_number()" in s]
    return found


def _ordered_scans(store: GraphStore, statement: str, params: Any) -> list[str]:
    """The indexes the plan of *statement* reads judgments in the order of, testing each
    row for the words of the search (``s_summary_t``, a ``Filter``). Planned as
    ``tests/pg/test_query_plans.py`` does, without sorts and table scans where the
    statement can do without, so that the few rows seeded here plan as a million do."""
    with store.pool.connection() as conn, conn.transaction():
        conn.execute("SET LOCAL enable_sort = off")
        conn.execute("SET LOCAL enable_seqscan = off")
        row = conn.execute("EXPLAIN (FORMAT JSON) " + statement, params).fetchone()
    assert row is not None
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if (
                node.get("Relation Name") == "judgments"
                and node.get("Node Type") == "Index Scan"
                and "s_summary_t" in node.get("Filter", "")
            ):
                found.append(node["Index Name"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(row[0])
    return found


def test_a_rare_word_finds_its_hits_before_it_sorts_them(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A word few judgments hold is found by its index, and its hits sorted: in the order
    of the date index the planner tests every judgment of the list for it (``pacht``,
    317 of a million on 2026-10-10: past the 30 s of a request, a 503)."""
    _words(store, rare=400)
    filters = JudgmentFilters(q="pacht", source="rechtspraak")
    statement, params = _items_statement(store, monkeypatch, filters)
    assert "hits AS MATERIALIZED" in statement
    assert _ordered_scans(store, statement, params) == []
    # what it replaces: the date index read in order, every row tested for the word
    monkeypatch.setattr(judgment_queries, "SORTED_HITS_MAX", -1)
    statement, params = _items_statement(store, monkeypatch, filters)
    assert _ordered_scans(store, statement, params)


@pytest.mark.parametrize("sort", ["date_desc", "date_asc", "citation_count"])
def test_sorted_hits_give_the_page_the_index_order_gives(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, sort: str
) -> None:
    _words(store, rare=3)
    filters = JudgmentFilters(q="pacht", source="rechtspraak")
    pages = []
    for most in (judgment_queries.SORTED_HITS_MAX, -1):
        monkeypatch.setattr(judgment_queries, "SORTED_HITS_MAX", most)
        pages.append(
            [
                get_judgments_list(
                    store, filters, sort=sort, limit=50, offset=offset, facets=False
                )
                for offset in (0, 50, 650)
            ]
        )
    assert pages[0] == pages[1]
    assert [page["total"] for page in pages[0]] == [667] * 3
    assert [len(page["items"]) for page in pages[0]] == [50, 50, 17]


def _page_and_statement(
    store: GraphStore,
    monkeypatch: pytest.MonkeyPatch,
    filters: JudgmentFilters,
    **page: Any,
) -> tuple[list[Any], str, Any]:
    """The items of a page of the list *filters*, and the statement that read them."""
    seen: list[tuple[str, Any]] = []
    query = store.query

    def recorded(statement: Any, params: Any = None, **options: Any) -> Any:
        seen.append((str(statement), params))
        return query(statement, params, **options)

    monkeypatch.setattr(store, "query", recorded)
    found = get_judgments_list(store, filters, limit=50, facets=False, **page)
    monkeypatch.setattr(store, "query", query)
    ((statement, params),) = [(s, p) for s, p in seen if "row_number()" in s]
    return found["items"], statement, params


def _page_by_id(store: GraphStore, statement: str, params: Any) -> list[Any]:
    """The page *statement* reads, its rows read again by their id: as the page was read
    before its rows were read by their place (``ctid``)."""
    by_id = statement.replace("j.ctid AS row_id", "j.id AS row_id").replace(
        "ON j.ctid = page.row_id", "ON j.id = page.row_id"
    )
    assert by_id != statement
    return list(store.query(by_id, params))


@pytest.mark.parametrize("sort", ["date_desc", "date_asc", "citation_count"])
@pytest.mark.parametrize("q", [None, "pacht"])
def test_rows_read_by_their_place_are_the_rows_read_by_their_id(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, sort: str, q: str | None
) -> None:
    """The page in the order of an index and the page of sorted hits give the same items
    whether their rows are read again by place or by id, at the start, in the middle and at
    the end of the list."""
    _words(store, rare=3)
    filters = JudgmentFilters(q=q, source="rechtspraak")
    for offset in (0, 50, 1950 if q is None else 650):
        items, statement, params = _page_and_statement(
            store, monkeypatch, filters, sort=sort, offset=offset
        )
        assert items
        assert items == _page_by_id(store, statement, params)


def _scans(store: GraphStore, statement: str, params: Any) -> list[str]:
    """The scans of judgments in the plan of *statement*: node type and index."""
    with store.pool.connection() as conn, conn.transaction():
        conn.execute("SET LOCAL enable_seqscan = off")
        row = conn.execute("EXPLAIN (FORMAT JSON) " + statement, params).fetchone()
    assert row is not None
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("Relation Name") == "judgments":
                found.append(
                    f"{node['Node Type']} {node.get('Index Name', '')}".strip()
                )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(row[0])
    return found


@pytest.mark.parametrize("q", [None, "pacht"])
def test_the_rows_of_a_page_are_read_by_their_place(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, q: str | None
) -> None:
    """The rows of the page are built into items from their place (a ``Tid Scan``), not
    looked up again by their id (``judgments_pkey``): four reads a row, the most of a cold
    page (2.1 s on prod for 100 judgments, 10 Oct)."""
    _words(store, rare=400)
    statement, params = _items_statement(
        store, monkeypatch, JudgmentFilters(q=q, source="rechtspraak")
    )
    scans = _scans(store, statement, params)
    assert "Tid Scan" in scans
    assert not any("judgments_pkey" in scan for scan in scans)


def test_a_request_waits_once_for_counts_that_expired_together(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counts of a list (its total and facets) are kept an hour, all computed by one
    warm-up, so they expire together; a request then has ten of them to wait for, partly one
    after another. It waits one ``STALE_WAIT`` in all and takes the kept counts, not one per
    count (11.1 s on prod on 10 Oct for the judgments of Rechtspraak)."""
    import time

    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store

    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            {"_key": f"j{n}", "type": "judgment", "labels": [],
             "props": {"ecli": f"ECLI:NL:HR:2020:{n}", "source": "rechtspraak",
                       "date_eff": "2020-01-01", "tier": "hoogste", "court_kind": "HR",
                       "subjects": ["Civiel recht"]}}
            for n in range(30)
        ],
    )  # fmt: skip
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        url = "/api/judgments?source=rechtspraak&limit=10&facets=true"
        kept = client.get(url).json()["facets"]
        # every kept count two hours old, and a new one slower than a request waits
        with version_cache._lock:
            for key, (value, at) in list(version_cache._lasting.items()):
                version_cache._lasting[key] = (value, at - 7200)
        computed = version_cache._compute_lasting

        def slow(entry_key: Any, compute: Any) -> Any:
            time.sleep(3)
            return computed(entry_key, compute)

        monkeypatch.setattr(version_cache, "_compute_lasting", slow)
        started = time.perf_counter()
        answer = client.get(url).json()
        took = time.perf_counter() - started
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert answer["facets"] == kept  # the kept counts
    assert took < version_cache.STALE_WAIT + 1.5, took  # one wait, not one per count
