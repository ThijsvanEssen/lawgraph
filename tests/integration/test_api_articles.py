"""The explained-by and legislative-history queries of an article, run for real.

An article of BWBR0002 with two versions (one identity, the ``stam_id``), a second article
of the same law, and memoranda whose EXPLAINS edges point at the article, at its versions
and at the instrument, so that every part of the AQL has an edge to take.
"""

from __future__ import annotations

from typing import Any

from lawgraph.api.schemas.articles import ArticleExplanationDTO
from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_PART_OF,
    RELATION_VERSION_OF,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter
from lawgraph.db.queries.articles import (
    get_article_explanations,
    get_article_legislative_history,
)

BWB = "BWBR0002"
ARTICLE = f"{COLLECTION_ARTICLES}/bwbr0002_5"
INSTRUMENT = f"{COLLECTION_INSTRUMENTS}/bwbr0002"
AV_OLD = f"{COLLECTION_ARTICLE_VERSIONS}/av_5_old"
AV_NEW = f"{COLLECTION_ARTICLE_VERSIONS}/av_5_new"
AV_OTHER = f"{COLLECTION_ARTICLE_VERSIONS}/av_6"
DOSSIER_36000 = f"{COLLECTION_DOSSIERS}/36000"
DOSSIER_36001 = f"{COLLECTION_DOSSIERS}/36001"


def _node(
    collection: str, node_type: NodeType, key: str, labels: list[str], **props: Any
) -> Node:
    return Node(
        collection=collection, type=node_type, key=key, labels=labels, props=props
    )


def _document(key: str, date: str | None, labels: list[str] | None = None) -> Node:
    return _node(
        COLLECTION_DOCUMENTS,
        NodeType.DOCUMENT,
        key,
        labels or ["TK"],
        source="tk",
        kind="Memorie van toelichting",
        title=f"MvT {key}",
        date=date,
    )


def _version(key: str, stam_id: str, number: str, valid_from: str) -> Node:
    return _node(
        COLLECTION_ARTICLE_VERSIONS,
        NodeType.ARTICLE_VERSION,
        key,
        ["BWB", "ArticleVersion"],
        bwb_id=BWB,
        stam_id=stam_id,
        article_number=number,
        valid_from=valid_from,
    )


def _explains(edges: EdgeWriter, document: str, target: str, **fields: Any) -> None:
    edges.add(
        f"{COLLECTION_DOCUMENTS}/{document}",
        target,
        RELATION_EXPLAINS,
        source="test",
        confidence=1.0,
        **fields,
    )


def _build(store: ArangoStore) -> None:
    nodes = [
        _node(
            COLLECTION_DOSSIERS,
            NodeType.DOSSIER,
            "36000",
            ["TK"],
            number="36000",
            label="36000",
        ),
        _node(
            COLLECTION_DOSSIERS,
            NodeType.DOSSIER,
            "36001",
            ["TK"],
            number="36001",
            label="36001",
        ),
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            "bwbr0002",
            ["BWB"],
            bwb_id=BWB,
        ),
        _node(
            COLLECTION_ARTICLES,
            NodeType.ARTICLE,
            "bwbr0002_5",
            ["BWB", "Article"],
            bwb_id=BWB,
            article_number="5",
            stam_id="S5",
        ),
        _node(
            COLLECTION_ARTICLES,
            NodeType.ARTICLE,
            "bwbr0002_6",
            ["BWB", "Article"],
            bwb_id=BWB,
            article_number="6",
            stam_id="S6",
        ),
        _version("av_5_old", "S5", "5", "2020-01-01"),
        _version("av_5_new", "S5", "5", "2024-01-01"),
        _version("av_6", "S6", "6", "2024-01-01"),
        # 2025: explains a version and the article itself: one item, the version
        _document("mvt_2025", "2025-01-10T00:00:00"),
        # 2024: explains both versions of the article: one item, the newest version
        _document("mvt_2024", "2024-05-01"),
        # 2023: explains the article only; another dossier
        _document("nvt_2023", "2023-03-01"),
        # explains a version of another article only
        _document("mvt_other", "2025-06-01"),
        # explains the instrument (the dossier's law changed no articles)
        _document("mvt_law", "2026-01-01"),
        # an Eerste Kamer paper without a dossier or a date
        _document("ek_nota", None, ["EersteKamer", "EK"]),
        # explains the article for the dossier, and a version for a passage
        _document("mvt_anchor", "2022-02-02"),
    ]
    with NodeWriter(store) as writer:
        writer.add_all(nodes)

    d = COLLECTION_DOCUMENTS
    edges = EdgeWriter(store, what=None)
    for from_id, to_id in [
        (f"{d}/mvt_2025", DOSSIER_36000),
        (f"{d}/mvt_2024", DOSSIER_36000),
        (f"{d}/nvt_2023", DOSSIER_36001),
        (f"{d}/mvt_law", DOSSIER_36001),
        (f"{d}/mvt_anchor", DOSSIER_36000),
        (ARTICLE, INSTRUMENT),
        (f"{COLLECTION_ARTICLES}/bwbr0002_6", INSTRUMENT),
    ]:
        edges.add(from_id, to_id, RELATION_PART_OF, source="test")
    for version, article in [
        (AV_OLD, ARTICLE),
        (AV_NEW, ARTICLE),
        (AV_OTHER, f"{COLLECTION_ARTICLES}/bwbr0002_6"),
    ]:
        edges.add(version, article, RELATION_VERSION_OF, source="test")
    _explains(edges, "mvt_2025", AV_NEW)
    _explains(edges, "mvt_2025", ARTICLE)
    _explains(edges, "mvt_2024", AV_OLD)
    _explains(edges, "mvt_2024", AV_NEW)
    _explains(edges, "nvt_2023", ARTICLE)
    _explains(edges, "mvt_other", AV_OTHER)
    _explains(edges, "mvt_other", f"{COLLECTION_ARTICLES}/bwbr0002_6")
    _explains(edges, "mvt_law", INSTRUMENT)
    _explains(edges, "ek_nota", ARTICLE)
    _explains(edges, "mvt_anchor", ARTICLE)
    _explains(edges, "mvt_anchor", AV_OLD, meta={"section_anchor": "artikel-5"})
    # an amendment is not an explanation
    edges.add(f"{d}/mvt_2024", ARTICLE, RELATION_INTRODUCES, source="test")
    edges.flush()


