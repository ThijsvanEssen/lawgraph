"""BWB amendments pipeline: publication → AMENDS/INTRODUCES/REPEALS → article."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_REPEALS,
)
from lawgraph.core.bwb_xml import article_version_key, publication_key
from lawgraph.core.models import make_node_key
from lawgraph.pipelines.semantic.bwb_amendments import BWBAmendmentsSemanticPipeline
from tests.conftest import _BaseFakeStore

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


class _FakeStore(_BaseFakeStore):
    def __init__(
        self,
        versions: list[dict[str, Any]],
        *,
        articles: list[tuple[str, str]] | None = None,
        dossiers: set[str] | None = None,
        regulations: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self.versions = versions
        # (bwb_id, stam_id) of every stored article; key = its node key
        self.articles = (
            articles
            if articles is not None
            else sorted({(v["bwb_id"], v["stam_id"]) for v in versions})
        )
        self.dossiers = dossiers or set()
        self.regulations = regulations or []
        self.nodes: dict[str, dict[str, Any]] = {}
        self.article_queries = 0
        self.existence_calls = 0
        self.node_writes = 0

    @staticmethod
    def article_key(bwb_id: str, stam_id: str) -> str:
        return make_node_key(bwb_id, "art", stam_id)

    def query(self, aql: str, bind_vars: dict | None = None, **_: Any):
        if "FOR v IN article_versions" in aql:
            # the real query sorts by article identity
            return iter(
                sorted(self.versions, key=lambda r: (r["bwb_id"], r["stam_id"]))
            )
        if "FOR a IN articles" in aql:
            self.article_queries += 1
            assert bind_vars is not None
            bwb_ids, stam_ids = set(bind_vars["bwb_ids"]), set(bind_vars["stam_ids"])
            return iter(  # cartesian IN filters, like AQL
                {"key": self.article_key(b, s), "bwb_id": b, "stam_id": s}
                for b, s in self.articles
                if b in bwb_ids and s in stam_ids
            )
        if "FOR i IN instruments" in aql:
            return iter(self.regulations)
        raise AssertionError(aql)

    def existing_keys(self, collection: str, keys) -> set[str]:
        assert collection == "dossiers"
        self.existence_calls += 1
        return set(keys) & self.dossiers

    def bulk_insert_or_update_nodes(self, collection: str, docs: list[dict]):
        assert collection == "instruments"
        self.node_writes += 1
        for doc in docs:
            old = self.nodes.get(doc["_key"], {"props": {}})
            self.nodes[doc["_key"]] = {**doc, "props": {**old["props"], **doc["props"]}}
        return len(docs), 0


def _run(store: _FakeStore, chunk: int | None = None):
    pipeline = BWBAmendmentsSemanticPipeline(store=store)
    if chunk is not None:
        pipeline._CHUNK = chunk
    return pipeline.run()


def _edges(store: _FakeStore, relation: str) -> list[dict[str, Any]]:
    return [e for e in store.edges.values() if e["relation"] == relation]


def _art(stam_id: str, bwb_id: str = BWB) -> str:
    return f"articles/{_FakeStore.article_key(bwb_id, stam_id)}"


def test_effect_decides_the_relation_and_edge_carries_the_version() -> None:
    store = _FakeStore(
        [
            _version("1", "a", effect="nieuw", origin=_pub("1")),
            _version("2", "b", effect="wijziging", origin=_pub("2")),
            _version("3", "c", effect="tekstplaatsing-wijziging", origin=_pub("3")),
            _version("4", "d", effect="vervallen", origin=_pub("4")),
        ]
    )

    result = _run(store)

    assert result.created == 4
    (intro,) = _edges(store, RELATION_INTRODUCES)
    assert intro["_from"] == f"instruments/{publication_key('stb-2019-1')}"
    assert intro["_to"] == _art("1")
    assert intro["meta"] == {
        "effective_date": "2019-02-01",
        "article_version": article_version_key(BWB, "1", "a"),
        "effect": "nieuw",
        "source_publication": "Stb.2019-1",
    }
    assert {e["_to"] for e in _edges(store, RELATION_AMENDS)} == {_art("2"), _art("3")}
    assert [e["_to"] for e in _edges(store, RELATION_REPEALS)] == [_art("4")]
    assert all(e["confidence"] == 1.0 for e in store.edges.values())


def test_documents_become_instruments_with_their_metadata() -> None:
    store = _FakeStore(
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

    origin = store.nodes[publication_key("stb-2019-33")]
    assert origin["type"] == "instrument"
    assert origin["props"] == {
        "display_name": "Stb. 2019, 33",
        "source": "bwb",
        "publication_kind": "Stb",
        "publication_year": 2019,
        "publication_number": "33",
        "date_signed": "2019-01-15",
        "date_published": "2019-01-20",
        "dossier_numbers": ["35786"],
    }
    # the commencement publication exists as an instrument, but amends nothing
    assert publication_key("stb-2020-99") in store.nodes
    assert "dossier_numbers" not in store.nodes[publication_key("stb-2020-99")]["props"]
    assert all(
        not e["_from"].endswith(publication_key("stb-2020-99"))
        for e in store.edges.values()
    )


def test_one_edge_per_publication_article_and_kind_keeps_the_earliest_date() -> None:
    later = _version("1", "b", valid_from="2019-06-01")
    earlier = _version("1", "a", valid_from="2019-02-01")
    undated = _version("1", "c", valid_from=None)
    other_kind = _version("1", "d", effect="vervallen", valid_from="2020-01-01")
    store = _FakeStore([later, undated, earlier, other_kind])

    # chunk size 1: the versions of one article must still be handled together
    _run(store, chunk=1)

    (amends,) = _edges(store, RELATION_AMENDS)
    assert amends["meta"]["effective_date"] == "2019-02-01"
    assert amends["meta"]["article_version"] == article_version_key(BWB, "1", "a")
    assert len(_edges(store, RELATION_REPEALS)) == 1  # a different kind: own edge
    assert len(store.edges) == 2


def test_other_documents_of_the_same_article_get_their_own_edge() -> None:
    store = _FakeStore(
        [_version("1", "a", origin=_pub("1")), _version("1", "b", origin=_pub("2"))]
    )

    _run(store)

    assert len(_edges(store, RELATION_AMENDS)) == 2


def test_unknown_effect_and_missing_article_are_skipped() -> None:
    store = _FakeStore(
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
    assert [e["_to"] for e in store.edges.values()] == [_art("1")]


def test_article_identity_is_the_pair_not_each_id_alone() -> None:
    """The bulk lookup filters ids and stam ids separately (a cartesian product)."""
    other = "BWBR0002222"
    store = _FakeStore(
        [_version("1", "a"), _version("2", "b", bwb_id=other)],
        # BWB has stam 1 only and OTHER has stam 2 only: (BWB, 2) must not resolve
        articles=[(BWB, "1"), (other, "2"), (other, "1"), (BWB, "5")],
    )

    _run(store)

    assert {e["_to"] for e in store.edges.values()} == {
        _art("1"),
        _art("2", bwb_id=other),
    }


def test_publication_and_regulation_link_to_existing_dossiers_only() -> None:
    store = _FakeStore(
        [_version("1", "a", origin=_pub("33", dossiers=["35786", "11111"]))],
        dossiers={make_node_key("35786"), make_node_key("22222")},
        regulations=[
            {"key": make_node_key(BWB), "dossiers": ["35786", "22222", "33333"]}
        ],
    )

    _run(store)

    links = {(e["_from"], e["_to"]) for e in _edges(store, RELATION_LEGISLATED_IN)}
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


def test_dossiers_of_a_publication_are_merged_across_versions_and_chunks() -> None:
    store = _FakeStore(
        [
            _version("1", "a", origin=_pub("33")),  # no dossier on this occurrence
            _version("2", "b", origin=_pub("33", dossiers=["35786"])),
            _version("3", "c", origin=_pub("33", dossiers=["35786", "40000"])),
        ],
        dossiers={make_node_key("35786"), make_node_key("40000")},
    )

    _run(store, chunk=1)  # every version in its own chunk

    props = store.nodes[publication_key("stb-2019-33")]["props"]
    assert props["dossier_numbers"] == ["35786", "40000"]
    links = _edges(store, RELATION_LEGISLATED_IN)
    assert len(links) == 2  # each dossier linked once, not once per version


def test_is_idempotent() -> None:
    store = _FakeStore(
        [_version("1", "a", origin=_pub("33", dossiers=["35786"]))],
        dossiers={make_node_key("35786")},
    )

    first, second = _run(store), _run(store)

    assert first.created == 2  # AMENDS + LEGISLATED_IN
    assert (second.created, second.updated) == (0, 2)
    assert len(store.edges) == 2


def test_store_calls_do_not_grow_with_the_number_of_versions() -> None:
    def build(n: int) -> _FakeStore:
        versions = [
            _version(str(i), f"v{i}", origin=_pub(str(i % 7), dossiers=["35786"]))
            for i in range(n)
        ]
        return _FakeStore(versions, dossiers={make_node_key("35786")})

    small, large = build(3), build(200)  # both fit in one chunk

    _run(small)
    _run(large)

    assert len(_edges(large, RELATION_AMENDS)) == 200
    assert (large.article_queries, large.existence_calls, large.node_writes) == (
        small.article_queries,
        small.existence_calls,
        small.node_writes,
    )
    assert large.article_queries == 1
