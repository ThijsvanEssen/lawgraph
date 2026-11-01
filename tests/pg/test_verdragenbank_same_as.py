"""``semantic verdragenbank``: ``props.same_as`` of a treaty names its BWB text, by which the
list of instruments has the treaty once, and a run that finds nothing new writes nothing."""

from __future__ import annotations

from lawgraph.db import GraphStore
from lawgraph.db.queries import instruments
from lawgraph.pipelines.semantic.verdragenbank import VerdragenbankSemanticPipeline


def _treaty(key: str, **props: object) -> dict[str, object]:
    return {
        "key": key,
        "type": "instrument",
        "labels": [],
        "props": {"kind": "verdrag", "citation_title": key, **props},
    }


def _version(store: GraphStore) -> str:
    return store.data_version()


def test_a_treaty_names_its_text_and_loses_it_when_the_number_goes(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _treaty("bwbv0001234", bwb_id="BWBV0001234", treaty_number="001234"),
            _treaty("verdrag_001", treaty_number="001234"),
            _treaty("verdrag_002", treaty_number="009999"),
        ],
    )
    VerdragenbankSemanticPipeline(store=store).run()
    same_as = (
        "SELECT key, same_as FROM instruments WHERE key LIKE 'verdrag%%' ORDER BY key"
    )
    assert [tuple(row.values()) for row in store.query(same_as)] == [
        ("verdrag_001", "instruments/bwbv0001234"),
        ("verdrag_002", None),
    ]
    listed = instruments.get_instruments_list(store, validity="all")
    assert sorted(item["key"] for item in listed["items"]) == [
        "bwbv0001234",
        "verdrag_002",
    ]

    version = _version(store)
    again = VerdragenbankSemanticPipeline(store=store).run()
    assert (again.created, again.updated) == (0, 0)
    assert _version(store) == version

    store.bulk_insert_or_update_nodes(
        "instruments", [_treaty("bwbv0001234", treaty_number="005555")]
    )
    VerdragenbankSemanticPipeline(store=store).run()
    assert [tuple(row.values()) for row in store.query(same_as)][0] == (
        "verdrag_001",
        None,
    )
