"""BWB amendments pipeline: publication → AMENDS/INTRODUCES/REPEALS → article."""

from __future__ import annotations

from collections.abc import Iterator
from functools import partial
from typing import Any

import pytest

from lawgraph.config.constants import (
    RELATION_AMENDS,
    RELATION_ESTABLISHES,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_REPEALS,
)
from lawgraph.core.bwb_xml import article_version_key, publication_key
from lawgraph.core.models import make_node_key
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.pipelines.semantic import bwb_amendments
from lawgraph.pipelines.semantic.bwb_amendments import BWBAmendmentsSemanticPipeline
from tests.asserts import show_items
from tests.fakes import (
    InMemoryStore,
    count_calls,
    patch_edge_removals,
    patch_rijkswet_dossiers,
)

BWB = "BWBR0001840"


def _pub(number: str, *, dossiers: list[str] | None = None, year: int = 2019) -> dict:
    return {
        "id": f"stb-{year}-{number}",
        "kind": "Stb",
        "year": year,
        "number": number,
        "effect": None,
        "signed": f"{year}-01-15",
        "published": f"{year}-01-20",
        "dossiers": dossiers or [],
    }


def _version(
    stam_id: str,
    versie_id: str,
    *,
    effect: str | None = "wijziging",
    valid_from: str | None = "2019-02-01",
    origin: dict | None = None,
    commencement: dict | None = None,
    bwb_id: str = BWB,
) -> dict[str, Any]:
    """A row as returned by the versions query (already projected)."""
    origin = origin or _pub("33")
    return {
        "key": article_version_key(bwb_id, stam_id, versie_id),
        "bwb_id": bwb_id,
        "stam_id": stam_id,
        "effect": effect,
        "valid_from": valid_from,
        "source_publication": origin["id"].replace("stb-", "Stb.", 1),
        "origin": origin,
        "commencement": commencement,
    }


def _article_key(bwb_id: str, stam_id: str) -> str:
    return make_node_key(bwb_id, "art", stam_id)