def _explanations(store: ArangoStore, **page: int) -> dict[str, Any]:
    page = {"limit": 100, "offset": 0, **page}
    return get_article_explanations(store, BWB, "5", **page)


def _summary(page: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    """``(document key, target id, section anchor)`` per row, in order."""
    return [
        (row["key"], row["target_id"], row["section_anchor"]) for row in page["items"]
    ]


def test_an_article_is_explained_through_itself_its_versions_and_its_instrument(
    database: str,
) -> None:
    store = ArangoStore()
    _build(store)

    page = _explanations(store)

    assert _summary(page) == [
        ("mvt_2025", AV_NEW, None),  # the version, not the article as well
        ("mvt_2024", AV_NEW, None),  # the newest of the versions it explains
        ("nvt_2023", ARTICLE, None),
        ("mvt_anchor", ARTICLE, None),  # without a passage before with one
        ("mvt_anchor", AV_OLD, "artikel-5"),
        ("ek_nota", ARTICLE, None),  # no date: last of the article-level ones
        ("mvt_law", INSTRUMENT, None),  # instrument level after all of those
    ]
    assert page["total"] == 7
    # the document of another article is nowhere
    assert "mvt_other" not in [row["key"] for row in page["items"]]


def test_a_row_carries_what_the_dto_needs(database: str) -> None:
    store = ArangoStore()
    _build(store)

    items = [ArticleExplanationDTO.from_row(r) for r in _explanations(store)["items"]]
    by_key = {(i.document.key, i.section_anchor): i for i in items}

    newest = by_key[("mvt_2025", None)]
    assert newest.target == "article_version"
    assert newest.article_version_key == "av_5_new"
    assert newest.scope == "dossier" and newest.confidence == 1.0
    assert newest.document.dossier_number == "36000"
    assert newest.document.chamber == "TK" and newest.document.date == "2025-01-10"
    assert newest.document.is_explanatory is True

    passage = by_key[("mvt_anchor", "artikel-5")]
    assert passage.scope == "article" and passage.target == "article_version"
    assert passage.article_version_key == "av_5_old"
    assert by_key[("mvt_anchor", None)].scope == "dossier"

    law = by_key[("mvt_law", None)]
    assert law.target == "instrument" and law.article_version_key is None
    assert law.document.dossier_number == "36001"

    ek = by_key[("ek_nota", None)]
    assert ek.document.chamber == "EK" and ek.document.dossier_number is None
    assert ek.document.date is None


def test_the_page_is_cut_and_the_total_is_not(database: str) -> None:
    store = ArangoStore()
    _build(store)
    everything = _summary(_explanations(store))

    first = _explanations(store, limit=3)
    rest = _explanations(store, limit=3, offset=3)
    last = _explanations(store, limit=3, offset=6)

    assert first["total"] == rest["total"] == last["total"] == 7
    assert _summary(first) + _summary(rest) + _summary(last) == everything
    assert _explanations(store, offset=50) == {"total": 7, "items": []}


def test_an_unknown_article_has_no_explanations(database: str) -> None:
    store = ArangoStore()
    _build(store)

    assert get_article_explanations(store, BWB, "99", limit=10, offset=0) == {
        "total": 0,
        "items": [],
    }


def test_an_article_of_another_identity_is_not_explained_by_the_versions_of_this_one(
    database: str,
) -> None:
    store = ArangoStore()
    _build(store)

    other = get_article_explanations(store, BWB, "6", limit=10, offset=0)

    assert _summary(other) == [
        ("mvt_other", AV_OTHER, None),
        ("mvt_law", INSTRUMENT, None),
    ]


def test_the_legislative_history_no_longer_lists_the_explanations(
    database: str,
) -> None:
    store = ArangoStore()
    _build(store)

    entries = get_article_legislative_history(store, BWB, "5")

    assert [e["document_id"] for e in entries] == [f"{COLLECTION_DOCUMENTS}/mvt_2024"]
    assert entries[0]["dossier_number"] == "36000"


# 2,400 explanatory documents of 120 KB: 288 MB, more than the 256 MiB a query may use on
# the test server. An instrument of the real corpus has hundreds of dossiers, and every
# dossier has several documents.
DOCUMENTS = 2_400
VERSIONS = 25
SIZE = 120_000


class _Recording:
    """A store that keeps the queries asked of it, to explain them afterwards."""

    def __init__(self, store: ArangoStore) -> None:
        self._store = store
        self.asked: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def query(
        self, aql: str, bind_vars: dict[str, Any] | None = None, **kw: Any
    ) -> Any:
        self.asked.append((aql, bind_vars or {}))
        return self._store.query(aql, bind_vars, **kw)


def _build_at_scale(store: ArangoStore) -> None:
    """One article of ``VERSIONS`` versions; 3/4 of the documents explain a version of it,
    1/4 the instrument; every document carries a large text."""
    text = "x" * SIZE
    nodes = [
        _node(
            COLLECTION_DOSSIERS,
            NodeType.DOSSIER,
            "36000",
            ["TK"],
            number="36000",
            label="36000",
        ),
        _node(
            COLLECTION_INSTRUMENTS, NodeType.INSTRUMENT, "bwbr0002", ["BWB"], bwb_id=BWB
        ),
        _node(
            COLLECTION_ARTICLES,
            NodeType.ARTICLE,
            "bwbr0002_5",
            ["BWB", "Article"],
            bwb_id=BWB,
            article_number="5",
            stam_id="S5",
        ),
    ]
    nodes += [
        _version(f"av_{n}", "S5", "5", f"{2000 + n}-01-01") for n in range(VERSIONS)
    ]
    for number in range(DOCUMENTS):
        document = _document(f"mvt_{number}", f"2020-01-01T{number % 24:02d}:00:00")
        document.props["text"] = text
        nodes.append(document)
    with NodeWriter(store) as writer:
        writer.add_all(nodes)

    edges = EdgeWriter(store, what=None)
    edges.add(ARTICLE, INSTRUMENT, RELATION_PART_OF, source="test")
    for number in range(DOCUMENTS):
        document = f"{COLLECTION_DOCUMENTS}/mvt_{number}"
        edges.add(document, DOSSIER_36000, RELATION_PART_OF, source="test")
        target = (
            INSTRUMENT
            if number % 4 == 0
            else f"{COLLECTION_ARTICLE_VERSIONS}/av_{number % VERSIONS}"
        )
        edges.add(document, target, RELATION_EXPLAINS, source="test", confidence=1.0)
    edges.flush()


def test_the_explanations_of_an_article_read_no_document_but_the_page(
    database: str,
) -> None:
    """Counting and sorting the explanations must not materialise the documents (their
    text is up to a megabyte): as a query of 288 MB of documents it would be stopped."""
    real = ArangoStore()
    _build_at_scale(real)
    store: Any = _Recording(real)

    page = get_article_explanations(store, BWB, "5", limit=50, offset=0)
    rest = get_article_explanations(store, BWB, "5", limit=50, offset=DOCUMENTS - 100)

    assert page["total"] == rest["total"] == DOCUMENTS
    assert len(page["items"]) == 50 and len(rest["items"]) == 50
    first = {ArticleExplanationDTO.from_row(r).target for r in page["items"]}
    last = {ArticleExplanationDTO.from_row(r).target for r in rest["items"]}
    assert first == {"article_version"}
    assert last == {"instrument"}  # 1,800 of the article, then the instrument's
    assert all("text" not in row for row in page["items"])

    aql, bind = next((a, b) for a, b in store.asked if "@explains" in a)
    plan = real.db.aql.explain(aql, bind_vars=bind)
    kinds = [node["type"] for node in plan["nodes"]]
    assert "EnumerateCollectionNode" not in kinds, kinds
