"""The reads and writes of the BWB, Staatsblad/Staatscourant and EUR-Lex normalize and
semantic steps on a real PostgreSQL: which rows, in which order, what a write leaves."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    RAW_KIND_EU_NIM,
    SOURCE_BWB,
    SOURCE_EURLEX,
    SOURCE_STAATSBLAD,
    SOURCE_STAATSCOURANT,
)
from lawgraph.db import GraphStore, raw_source_doc
from lawgraph.db.queries.normalize import bwb as normalize_bwb
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.queries.semantic import eu as semantic_eu


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [node_type], "props": props}


def _edge(key: str, source: str, target: str, **doc: Any) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": "REFERS_TO",
        "source": "bwb",
        "status": "canoniek",
        "confidence": 0.9,
        "meta": {},
        **doc,
    }


def _props(store: GraphStore, collection: str, key: str) -> dict[str, Any]:
    doc = store.get_document(collection, key)
    assert doc is not None
    return doc["props"]


def _edge_doc(store: GraphStore, key: str) -> dict[str, Any]:
    return next(store.query("SELECT doc FROM edges WHERE key = %(k)s", {"k": key}))


# ── instruments ──────────────────────────────────────────────────────────────


def _instruments(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node(
                "bwbr2",
                "instrument",
                source=SOURCE_BWB,
                bwb_id="BWBR2",
                title="Wet twee",
                citation_title="Wet twee",
                short_title="W2",
                aliases=["W2", "Wtwee"],
                basis=["BWBR1"],
                dossier_numbers=["123", "456"],
            ),
            _node(
                "bwbr1",
                "instrument",
                source=SOURCE_BWB,
                bwb_id="BWBR1",
                title="Wet een",
                basis=[],
                dossier_numbers="123",
            ),
            _node(
                "bwbr3",
                "instrument",
                source=SOURCE_BWB,
                bwb_id="BWBR3",
                basis="art. 1 Wet een",
            ),
            _node("celex_1", "instrument", source=SOURCE_EURLEX, celex="32016R0679"),
            _node("other", "instrument", source="tk", title="Geen id"),
            _node("stb", "instrument", source="x", basis=["y"], bwb_id="BWBR9"),
        ],
    )


def test_alias_rows_are_the_instruments_with_an_id_by_key(store: GraphStore) -> None:
    _instruments(store)
    assert list(semantic_bwb.instrument_alias_rows(store)) == [
        {"bwb_id": "BWBR1", "celex": None, "title": "Wet een", "citation_title": None},
        {
            "bwb_id": "BWBR2",
            "celex": None,
            "title": "Wet twee",
            "citation_title": "Wet twee",
        },
        {"bwb_id": "BWBR3", "celex": None, "title": None, "citation_title": None},
        {"bwb_id": None, "celex": "32016R0679", "title": None, "citation_title": None},
        {"bwb_id": "BWBR9", "celex": None, "title": None, "citation_title": None},
    ]
    rows = list(semantic_bwb.code_alias_rows(store))
    assert [r["bwb_id"] or r["celex"] for r in rows] == [
        "BWBR1",
        "BWBR2",
        "BWBR3",
        "32016R0679",
        "BWBR9",
    ]
    assert rows[1] == {
        "short_title": "W2",
        "aliases": ["W2", "Wtwee"],
        "bwb_id": "BWBR2",
        "celex": None,
    }


def test_regulations_with_basis_are_bwb_with_a_non_empty_basis(
    store: GraphStore,
) -> None:
    _instruments(store)
    assert list(semantic_bwb.regulations_with_basis(store)) == [
        {"key": "bwbr2", "bwb_id": "BWBR2", "basis": ["BWBR1"]},
        # LENGTH of a string is its number of characters
        {"key": "bwbr3", "bwb_id": "BWBR3", "basis": "art. 1 Wet een"},
    ]


def test_instruments_by_bwb_id(store: GraphStore) -> None:
    _instruments(store)
    assert list(
        semantic_bwb.instrument_keys_by_bwb_id(store, ["BWBR3", "BWBR1", "X"])
    ) == [
        {"_key": "bwbr1", "props": {"bwb_id": "BWBR1"}},
        {"_key": "bwbr3", "props": {"bwb_id": "BWBR3"}},
    ]
    assert list(semantic_bwb.instrument_ids_by_bwb_id(store, ["BWBR2", "BWBR1"])) == [
        {"bwb_id": "BWBR1", "inst_id": "instruments/bwbr1", "inst_key": "bwbr1"},
        {"bwb_id": "BWBR2", "inst_id": "instruments/bwbr2", "inst_key": "bwbr2"},
    ]
    assert list(semantic_bwb.instrument_keys_by_bwb_id(store, [])) == []


def test_regulation_dossier_numbers_are_a_list_or_empty(store: GraphStore) -> None:
    _instruments(store)
    assert list(semantic_bwb.regulation_dossier_numbers(store)) == [
        {"key": "bwbr1", "dossiers": []},  # a string is no list
        {"key": "bwbr2", "dossiers": ["123", "456"]},
        {"key": "bwbr3", "dossiers": []},
        {"key": "stb", "dossiers": []},
    ]


# ── articles ─────────────────────────────────────────────────────────────────


def _articles(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            # props out of order: a slim projection sorts them
            _node(
                "bwbr1_2",
                "article",
                text="Zie bijlage 1, de Tabel van tarieven.",
                references=[{"bwb_id": "BWBR2"}],
                bwb_id="BWBR1",
                article_number="2",
                stam_id="s2",
                heading="Twee",
            ),
            _node(
                "bwbr1_1",
                "article",
                bwb_id="BWBR1",
                article_number="1",
                stam_id="s1",
                text="De BIJLAGE geldt. Tabel van tarieven.",
                references=None,
            ),
            _node(
                "bwbr1_stub",
                "article",
                bwb_id="BWBR1",
                article_number="9",
                stub=True,
            ),
            _node(
                "bwbr1_old",
                "article",
                bwb_id="BWBR1",
                last_article_number="3",
                stam_id="s3",
            ),
            _node(
                "bwbr2_1",
                "article",
                bwb_id="BWBR2",
                article_number="1",
                stam_id="s1",
                text="Tabel van tarieven",
                references=[],
            ),
            _node(
                "celex_32016r0679_5",
                "article",
                celex="32016R0679",
                article_number="5",
                text="Beginselen",
                display_name="Artikel 5 AVG",
                heading="x",
            ),
            _node("celex_x_1", "article", celex="X", article_number="1"),
        ],
    )


def test_law_articles_of_a_law_by_key(store: GraphStore) -> None:
    _articles(store)
    assert list(semantic_bwb.law_articles(store, "bwb_id", "BWBR1")) == [
        {"key": "bwbr1_1", "number": "1", "last_number": None, "stub": False},
        {"key": "bwbr1_2", "number": "2", "last_number": None, "stub": False},
        {"key": "bwbr1_old", "number": None, "last_number": "3", "stub": False},
        {"key": "bwbr1_stub", "number": "9", "last_number": None, "stub": True},
    ]
    assert [r["key"] for r in semantic_bwb.law_articles(store, "celex", "X")] == [
        "celex_x_1"
    ]
    with pytest.raises(ValueError):
        semantic_bwb.law_articles(store, "props", "x")


def test_article_bwb_ids_are_distinct_and_sorted(store: GraphStore) -> None:
    _articles(store)
    assert list(semantic_bwb.article_bwb_ids(store)) == ["BWBR1", "BWBR2"]


def test_articles_with_references_are_slim_with_props_in_byte_order(
    store: GraphStore,
) -> None:
    _articles(store)
    rows = list(semantic_bwb.articles_with_references(store, ["BWBR1", "BWBR2"]))
    # bwbr1_1 has references null: left out; an empty list is there
    assert rows == [
        {
            "_key": "bwbr1_2",
            "type": "article",
            "labels": ["article"],
            "props": {
                "article_number": "2",
                "bwb_id": "BWBR1",
                "references": [{"bwb_id": "BWBR2"}],
            },
        },
        {
            "_key": "bwbr2_1",
            "type": "article",
            "labels": ["article"],
            "props": {"article_number": "1", "bwb_id": "BWBR2", "references": []},
        },
    ]
    assert list(rows[0]) == ["_key", "type", "labels", "props"]
    assert list(rows[0]["props"]) == ["article_number", "bwb_id", "references"]


def test_articles_by_identity_are_every_combination_by_key(store: GraphStore) -> None:
    _articles(store)
    rows = list(semantic_bwb.articles_by_identity(store, ["BWBR1", "BWBR2"], ["s1"]))
    assert rows == [
        {"key": "bwbr1_1", "bwb_id": "BWBR1", "stam_id": "s1"},
        {"key": "bwbr2_1", "bwb_id": "BWBR2", "stam_id": "s1"},
    ]


def test_article_identities_and_eu_articles(store: GraphStore) -> None:
    _articles(store)
    assert [r["key"] for r in normalize_bwb.article_identities(store, ["BWBR1"])] == [
        "bwbr1_1",
        "bwbr1_2",
        "bwbr1_old",
        "bwbr1_stub",
    ]
    assert list(normalize_bwb.article_identities(store, ["BWBR1"]))[3] == {
        "key": "bwbr1_stub",
        "bwb_id": "BWBR1",
        "stam_id": None,
    }
    avg = {
        "_key": "celex_32016r0679_5",
        "type": "article",
        "labels": ["article"],
        "props": {
            "article_number": "5",
            "celex": "32016R0679",
            "display_name": "Artikel 5 AVG",
            "text": "Beginselen",
        },
    }
    assert list(semantic_eu.eu_articles_of(store, ["32016R0679"])) == [avg]
    rows = list(semantic_eu.eu_articles(store))
    assert [r["_key"] for r in rows] == ["celex_32016r0679_5", "celex_x_1"]
    assert rows[1]["props"] == {"article_number": "1", "celex": "X"}


# ── annexes ──────────────────────────────────────────────────────────────────


def test_annexes_and_the_articles_that_name_them(store: GraphStore) -> None:
    _articles(store)
    store.bulk_insert_or_update_nodes(
        "annexes",
        [
            _node("b2", "annex", bwb_id="BWBR1", label="Bijlage 2", title="Tarieven"),
            _node("b1", "annex", bwb_id="BWBR1", label="Bijlage 1", title="Tabel"),
            _node("b3", "annex", bwb_id="BWBR1"),
            _node("b4", "annex", title="Zonder wet"),
        ],
    )
    assert list(semantic_bwb.annex_keys(store)) == ["b1", "b2", "b3", "b4"]
    assert list(semantic_bwb.titled_annexes(store)) == [
        {"key": "b1", "bwb_id": "BWBR1", "label": "Bijlage 1", "title": "Tabel"},
        {"key": "b2", "bwb_id": "BWBR1", "label": "Bijlage 2", "title": "Tarieven"},
    ]
    names = [
        {"key": "b2", "bwb_id": "BWBR1", "name": "Tabel van tarieven"},
        {"key": "b1", "bwb_id": "BWBR1", "name": "bijlage 1"},
    ]
    rows = list(semantic_bwb.articles_naming_annexes(store, names))
    # in the order of the names, then by key; the text is matched case-sensitively, and
    # the article of BWBR2 naming the table is not of the annex's regulation
    assert [(r["annex"], r["article"]["_key"]) for r in rows] == [
        ("b2", "bwbr1_1"),
        ("b2", "bwbr1_2"),
        ("b1", "bwbr1_2"),
    ]
    assert rows[0] == {
        "annex": "b2",
        "article": {
            "_key": "bwbr1_1",
            "type": "article",
            "labels": ["article"],
            "props": {
                "article_number": "1",
                "bwb_id": "BWBR1",
                "text": "De BIJLAGE geldt. Tabel van tarieven.",
            },
        },
    }
    mentioning = list(semantic_bwb.articles_mentioning_annex(store))
    assert [r["_key"] for r in mentioning] == ["bwbr1_1", "bwbr1_2"]
    assert list(mentioning[0]["props"]) == ["bwb_id", "text"]


# ── article versions ─────────────────────────────────────────────────────────


def _versions(store: GraphStore) -> None:
    origin = {"id": "stb-2020-1", "date": "2020-01-01"}
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _node(
                "v3",
                "article_version",
                bwb_id="BWBR1",
                stam_id="s1",
                article_number="1",
                origin_publication=origin,
                effect="wijziging",
                valid_from="2021-01-01",
                text="x" * 80,
                position=2,
                breadcrumb=[{"title": "H1"}],
            ),
            _node(
                "v1",
                "article_version",
                bwb_id="BWBR1",
                stam_id="s1",
                article_number="1",
                origin_publication={"id": "stb-2019-9"},
                effect="nieuw",
                valid_from="2020-01-01",
                source_publication="stb-2019-9",
                commencement_publication={"id": "stb-2019-10"},
                position=1,
            ),
            _node(
                "v0",
                "article_version",
                bwb_id="BWBR1",
                stam_id="s0",
                origin_publication=origin,
                position=None,
                valid_from=None,
            ),
            _node(
                "v2",
                "article_version",
                bwb_id="BWBR0",
                stam_id="s9",
                origin_publication=origin,
                valid_from="2020-06-01",
                position=10,
            ),
            _node("v4", "article_version", bwb_id="BWBR1", stam_id="s5", position=1),
            _node(
                "v5",
                "article_version",
                bwb_id="BWBR1",
                origin_publication=origin,
            ),
            _node(
                "v6",
                "article_version",
                bwb_id="BWBR1",
                stam_id="s2",
                origin_publication=None,
            ),
        ],
    )


def test_amending_versions_by_article_identity(store: GraphStore) -> None:
    _versions(store)
    rows = list(semantic_bwb.amending_article_versions(store))
    # an origin and a stam id; by bwb_id, stam_id, key
    assert [r["key"] for r in rows] == ["v2", "v0", "v1", "v3"]
    assert rows[2] == {
        "key": "v1",
        "bwb_id": "BWBR1",
        "stam_id": "s1",
        "effect": "nieuw",
        "valid_from": "2020-01-01",
        "source_publication": "stb-2019-9",
        "origin": {"id": "stb-2019-9"},
        "commencement": {"id": "stb-2019-10"},
    }
    assert rows[3]["source_publication"] is None


def test_article_versions_of_the_laws(store: GraphStore) -> None:
    _versions(store)
    rows = list(normalize_bwb.article_versions(store, ["BWBR1"]))
    assert [r["key"] for r in rows] == ["v0", "v1", "v3", "v4", "v5", "v6"]
    v3 = rows[2]
    assert list(v3) == [
        "key",
        "bwb_id",
        "stam_id",
        "number",
        "label",
        "valid_from",
        "valid_until",
        "current",
        "last_seen",
        "effect",
        "digest",
        "position",
        "text_start",
        "title",
    ]
    assert v3["text_start"] == "x" * 60
    assert v3["number"] == "1" and v3["position"] == 2 and v3["label"] is None
    assert rows[0]["text_start"] == ""  # SUBSTRING of a missing text


def test_stored_places_by_position_then_without(store: GraphStore) -> None:
    _versions(store)
    rows = list(normalize_bwb.stored_places(store, "BWBR1"))
    # v1 and v4 share position 1 (the key settles it); v0 (null), v5, v6 have none
    assert [r["key"] for r in rows] == ["v1", "v4", "v3", "v0", "v5", "v6"]
    assert rows[2] == {
        "key": "v3",
        "breadcrumb": [{"title": "H1"}],
        "breadcrumb_changes": None,
    }


def test_article_version_starts_of_the_versions_with_one(store: GraphStore) -> None:
    _versions(store)
    assert normalize_bwb.article_version_starts(store, ["v0", "v1", "v2", "nope"]) == {
        "v1": "2020-01-01",
        "v2": "2020-06-01",
    }


def test_toestand_starts_oldest_first_per_law(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instrument_versions",
        [
            _node("t3", "instrument_version", bwb_id="BWBR1", valid_from="2022-01-01"),
            _node("t1", "instrument_version", bwb_id="BWBR1", valid_from="2020-01-01"),
            _node("t2", "instrument_version", bwb_id="BWBR1"),
            _node("t4", "instrument_version", bwb_id="BWBR0", valid_from="2019-01-01"),
            _node("t5", "instrument_version", bwb_id="BWBR8", valid_from="2019-01-01"),
        ],
    )
    starts = normalize_bwb.toestand_starts(store, ["BWBR1", "BWBR0"])
    assert starts == {"BWBR0": ["2019-01-01"], "BWBR1": ["2020-01-01", "2022-01-01"]}
    assert list(starts) == ["BWBR0", "BWBR1"]


# ── classifications ──────────────────────────────────────────────────────────


def test_classifiable_edges_per_article(store: GraphStore) -> None:
    _articles(store)
    store.bulk_insert_or_update_edges(
        [
            _edge("e2", "articles/bwbr1_2", "articles/bwbr2_1", meta={"start": 4}),
            _edge(
                "e1",
                "articles/bwbr1_2",
                "articles/bwbr1_1",
                meta={"start": 1, "end": 9},
            ),
            _edge("e3", "articles/bwbr1_1", "articles/bwbr1_2", meta={"end": 3}),
            _edge("e4", "articles/bwbr1_1", "instruments/x", relation="PART_OF"),
            _edge("e5", "articles/bwbr1_old", "articles/bwbr1_1"),  # no text
            _edge("e6", "judgments/j", "articles/bwbr1_1"),
        ]
    )
    assert list(semantic_bwb.articles_with_classifiable_edges(store)) == [
        {
            "text": "De BIJLAGE geldt. Tabel van tarieven.",
            "edges": [{"key": "e3", "start": None, "end": 3}],
        },
        {
            "text": "Zie bijlage 1, de Tabel van tarieven.",
            "edges": [
                {"key": "e1", "start": 1, "end": 9},
                {"key": "e2", "start": 4, "end": None},
            ],
        },
    ]


def test_update_edge_classifications_writes_what_differs(store: GraphStore) -> None:
    store.bulk_insert_or_update_edges(
        [
            _edge("e1", "articles/a", "articles/b", meta={"start": 1, "end": 5}),
            _edge(
                "e2",
                "articles/a",
                "articles/c",
                semantic_type="definition",
                explanation="Zie",
                meta={"semantic_pattern": "p", "semantic_confidence": 0.8},
            ),
        ]
    )
    batch = [
        {
            "key": "e1",
            "semantic_type": "applies",
            "explanation": "Van toepassing",
            "pattern": "van toepassing",
            "semantic_confidence": 0.7,
        },
        {
            "key": "e2",
            "semantic_type": "definition",
            "explanation": "Zie",
            "pattern": "p",
            "semantic_confidence": 0.80,
        },
        {
            "key": "missing",
            "semantic_type": "x",
            "explanation": None,
            "pattern": None,
            "semantic_confidence": None,
        },
    ]
    assert (
        semantic_bwb.update_edge_classifications(store, batch, "2026-10-01T00:00:00Z")
        == 1
    )
    doc = _edge_doc(store, "e1")
    # MERGE: the keys it had in byte order, then the new ones
    assert list(doc) == [
        "confidence",
        "meta",
        "relation",
        "source",
        "status",
        "semantic_type",
        "explanation",
        "updated_at",
    ]
    assert doc["meta"] == {
        "end": 5,
        "semantic_confidence": 0.7,
        "semantic_pattern": "van toepassing",
        "start": 1,
    }
    assert list(doc["meta"]) == sorted(doc["meta"])
    assert doc["updated_at"] == "2026-10-01T00:00:00Z"
    assert "updated_at" not in _edge_doc(store, "e2")
    # the same again changes nothing
    assert semantic_bwb.update_edge_classifications(store, batch, "2026-10-02") == 0
    # a classification that goes away is written as null
    batch[0] = {**batch[0], "semantic_type": None, "pattern": None}
    assert semantic_bwb.update_edge_classifications(store, batch[:1], "2026-10-03") == 1
    doc = _edge_doc(store, "e1")
    assert doc["semantic_type"] is None
    assert doc["meta"]["semantic_pattern"] is None
    assert doc["updated_at"] == "2026-10-03"
    assert list(doc) == sorted(doc)
    # an edge twice in a batch: both written, the last one stays
    twice = [{**batch[0], "semantic_type": "a"}, {**batch[0], "semantic_type": "b"}]
    assert semantic_bwb.update_edge_classifications(store, twice, None) == 2
    assert _edge_doc(store, "e1")["semantic_type"] == "b"


# ── Staatsblad and Staatscourant ─────────────────────────────────────────────


_LONG = "Nota van toelichting. " * 10


def _publications(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("bwbr1", "instrument", bwb_id="BWBR1", citation_title="Wet milieu"),
            _node(
                "bwbr2",
                "instrument",
                bwb_id="BWBR2",
                citation_title="Wet milieubeheer",
            ),
            # as long as bwbr2's title and also named: the key settles it
            _node(
                "bwbr0", "instrument", bwb_id="BWBR0", citation_title="Wet beheerstaken"
            ),
            _node("bwbr4", "instrument", bwb_id="BWBR4", citation_title="Wet"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node(
                "stb-1",
                "document",
                source=SOURCE_STAATSBLAD,
                bwb_id="BWBR2",
                text=_LONG,
                title="Besluit",
            ),
            _node(
                "stb-2",
                "document",
                source=SOURCE_STAATSBLAD,
                text=_LONG,
                title="Wijziging van de WET MILIEUBEHEER en de Wet beheerstaken",
            ),
            _node(
                "stb-3",
                "document",
                source=SOURCE_STAATSBLAD,
                bwb_id=None,
                text=_LONG,
                title="Iets over de Wet milieu",
            ),
            _node(
                "stb-4",
                "document",
                source=SOURCE_STAATSBLAD,
                bwb_id="BWBR1",
                text="kort",
            ),
            _node(
                "stb-5",
                "document",
                source=SOURCE_STAATSBLAD,
                bwb_id="BWBR77",
                text=_LONG,
            ),
            _node("stb-6", "document", source=SOURCE_STAATSBLAD, text=_LONG),
            _node(
                "stcrt-1",
                "document",
                source=SOURCE_STAATSCOURANT,
                bwb_id="BWBR1",
                date="2026-01-01",
                text="Regeling op grond van BWBR0000004. " * 4,
            ),
            _node(
                "stcrt-2",
                "document",
                source=SOURCE_STAATSCOURANT,
                date="2026-03-01",
                title="Regeling Wet milieubeheer",
                text="BWBR2 " * 30,
            ),
            _node(
                "stcrt-3",
                "document",
                source=SOURCE_STAATSCOURANT,
                title="Wet",  # too short a title
                date="2025-01-01",
                text="kort",
            ),
            _node(
                "stcrt-4",
                "document",
                source=SOURCE_STAATSCOURANT,
                title="Regeling over de Wet",
                text="y" * 101,
            ),
        ],
    )


def test_staatsblad_matches_by_bwb_id_then_by_the_longest_title(
    store: GraphStore,
) -> None:
    _publications(store)
    assert semantic_bwb.staatsblad_instrument_matches(store) == [
        {
            "pub_id": "documents/stb-1",
            "pub_key": "stb-1",
            "inst_id": "instruments/bwbr2",
            "inst_key": "bwbr2",
            "match_type": "bwb_id",
        },
        {
            "pub_id": "documents/stb-2",
            "pub_key": "stb-2",
            "inst_id": "instruments/bwbr0",
            "inst_key": "bwbr0",
            "match_type": "title",
        },
        {
            "pub_id": "documents/stb-3",
            "pub_key": "stb-3",
            "inst_id": "instruments/bwbr1",
            "inst_key": "bwbr1",
            "match_type": "title",
        },
    ]


def test_staatscourant_matches_and_texts_since_a_date(store: GraphStore) -> None:
    _publications(store)
    rows = semantic_bwb.staatscourant_instrument_matches(store, None)
    assert [(r["pub_key"], r["inst_key"], r["match_type"]) for r in rows] == [
        ("stcrt-1", "bwbr1", "bwb_id"),
        ("stcrt-2", "bwbr2", "title"),
        # "Wet" is too short a citation title to match
    ]
    rows = semantic_bwb.staatscourant_instrument_matches(store, "2026-02-01")
    assert [r["pub_key"] for r in rows] == ["stcrt-2"]
    assert semantic_bwb.staatscourant_instrument_matches(store, "") == (
        semantic_bwb.staatscourant_instrument_matches(store, None)
    )
    texts = list(semantic_bwb.staatscourant_texts(store, None))
    assert [t["pub_key"] for t in texts] == ["stcrt-1", "stcrt-2", "stcrt-4"]
    assert list(texts[0]) == ["pub_id", "pub_key", "text"]
    # a publication without a date is before every date
    assert [
        t["pub_key"] for t in semantic_bwb.staatscourant_texts(store, "2026-01-01")
    ] == [
        "stcrt-1",
        "stcrt-2",
    ]


# ── EUR-Lex ──────────────────────────────────────────────────────────────────


def test_eu_references_of_bwb_regulations(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("r2", "instrument", source=SOURCE_BWB, bwb_id="R2", celex_refs=["A"]),
            _node(
                "r1",
                "instrument",
                source=SOURCE_BWB,
                bwb_id="R1",
                celex_refs=[],
                implements_celex=["B", "C"],
            ),
            _node("r3", "instrument", source=SOURCE_BWB, bwb_id="R3", celex_refs=[]),
            _node("r4", "instrument", source="x", bwb_id="R4", celex_refs=["A"]),
        ],
    )
    assert list(semantic_eu.eu_references(store)) == [
        # an empty list is truthy: it stays
        {"bwb_id": "R1", "named": [], "implements": ["B", "C"]},
        {"bwb_id": "R2", "named": ["A"], "implements": []},
    ]


def test_national_measures_are_the_payloads(store: GraphStore) -> None:
    store.insert_raw_sources(
        [
            raw_source_doc(
                source=SOURCE_EURLEX,
                kind=RAW_KIND_EU_NIM,
                external_id="b",
                payload_json={"celex": ["B"], "z": 1, "a": 2},
            ),
            raw_source_doc(
                source=SOURCE_EURLEX,
                kind=RAW_KIND_EU_NIM,
                external_id="a",
                payload_json=[{"celex": ["A"]}],
            ),
            raw_source_doc(source=SOURCE_EURLEX, kind=RAW_KIND_EU_NIM, external_id="c"),
            raw_source_doc(
                source=SOURCE_EURLEX,
                kind="other",
                external_id="d",
                payload_json={"celex": ["D"]},
            ),
        ]
    )
    measures = list(semantic_eu.national_measures(store))
    assert sorted(map(str, measures)) == sorted(
        [str({"celex": ["B"], "z": 1, "a": 2}), str([{"celex": ["A"]}])]
    )
    payload = next(m for m in measures if isinstance(m, dict))
    assert list(payload) == ["celex", "z", "a"]  # as retrieved


def test_regulations_of_publications_once_each(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node(
                "r2",
                "instrument",
                source=SOURCE_BWB,
                bwb_id="R2",
                enacted_publication="stb-1",
            ),
            _node(
                "r1",
                "instrument",
                source=SOURCE_BWB,
                bwb_id="R1",
                enacted_publication="stb-2",
            ),
            _node(
                "r3",
                "instrument",
                source="x",
                bwb_id="R3",
                enacted_publication="stb-1",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _node("v1", "av", bwb_id="R9", origin_publication={"id": "stb-2"}),
            _node("v2", "av", bwb_id="R2", origin_publication={"id": "stb-1"}),
            _node("v3", "av", bwb_id="R9", origin_publication={"id": "stb-2"}),
            _node("v4", "av", bwb_id="R8", origin_publication={"id": "stb-1"}),
            _node("v5", "av", origin_publication={"id": "stb-1"}),
            _node("v6", "av", bwb_id="R7", origin_publication={"id": "stb-3"}),
        ],
    )
    rows = list(semantic_eu.regulations_of_publications(store, ["stb-1", "stb-2"]))
    assert rows == [
        ["stb-2", "R1"],  # the regulations, by key
        ["stb-1", "R2"],
        ["stb-1", None],  # then the versions' pairs, sorted (null first)
        ["stb-1", "R8"],
        ["stb-2", "R9"],
    ]


# ── short titles ─────────────────────────────────────────────────────────────


def test_update_abbreviations_sets_and_removes(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("a", "instrument", title="A", short_title="Old", bwb_id="BWBRA"),
            _node("b", "instrument", title="B", short_title="BW", aliases=["BW"]),
            _node("c", "instrument", title="C", short_title="X", aliases=["X"]),
            _node("d", "instrument", zeta=1, title="D"),
        ],
    )
    rows = [
        {"key": "a", "short_title": "Awb", "aliases": ["Awb", "AWB"]},
        {"key": "b", "short_title": "BW", "aliases": ["BW"]},  # unchanged
        {"key": "c", "short_title": None, "aliases": []},  # both go
        {"key": "d", "short_title": "D", "aliases": None},
        {"key": "missing", "short_title": "M", "aliases": ["M"]},
    ]
    assert normalize_bwb.update_abbreviations(store, rows) == 3
    a = _props(store, "instruments", "a")
    assert a == {
        "aliases": ["Awb", "AWB"],
        "bwb_id": "BWBRA",
        "short_title": "Awb",
        "title": "A",
    }
    assert list(a) == sorted(a)
    assert _props(store, "instruments", "c") == {"title": "C"}
    d = _props(store, "instruments", "d")
    assert list(d.items()) == [("short_title", "D"), ("title", "D"), ("zeta", 1)]
    assert normalize_bwb.update_abbreviations(store, rows) == 0
    assert normalize_bwb.update_abbreviations(store, []) == 0


def test_the_abbreviation_goes_to_the_instrument_and_its_articles(
    store: GraphStore,
) -> None:
    """BE-8: EVRM (a treaty of the BWB, by bwb_id) and AVG (an EU act, by celex): the same
    value on the law (``abbreviation``) and its articles (``instrument_abbreviation``)."""
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node(
                "bwbv0001000", "instrument", bwb_id="BWBV0001000", short_title="EVRM"
            ),
            _node("32016r0679", "instrument", celex="32016R0679", title="AVG-titel"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("bwbv0001000_8", "article", bwb_id="BWBV0001000", article_number="8"),
            _node("32016r0679_6", "article", celex="32016R0679", article_number="6"),
            _node("other_1", "article", bwb_id="BWBR0001854", article_number="1"),
        ],
    )
    rows = [
        {"key": "bwbv0001000", "abbreviation": "EVRM"},
        {"key": "32016r0679", "abbreviation": "AVG"},
    ]
    assert normalize_bwb.update_instrument_abbreviations(store, rows) == 4
    assert _props(store, "instruments", "bwbv0001000")["abbreviation"] == "EVRM"
    assert _props(store, "instruments", "32016r0679")["abbreviation"] == "AVG"
    art8 = _props(store, "articles", "bwbv0001000_8")
    assert art8["instrument_abbreviation"] == "EVRM"
    assert list(art8) == sorted(art8)  # D11
    assert _props(store, "articles", "32016r0679_6")["instrument_abbreviation"] == "AVG"
    assert "instrument_abbreviation" not in _props(store, "articles", "other_1")
    assert normalize_bwb.update_instrument_abbreviations(store, rows) == 0
    # an abbreviation that is gone goes from the law and its articles
    gone = [{"key": "bwbv0001000", "abbreviation": None}]
    assert normalize_bwb.update_instrument_abbreviations(store, gone) == 2
    assert "abbreviation" not in _props(store, "instruments", "bwbv0001000")
    assert "instrument_abbreviation" not in _props(store, "articles", "bwbv0001000_8")