class _Store(InMemoryStore):
    """The dossiers of the graph, the article versions that amend, the stored articles
    ((bwb_id, stam_id), all of the versions by default) and the regulations' dossiers."""

    def __init__(
        self,
        versions: list[dict[str, Any]],
        *,
        articles: list[tuple[str, str]] | None = None,
        dossiers: set[str] | None = None,
        regulations: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__({"dossiers": [{"key": key} for key in dossiers or ()]})
        self.versions = versions
        self.articles = (
            articles
            if articles is not None
            else sorted({(v["bwb_id"], v["stam_id"]) for v in versions})
        )
        self.regulations = regulations or []
        self.article_queries = 0


@pytest.fixture(autouse=True)
def _amendment_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queries of the pipeline, answered from the fake store."""

    def amending_article_versions(store: _Store) -> Iterator[dict[str, Any]]:
        # the real query sorts by article identity
        return iter(sorted(store.versions, key=lambda r: (r["bwb_id"], r["stam_id"])))

    def articles_by_identity(
        store: _Store, bwb_ids: list[str], stam_ids: list[str]
    ) -> Iterator[dict[str, Any]]:
        store.article_queries += 1
        return iter(  # every combination of the two lists, like the real query
            {"key": _article_key(b, s), "bwb_id": b, "stam_id": s}
            for b, s in store.articles
            if b in bwb_ids and s in stam_ids
        )

    monkeypatch.setattr(
        semantic_bwb, "amending_article_versions", amending_article_versions
    )
    monkeypatch.setattr(semantic_bwb, "articles_by_identity", articles_by_identity)
    monkeypatch.setattr(
        semantic_bwb,
        "regulation_dossier_numbers",
        lambda store: iter(store.regulations),
    )
    patch_rijkswet_dossiers(monkeypatch)
    patch_edge_removals(monkeypatch)


def _run(store: _Store, chunk: int | None = None):
    pipeline = BWBAmendmentsSemanticPipeline(store=store)
    if chunk is not None:
        pipeline._CHUNK = chunk
    return pipeline.run()


def _edges(store: _Store, relation: str) -> list[dict[str, Any]]:
    return [e for e in store.edges.values() if e["relation"] == relation]


def _art(stam_id: str, bwb_id: str = BWB) -> str:
    return f"articles/{_article_key(bwb_id, stam_id)}"


def test_effect_decides_the_relation_and_edge_carries_the_version() -> None:
    store = _Store(
        [
            _version("1", "a", effect="nieuw", origin=_pub("1")),
            _version("2", "b", effect="wijziging", origin=_pub("2")),
            _version("3", "c", effect="tekstplaatsing-wijziging", origin=_pub("3")),
            _version("4", "d", effect="vervallen", origin=_pub("4")),
        ]
    )

    result = _run(store)

    assert result.created == 3  # a republication (tekstplaatsing) amends nothing
    (intro,) = _edges(store, RELATION_INTRODUCES)
    assert intro["from_id"] == f"instruments/{publication_key('stb-2019-1')}"
    assert intro["to_id"] == _art("1")
    assert intro["meta"] == {
        "effective_date": "2019-02-01",
        "article_version": article_version_key(BWB, "1", "a"),
        "effect": "nieuw",
        "source_publication": "Stb.2019-1",
    }
    assert {e["to_id"] for e in _edges(store, RELATION_AMENDS)} == {_art("2")}
    assert [e["to_id"] for e in _edges(store, RELATION_REPEALS)] == [_art("4")]
    failing = [e for e in store.edges.values() if e["confidence"] != 1.0]
    assert not failing, show_items(failing)


def test_a_new_regulation_is_established_by_the_publication_that_enacted_it() -> None:
    """The Cyberbeveiligingswet: its articles came with Stb. 2026, 187 (effect
    ``nieuwe-regeling``), legislated in 36764; the act changed the Telecommunicatiewet in
    the same publication."""
    cbw, tw = "BWBR0052872", "BWBR0009950"
    enacted = {
        **_pub("187", dossiers=["36764"], year=2026),
        "effect": "nieuwe-regeling",
    }
    store = _Store(
        [
            _version("1", "a", effect="nieuwe-regeling", origin=enacted, bwb_id=cbw),
            _version("16", "b", effect="nieuwe-regeling", origin=enacted, bwb_id=cbw),
            _version("7", "c", effect="wijziging", origin=enacted, bwb_id=tw),
        ],
        dossiers={"36764"},
    )

    _run(store)

    stb = f"instruments/{publication_key('stb-2026-187')}"
    established = _edges(store, RELATION_ESTABLISHES)
    assert {e["to_id"] for e in established} == {_art("1", cbw), _art("16", cbw)}
    assert {e["from_id"] for e in established} == {stb}
    assert established[0]["meta"]["effect"] == "nieuwe-regeling"
    # an enactment is no change of the law: no AMENDS or INTRODUCES into the Cbw
    assert [e["to_id"] for e in _edges(store, RELATION_AMENDS)] == [_art("7", tw)]
    assert _edges(store, RELATION_INTRODUCES) == []
    assert [e["to_id"] for e in _edges(store, RELATION_LEGISLATED_IN)] == [
        "dossiers/36764"
    ]


def test_documents_become_instruments_with_their_metadata() -> None:
    store = _Store(
        [
            _version(
                "1",
                "a",
                origin=_pub("33", dossiers=["35786"]),
                commencement=_pub("99", year=2020),
            )
        ]
    )

    _run(store)

    origin = store.nodes["instruments"][publication_key("stb-2019-33")]
    assert origin["type"] == "instrument"
    assert origin["props"] == {
        "display_name": "Stb. 2019, 33",
        # a publication is no regulation: its own kind, and a name to sort it by
        "citation_title": "Stb. 2019, 33",
        "kind": "publicatie",
        "jurisdiction": "nl",
        "source": "bwb",
        "publication_kind": "Stb",
        "publication_year": 2019,
        "publication_number": "33",
        "date_signed": "2019-01-15",
        "date_published": "2019-01-20",
        "dossier_numbers": ["35786"],
        "stub": False,  # a node that is written says that it is not a stub
    }
    # the commencement publication exists as an instrument, but amends nothing
    assert publication_key("stb-2020-99") in store.nodes["instruments"]
    assert (
        "dossier_numbers"
        not in store.nodes["instruments"][publication_key("stb-2020-99")]["props"]
    )
    failing = [
        e
        for e in store.edges.values()
        if e["from_id"].endswith(publication_key("stb-2020-99"))
    ]
    assert not failing, show_items(failing)


def test_one_edge_per_publication_article_and_kind_keeps_the_earliest_date() -> None:
    later = _version("1", "b", valid_from="2019-06-01")
    earlier = _version("1", "a", valid_from="2019-02-01")
    undated = _version("1", "c", valid_from=None)
    other_kind = _version("1", "d", effect="vervallen", valid_from="2020-01-01")
    store = _Store([later, undated, earlier, other_kind])

    # chunk size 1: the versions of one article must still be handled together
    _run(store, chunk=1)

    (amends,) = _edges(store, RELATION_AMENDS)
    assert amends["meta"]["effective_date"] == "2019-02-01"
    assert amends["meta"]["article_version"] == article_version_key(BWB, "1", "a")
    assert len(_edges(store, RELATION_REPEALS)) == 1  # a different kind: own edge
    assert len(store.edges) == 2


def test_other_documents_of_the_same_article_get_their_own_edge() -> None:
    store = _Store(
        [_version("1", "a", origin=_pub("1")), _version("1", "b", origin=_pub("2"))]
    )

    _run(store)

    assert len(_edges(store, RELATION_AMENDS)) == 2


def test_unknown_effect_and_missing_article_are_skipped() -> None:
    store = _Store(
        [
            _version("1", "a"),
            _version("2", "b", effect=None),
            _version("3", "c", effect="onbekend"),
            _version("9", "d"),  # article 9 is not in the graph
        ],
        articles=[(BWB, "1"), (BWB, "2"), (BWB, "3")],
    )

    result = _run(store)

    assert result.created == 1
    assert result.skipped == 3
    assert [e["to_id"] for e in store.edges.values()] == [_art("1")]


def test_article_identity_is_the_pair_not_each_id_alone() -> None:
    """The bulk lookup filters ids and stam ids separately (a cartesian product)."""
    other = "BWBR0002222"
    store = _Store(
        [_version("1", "a"), _version("2", "b", bwb_id=other)],
        # BWB has stam 1 only and OTHER has stam 2 only: (BWB, 2) must not resolve
        articles=[(BWB, "1"), (other, "2"), (other, "1"), (BWB, "5")],
    )

    _run(store)

    assert {e["to_id"] for e in store.edges.values()} == {
        _art("1"),
        _art("2", bwb_id=other),
    }


def test_a_chunk_leaves_the_edges_of_the_articles_of_another_chunk_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lookup of a chunk also returns articles of other chunks (its two id lists cross):
    those are no targets of the chunk, or it would remove their amendment edges, which a
    long run has written already (here: every edge at once)."""
    monkeypatch.setattr(bwb_amendments, "EdgeWriter", partial(EdgeWriter, batch_size=1))
    other = "BWBR0002222"
    store = _Store(
        [
            # chunk 1: two versions of (BWB, 1)
            _version("1", "a"),
            _version("1", "b", origin=_pub("34")),
            # chunk 2: (BWB, 2) and (OTHER, 1); its lookup crosses into (BWB, 1)
            _version("2", "c"),
            _version("1", "d", bwb_id=other),
        ],
        articles=[(BWB, "1"), (BWB, "2"), (other, "1")],
    )

    _run(store, chunk=2)

    assert sorted(
        e["to_id"] for e in store.edges.values() if e["to_id"].startswith("articles/")
    ) == [
        _art("1"),
        _art("1"),
        _art("2"),
        _art("1", bwb_id=other),
    ]


def test_publication_and_regulation_link_to_existing_dossiers_only() -> None:
    store = _Store(
        [_version("1", "a", origin=_pub("33", dossiers=["35786", "11111"]))],
        dossiers={make_node_key("35786"), make_node_key("22222")},
        regulations=[
            {"key": make_node_key(BWB), "dossiers": ["35786", "22222", "33333"]}
        ],
    )

    _run(store)

    links = {(e["from_id"], e["to_id"]) for e in _edges(store, RELATION_LEGISLATED_IN)}
    dossier = lambda n: f"dossiers/{make_node_key(n)}"  # noqa: E731
    assert links == {
        (f"instruments/{publication_key('stb-2019-33')}", dossier("35786")),
        (f"instruments/{make_node_key(BWB)}", dossier("35786")),
        (f"instruments/{make_node_key(BWB)}", dossier("22222")),
    }
    assert {
        e["meta"]["dossier_number"] for e in _edges(store, RELATION_LEGISLATED_IN)
    } == {
        "35786",
        "22222",
    }


def test_a_rijkswet_dossier_is_named_by_its_number_alone() -> None:
    """Stb. 2014, 10, the Rijkswet changing the Paspoortwet, names 33440: the dossier
    33440-(R1990)."""
    store = _Store(
        [_version("1", "a", origin=_pub("10", dossiers=["33440"], year=2014))]
    )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            {
                "key": "33440_r1990",
                "type": "dossier",
                "labels": [],
                "props": {"label": "33440-(R1990)", "number": "33440"},
            }
        ],
    )

    _run(store)

    (link,) = _edges(store, RELATION_LEGISLATED_IN)
    assert (link["from_id"], link["to_id"]) == (
        f"instruments/{publication_key('stb-2014-10')}",
        "dossiers/33440_r1990",
    )
    assert link["meta"] == {"dossier_number": "33440"}


