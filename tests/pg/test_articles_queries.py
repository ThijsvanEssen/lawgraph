"""The article queries on a real PostgreSQL: detail, versions, citations, legislative
history, explanations and the passages that cite an article."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.qualifiers import Qualifier
from lawgraph.db import ArangoStore
from lawgraph.db.queries import articles
from lawgraph.db.queries.articles import (
    get_article_citations,
    get_article_cited_by,
    get_article_explanations,
    get_article_history,
    get_article_legislative_history,
    get_article_with_relations,
)

BWB = "BWBR0002"
ARTICLE = "articles/bwbr0002_5"
INSTRUMENT = "instruments/bwbr0002"
AV_OLD = "article_versions/av_5_old"
AV_NEW = "article_versions/av_5_new"
AV_UNDATED = "article_versions/av_5_undated"
AV_OTHER = "article_versions/av_6"


def _node(
    key: str, node_type: str, labels: list[str] | None = None, **props: Any
) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": labels or [], "props": props}


def _edge(
    key: str,
    source: str,
    target: str,
    relation: str,
    *,
    status: str = "canoniek",
    confidence: float | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "status": status,
        "confidence": confidence,
        "meta": meta or {},
    }


def _article(key: str, number: str, **props: Any) -> dict[str, Any]:
    return _node(
        key, "article", ["BWB", "Article"], bwb_id=BWB, article_number=number, **props
    )


def _version(
    key: str, stam_id: str | None, number: str, **props: Any
) -> dict[str, Any]:
    if stam_id is not None:
        props["stam_id"] = stam_id
    return _node(
        key,
        "article_version",
        ["BWB", "ArticleVersion"],
        bwb_id=props.pop("bwb_id", BWB),
        article_number=number,
        **props,
    )


# ── detail ───────────────────────────────────────────────────────────────────


def test_an_article_with_its_instrument_and_judgments(store: ArangoStore) -> None:
    store.bulk_insert_or_update_nodes("instruments", [_node("bwbr0002", "instrument")])
    store.bulk_insert_or_update_nodes("articles", [_article("bwbr0002_5", "5")])
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node("j1", "judgment", ecli="ECLI:1", date_eff="2020-01-01"),
            _node("j2", "judgment", ecli="ECLI:2", date_eff="2021-01-01"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("p", ARTICLE, INSTRUMENT, "PART_OF"),
            _edge("r1", "judgments/j1", ARTICLE, "REFERS_TO"),
            _edge("r2", "judgments/j2", ARTICLE, "REFERS_TO"),
        ]
    )

    data = get_article_with_relations(store, BWB, "5")

    assert data.article == {
        "_key": "bwbr0002_5",
        "_id": ARTICLE,
        "type": "article",
        "labels": ["BWB", "Article"],
        "props": {"article_number": "5", "bwb_id": BWB},
    }
    assert data.instrument is not None and data.instrument["_id"] == INSTRUMENT
    assert [j["_key"] for j in data.judgments] == ["j2", "j1"]
    assert data.metadata == {"judgment_count": 2}
    with pytest.raises(ValueError, match="article not found"):
        get_article_with_relations(store, BWB, "99")


# ── versions ─────────────────────────────────────────────────────────────────


def _seed_versions(store: ArangoStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _article("bwbr0002_5", "5", stam_id="S5"),
            _article("bwbr0002_7", "7"),  # no stam_id: matched on its number
        ],
    )
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _version("av_b", "S5", "5", valid_from="2020-01-01"),
            _version("av_a", "S5", "5a", valid_from="2020-01-01"),  # same day: key
            _version("av_d", "S5", "5", valid_from="2024-01-01"),
            _version("av_c", "S5", "4"),  # no valid_from: first, as null sorts
            _version("av_x", "S6", "5", valid_from="2019-01-01"),  # another identity
            _version("av_y", "S5", "5", bwb_id="BWBR0003", valid_from="2019-01-01"),
            _version("av_7", None, "7", valid_from="2021-01-01"),
            _version("av_7s", "S7", "7", valid_from="2020-01-01"),
        ],
    )


def test_the_versions_of_an_article_identity_oldest_first(store: ArangoStore) -> None:
    _seed_versions(store)

    data = get_article_history(store, BWB, "5")

    assert data.article["_id"] == ARTICLE
    assert [v["_key"] for v in data.versions] == ["av_c", "av_a", "av_b", "av_d"]
    assert data.versions[1] == {
        "_key": "av_a",
        "_id": "article_versions/av_a",
        "type": "article_version",
        "labels": ["BWB", "ArticleVersion"],
        "props": {
            "article_number": "5a",
            "bwb_id": BWB,
            "stam_id": "S5",
            "valid_from": "2020-01-01",
        },
    }
    # nothing names a dossier: no titles, and no query for them
    assert data.dossier_titles == {}

    without_stam = get_article_history(store, BWB, "7")
    assert [v["_key"] for v in without_stam.versions] == ["av_7s", "av_7"]

    with pytest.raises(ValueError, match="article not found"):
        get_article_history(store, BWB, "99")


def test_the_versions_name_the_dossiers_of_their_publications(
    store: ArangoStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.bulk_insert_or_update_nodes(
        "articles", [_article("bwbr0002_5", "5", stam_id="S5")]
    )
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _version(
                "av_1",
                "S5",
                "5",
                valid_from="2020-01-01",
                origin_publication={"dossiers": ["36000", " 35000 "]},
                commencement_publication={"dossiers": ["36000"]},
            ),
        ],
    )
    asked: list[list[str]] = []

    def titles(_store: Any, numbers: list[str]) -> dict[str, str | None]:
        asked.append(list(numbers))
        return {n: f"T{n}" for n in numbers}

    monkeypatch.setattr(articles, "get_dossier_titles", titles)

    data = get_article_history(store, BWB, "5")

    assert asked == [["35000", "36000"]]
    assert data.dossier_titles == {"35000": "T35000", "36000": "T36000"}


# ── citations ────────────────────────────────────────────────────────────────


def test_the_citations_of_an_article_in_text_order_once_per_span(
    store: ArangoStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _article(
                "bwbr0002_1",
                "1",
                citations=[
                    # the span of edge c0: already there
                    {
                        "target_bwb_id": BWB,
                        "target_article_number": "2",
                        "start": 30,
                        "end": 35,
                        "text": "art 2",
                    },
                    {
                        "target_bwb_id": BWB,
                        "target_article_number": "3",
                        "start": "1",
                        "end": 2.0,
                        "text": " x ",
                        "confidence": "0.4",
                    },
                    {"target_bwb_id": BWB, "target_article_number": "99"},
                    "not an entry",
                ],
            ),
            _article("bwbr0002_2", "2"),
            _article("bwbr0002_3", "3"),
        ],
    )
    store.bulk_insert_or_update_nodes("instruments", [_node("bwbr0003", "instrument")])
    source = "articles/bwbr0002_1"
    art2 = "articles/bwbr0002_2"
    span = {"start": 30, "end": 35, "text": "art 2"}
    store.bulk_insert_or_update_edges(
        [
            _edge("c1", source, art2, "REFERS_TO", confidence=0.9, meta=span),
            # the same span, a lower key: this one is kept
            _edge("c0", source, art2, "REFERS_TO", confidence=0.5, meta=span),
            _edge(
                "c2",
                source,
                "instruments/bwbr0003",
                "REFERS_TO",
                meta={
                    "start": 10,
                    "end": 15,
                    "text": "Wet",
                    "reference_kind": "extref",
                    "leden": ["2"],
                },
            ),
            # a target that is not there
            _edge("c3", source, "articles/bwbr0002_99", "REFERS_TO", meta={"start": 5}),
            # no position: first, as null sorts
            _edge("c4", source, art2, "REFERS_TO"),
            # a string sorts after every number
            _edge(
                "c5",
                source,
                "instruments/bwbr0003",
                "REFERS_TO",
                meta={"start": "20", "end": "22"},
            ),
            _edge("c6", source, INSTRUMENT, "PART_OF", meta={"start": 1}),
        ]
    )
    article = store.get_document("articles", "bwbr0002_1")
    assert article is not None

    citations = get_article_citations(store, article)

    assert [
        (c.target["_id"], c.start, c.end, c.text, c.confidence, c.reference_kind)
        for c in citations
    ] == [
        (art2, None, None, None, None, None),
        ("instruments/bwbr0003", 10, 15, "Wet", None, "extref"),
        (art2, 30, 35, "art 2", 0.5, None),
        ("instruments/bwbr0003", 20, 22, None, None, None),
        ("articles/bwbr0002_3", 1, 2, "x", 0.4, None),
    ]
    assert citations[1].qualifier == Qualifier(leden=("2",))
    assert citations[0].target == {
        "_key": "bwbr0002_2",
        "_id": art2,
        "type": "article",
        "labels": ["BWB", "Article"],
        "props": {"article_number": "2", "bwb_id": BWB},
    }
    assert get_article_citations(store, {}) == []
    assert get_article_citations(store, {"props": {}}) == []


# ── legislative history ──────────────────────────────────────────────────────


def _seed_history(store: ArangoStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles", [_article("bwbr0002_5", "5", stam_id="S5")]
    )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _node("36000", "dossier", label="36000", title="Wet A"),
            _node("36001", "dossier", label="36001", title="Wet B"),
            _node("36002", "dossier", label="36002"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node(
                "stb_2024_7",
                "instrument",
                kind=None,
                publication_kind="Stb",
                date=None,
                date_published="2024-02-01",
                display_name="Stb. 2024, 7",
                # the dossier of its edge, and one the graph does not hold
                dossier_numbers=["36001", "17524"],
            ),
            # no dossier at all: no entry
            _node("stb_1990_1", "instrument", publication_kind="Stb"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node(
                "bill_1",
                "document",
                kind="Wetsvoorstel",
                date="2025-03-01",
                display_name="Voorstel",
                # the numbers of a document are no dossiers of the change
                dossier_numbers=["99999"],
            ),
            _node("memo", "document", kind="Nota", date="2025-04-01"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "judgments", [_node("j1", "judgment", date="2025-01-01")]
    )
    stb = "instruments/stb_2024_7"
    bill = "documents/bill_1"
    store.bulk_insert_or_update_edges(
        [
            _edge("h1", stb, ARTICLE, "AMENDS"),
            _edge("h2", stb, "dossiers/36001", "LEGISLATED_IN"),
            _edge("h3", "instruments/stb_1990_1", ARTICLE, "AMENDS"),
            _edge("h4", bill, ARTICLE, "INTRODUCES", status="voorgesteld"),
            _edge("h5", bill, "dossiers/36000", "PART_OF"),
            _edge("h6", bill, "cases/c1", "PART_OF"),
            _edge("h7", "cases/c1", "dossiers/36002", "PART_OF"),
            _edge("h8", "cases/c1", "dossiers/36000", "PART_OF"),  # once
            _edge("h9", "documents/memo", ARTICLE, "REPEALS", status="voorgesteld"),
            _edge("h10", "judgments/j1", ARTICLE, "REFERS_TO"),
            _edge("h11", "documents/ghost", ARTICLE, "AMENDS"),
        ]
    )


def test_the_legislative_history_is_the_dossiers_that_changed_the_article(
    store: ArangoStore,
) -> None:
    _seed_history(store)

    entries = get_article_legislative_history(store, BWB, "5")

    bill = {
        "date": "2025-03-01",
        "kind": "Wetsvoorstel",
        "change": "introduces",
        "status": "voorgesteld",
        "summary": "Voorstel",
        "document_id": "documents/bill_1",
    }
    stb = {
        "date": "2024-02-01",
        "kind": "Stb",
        "change": "amends",
        "status": "canoniek",
        "summary": "Stb. 2024, 7",
        "document_id": "instruments/stb_2024_7",
    }
    assert entries == [
        {
            **bill,
            "dossier_id": "dossiers/36000",
            "dossier_number": "36000",
            "dossier_title": "Wet A",
        },
        {
            **bill,
            "dossier_id": "dossiers/36002",
            "dossier_number": "36002",
            "dossier_title": None,
        },
        {
            **stb,
            "dossier_id": None,
            "dossier_number": "17524",
            "dossier_title": None,
        },
        {
            **stb,
            "dossier_id": "dossiers/36001",
            "dossier_number": "36001",
            "dossier_title": "Wet B",
        },
    ]
    assert list(entries[0]) == [
        "date",
        "kind",
        "change",
        "status",
        "summary",
        "document_id",
        "dossier_id",
        "dossier_number",
        "dossier_title",
    ]
    # by id, as the route asks
    assert get_article_legislative_history(store, BWB, "x", article_id=ARTICLE) == (
        entries
    )
    assert get_article_legislative_history(store, BWB, "99") == []


# ── explanations ─────────────────────────────────────────────────────────────


def _document(key: str, date: str | None, labels: list[str] | None = None) -> Any:
    return _node(
        key,
        "document",
        labels or ["TK"],
        source="tk",
        kind="Memorie van toelichting",
        title=f"MvT {key}",
        date=date,
    )


def _seed_explanations(store: ArangoStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _node("36000", "dossier", label="36000"),
            _node("36001", "dossier", label="36001"),
            _node("36009", "dossier"),  # no label: never the number
        ],
    )
    store.bulk_insert_or_update_nodes("instruments", [_node("bwbr0002", "instrument")])
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _article("bwbr0002_5", "5", stam_id="S5"),
            _article("bwbr0002_6", "6", stam_id="S6"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _version("av_5_old", "S5", "5", valid_from="2020-01-01"),
            _version("av_5_new", "S5", "5", valid_from="2024-01-01"),
            _version("av_5_undated", "S5", "5"),
            _version("av_6", "S6", "6", valid_from="2024-01-01"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            # explains a version and the article itself: one item, the version
            _document("mvt_2025", "2025-01-10T00:00:00"),
            # explains both dated versions: one item, the newest version
            _document("mvt_2024", "2024-05-01"),
            # explains the article only; another dossier
            _document("nvt_2023", "2023-03-01"),
            # explains a version of another article only
            _document("mvt_other", "2025-06-01"),
            # explains the instrument
            _document("mvt_law", "2026-01-01"),
            # an Eerste Kamer paper without a dossier or a date
            _document("ek_nota", None, ["EersteKamer", "EK"]),
            # explains the article for the dossier, and a version for a passage
            _document("mvt_anchor", "2022-02-02"),
            # explains an undated and a dated version: the dated one
            _document("mvt_undated", "2021-06-01"),
        ],
    )
    d = "documents"
    edges = [
        _edge("p1", f"{d}/mvt_2025", "dossiers/36000", "PART_OF"),
        _edge("p2", f"{d}/mvt_2024", "dossiers/36000", "PART_OF"),
        _edge("p3", f"{d}/nvt_2023", "dossiers/36001", "PART_OF"),
        _edge("p4", f"{d}/mvt_law", "dossiers/36001", "PART_OF"),
        _edge("p5", f"{d}/mvt_anchor", "dossiers/36001", "PART_OF"),
        _edge("p6", f"{d}/mvt_anchor", "dossiers/36000", "PART_OF"),
        _edge("p7", f"{d}/mvt_undated", "dossiers/36009", "PART_OF"),
        _edge("p8", f"{d}/mvt_undated", "cases/c1", "PART_OF"),
    ]
    explains = [
        ("mvt_2025", AV_NEW, None),
        ("mvt_2025", ARTICLE, None),
        ("mvt_2024", AV_OLD, None),
        ("mvt_2024", AV_NEW, None),
        ("nvt_2023", ARTICLE, None),
        ("mvt_other", AV_OTHER, None),
        ("mvt_other", "articles/bwbr0002_6", None),
        ("mvt_law", INSTRUMENT, None),
        ("ek_nota", ARTICLE, None),
        ("mvt_anchor", ARTICLE, None),
        ("mvt_anchor", AV_OLD, "artikel-5"),
        ("mvt_undated", AV_UNDATED, None),
        ("mvt_undated", AV_OLD, None),
    ]
    for i, (document, target, anchor) in enumerate(explains):
        meta = {"section_anchor": anchor} if anchor else {}
        edges.append(
            _edge(
                f"x{i:02d}",
                f"{d}/{document}",
                target,
                "EXPLAINS",
                confidence=1.0,
                meta=meta,
            )
        )
    # an amendment is not an explanation; an edge from a judgment is none either
    edges.append(_edge("i1", f"{d}/mvt_2024", ARTICLE, "INTRODUCES"))
    edges.append(_edge("i2", "judgments/j1", ARTICLE, "EXPLAINS"))
    # a document that is not there
    edges.append(_edge("i3", f"{d}/ghost", ARTICLE, "EXPLAINS"))
    store.bulk_insert_or_update_edges(edges)


def _explanations(store: ArangoStore, **page: int) -> dict[str, Any]:
    page = {"limit": 100, "offset": 0, **page}
    return get_article_explanations(store, BWB, "5", **page)


def _summary(page: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    return [
        (row["key"], row["target_id"], row["section_anchor"]) for row in page["items"]
    ]


def test_an_article_is_explained_through_itself_and_its_versions_not_its_law(
    store: ArangoStore,
) -> None:
    _seed_explanations(store)

    page = _explanations(store)

    assert _summary(page) == [
        ("mvt_2025", AV_NEW, None),
        ("mvt_2024", AV_NEW, None),
        ("nvt_2023", ARTICLE, None),
        ("mvt_anchor", ARTICLE, None),  # without a passage before with one
        ("mvt_anchor", AV_OLD, "artikel-5"),
        ("mvt_undated", AV_OLD, None),
        ("ek_nota", ARTICLE, None),  # no date: last
    ]
    assert page["total"] == 7
    assert list(page) == ["total", "items"]
    first = page["items"][0]
    assert list(first) == [
        "document_id",
        "key",
        "kind",
        "title",
        "date",
        "source",
        "labels",
        "dossier_number",
        "target_id",
        "confidence",
        "section_anchor",
    ]
    assert first == {
        "document_id": "documents/mvt_2025",
        "key": "mvt_2025",
        "kind": "Memorie van toelichting",
        "title": "MvT mvt_2025",
        "date": "2025-01-10T00:00:00",
        "source": "tk",
        "labels": ["TK"],
        "dossier_number": "36000",
        "target_id": AV_NEW,
        "confidence": 1.0,
        "section_anchor": None,
    }
    by_key = {(r["key"], r["section_anchor"]): r for r in page["items"]}
    # the lowest label of its dossiers
    assert by_key[("mvt_anchor", "artikel-5")]["dossier_number"] == "36000"
    # a dossier without a label is no number
    assert by_key[("mvt_undated", None)]["dossier_number"] is None
    ek = by_key[("ek_nota", None)]
    assert ek["labels"] == ["EersteKamer", "EK"]
    assert ek["date"] is None and ek["dossier_number"] is None


def test_the_page_of_explanations_is_cut_and_the_total_is_not(
    store: ArangoStore,
) -> None:
    _seed_explanations(store)
    everything = _summary(_explanations(store))

    pages = [_explanations(store, limit=3, offset=offset) for offset in (0, 3, 6)]

    assert [p["total"] for p in pages] == [7, 7, 7]
    assert [len(p["items"]) for p in pages] == [3, 3, 1]
    assert sum((_summary(p) for p in pages), []) == everything
    assert _explanations(store, offset=50) == {"total": 7, "items": []}
    assert _explanations(store, limit=0) == {"total": 7, "items": []}


def test_explanations_of_another_or_an_unknown_article(store: ArangoStore) -> None:
    _seed_explanations(store)

    other = get_article_explanations(store, BWB, "6", limit=10, offset=0)

    assert _summary(other) == [("mvt_other", AV_OTHER, None)]
    assert other["total"] == 1
    assert get_article_explanations(store, BWB, "99", limit=10, offset=0) == {
        "total": 0,
        "items": [],
    }


# ── cited by ─────────────────────────────────────────────────────────────────

CITED = "articles/sr_287"


def _judgment(key: str, ecli: str, court: str, tier: str, date: str | None) -> Any:
    props: dict[str, Any] = {
        "ecli": ecli,
        "display_name": f"{court} {key}",
        "court_code": court,
        "tier": tier,
        "court_kind": "x",
        "text": "a long text that is not read",
    }
    if date:
        props["date_eff"] = date
    return _node(key, "judgment", ["Rechtspraak"], **props)


def _seed_cited_by(store: ArangoStore) -> None:
    store.bulk_insert_or_update_nodes("articles", [_node("sr_287", "article")])
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _judgment("j1", "ECLI:NL:HR:2020:1", "HR", "cassatie", "2020-05-01"),
            _judgment("j2", "ECLI:NL:RBAMS:2021:2", "RBAMS", "first", "2021-01-01"),
            _judgment("j3", "ECLI:NL:GHDHA:2021:3", "GHDHA", "appeal", "2021-01-01"),
            _judgment("j4", "ECLI:NL:RBAMS:2019:4", "RBAMS", "first", None),
            _judgment("j5", "ECLI:NL:HR:2022:5", "HR", "cassatie", "2022-01-01"),
            _judgment("j6", "ECLI:NL:HR:2022:6", "HR", "cassatie", "2022-01-01"),
        ],
    )

    def cites(key: str, source: str, mentions: Any) -> dict[str, Any]:
        return _edge(key, source, CITED, "REFERS_TO", meta={"mentions": mentions})

    store.bulk_insert_or_update_edges(
        [
            cites(
                "e1",
                "judgments/j1",
                [{"leden": ["1"], "snippet": "a"}, {"leden": ["2"], "snippet": "b"}],
            ),
            cites("e2", "judgments/j2", [{"leden": ["1", "2"], "snippet": "c"}]),
            cites("e3", "judgments/j3", [{"snippet": "d"}]),
            cites("e4", "judgments/j4", [{"leden": ["2"], "snippet": "e"}]),
            cites("e5", "judgments/j5", "not a list"),
            cites("e6", "judgments/j6", []),
            # not a judgment, and a judgment that is not there
            cites("e7", "documents/d1", [{"snippet": "f"}]),
            cites("e8", "judgments/ghost", [{"snippet": "g"}]),
        ]
    )


def _snippets(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(r["judgment"]["_key"], r["mention"]["snippet"]) for r in rows]


def test_the_passages_that_cite_an_article_newest_first(store: ArangoStore) -> None:
    _seed_cited_by(store)

    cited = get_article_cited_by(store, CITED)

    assert _snippets(cited.rows) == [
        ("j3", "d"),  # the same day as j2: by ECLI
        ("j2", "c"),
        ("j1", "a"),  # one judgment: its mentions in order
        ("j1", "b"),
        ("j4", "e"),  # no date: last
    ]
    assert cited.total == 5 and cited.judgment_total == 4
    assert cited.rows[0] == {
        "judgment": {
            "_id": "judgments/j3",
            "_key": "j3",
            "props": {
                "ecli": "ECLI:NL:GHDHA:2021:3",
                "display_name": "GHDHA j3",
                "court_code": "GHDHA",
                "tier": "appeal",
                "court_kind": "x",
                "date_eff": "2021-01-01",
            },
        },
        "mention": {"snippet": "d"},
    }
    assert list(cited.rows[0]) == ["judgment", "mention"]
    assert list(cited.rows[0]["judgment"]["props"]) == [
        "ecli",
        "display_name",
        "court_code",
        "tier",
        "court_kind",
        "date_eff",
    ]
    assert cited.rows[-1]["judgment"]["props"]["date_eff"] is None


def test_the_passages_are_filtered_and_paged(store: ArangoStore) -> None:
    _seed_cited_by(store)

    by_lid = get_article_cited_by(store, CITED, lid="2")
    assert _snippets(by_lid.rows) == [("j2", "c"), ("j1", "b"), ("j4", "e")]
    assert (by_lid.total, by_lid.judgment_total) == (3, 3)

    by_court = get_article_cited_by(store, CITED, court="hr")
    assert _snippets(by_court.rows) == [("j1", "a"), ("j1", "b")]
    assert (by_court.total, by_court.judgment_total) == (2, 1)

    by_tier = get_article_cited_by(store, CITED, tier="first", lid="1")
    assert _snippets(by_tier.rows) == [("j2", "c")]

    page = get_article_cited_by(store, CITED, limit=2, offset=1)
    assert _snippets(page.rows) == [("j2", "c"), ("j1", "a")]
    assert (page.total, page.judgment_total) == (5, 4)

    beyond = get_article_cited_by(store, CITED, offset=10)
    assert (beyond.rows, beyond.total, beyond.judgment_total) == ([], 5, 4)

    nothing = get_article_cited_by(store, "articles/none")
    assert (nothing.rows, nothing.total, nothing.judgment_total) == ([], 0, 0)