def test_dossiers_of_a_publication_are_merged_across_versions_and_chunks() -> None:
    store = _Store(
        [
            _version("1", "a", origin=_pub("33")),  # no dossier on this occurrence
            _version("2", "b", origin=_pub("33", dossiers=["35786"])),
            _version("3", "c", origin=_pub("33", dossiers=["35786", "40000"])),
        ],
        dossiers={make_node_key("35786"), make_node_key("40000")},
    )

    _run(store, chunk=1)  # every version in its own chunk

    props = store.nodes["instruments"][publication_key("stb-2019-33")]["props"]
    assert props["dossier_numbers"] == ["35786", "40000"]
    links = _edges(store, RELATION_LEGISLATED_IN)
    assert len(links) == 2  # each dossier linked once, not once per version


def test_is_idempotent() -> None:
    store = _Store(
        [_version("1", "a", origin=_pub("33", dossiers=["35786"]))],
        dossiers={make_node_key("35786")},
    )

    first, second = _run(store), _run(store)

    assert first.created == 2  # AMENDS + LEGISLATED_IN
    assert (second.created, second.updated) == (0, 2)
    assert len(store.edges) == 2


def test_store_calls_do_not_grow_with_the_number_of_versions() -> None:
    def build(n: int) -> _Store:
        versions = [
            _version(str(i), f"v{i}", origin=_pub(str(i % 7), dossiers=["35786"]))
            for i in range(n)
        ]
        return _Store(versions, dossiers={make_node_key("35786")})

    small, large = build(3), build(200)  # both fit in one chunk
    writes = ("existing_keys", "bulk_insert_or_update_nodes")
    small_calls, large_calls = count_calls(small, *writes), count_calls(large, *writes)

    _run(small)
    _run(large)

    assert len(_edges(large, RELATION_AMENDS)) == 200
    assert large.article_queries == small.article_queries
    assert large_calls == small_calls
    assert large.article_queries == 1
