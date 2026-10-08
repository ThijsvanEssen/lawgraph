"""A judgment as a neighbour without its text, on a real PostgreSQL: ``lg_judgment_light``
kept by the triggers on every write of ``judgments``, filled by ``semantic graph-light``
for the judgments written before them, and read by the neighbours, the neighbourhood and the
paths instead of the props of the judgment."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore
from lawgraph.db.queries import judgment_light
from lawgraph.db.queries import nodes as node_queries
from lawgraph.db.queries.paths import get_paths

JUDGMENT = "judgments/ecli_nl_hr_2020_1"
ARTICLE = "articles/w_1"


def _judgment(key: str = "ecli_nl_hr_2020_1", **props: Any) -> dict[str, Any]:
    return {
        "_key": key,
        "type": "judgment",
        "labels": [],
        "props": {
            "ecli": key.upper().replace("_", ":"),
            "text": "De hele tekst. " * 100,
            "court": "Hoge Raad",
            "summary": "Huur. " * 100,
            "paragraphs": [{"n": 1, "text": "r.o. 1"}],
            "date": "2020-01-31",
            "unresolved_appeal_targets": [{"court": "Hof"}],
            "case_number": "19/00001",
            "stub": False,
            **props,
        },
    }


def _light(store: GraphStore) -> dict[str, Any]:
    return {
        row["id"]: row["props"]
        for row in store.query("SELECT id, props FROM lg_judgment_light")
    }


def _cites(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles", [{"_key": "w_1", "type": "article", "labels": [], "props": {}}]
    )
    store.bulk_insert_or_update_edges(
        [
            {
                "_key": "r1",
                "_from": JUDGMENT,
                "_to": ARTICLE,
                "relation": "REFERS_TO",
                "source": "rechtspraak",
                "status": "canoniek",
                "meta": {},
            }
        ]
    )


def test_a_judgment_written_is_kept_light(store: GraphStore) -> None:
    """The props a neighbour shows, in their stored order, its summary as long as a preview
    needs; no text, no paragraphs; kept again when the judgment changes, and gone with it."""
    store.bulk_insert_or_update_nodes("judgments", [_judgment()])
    (light,) = _light(store).values()
    assert list(light) == ["ecli", "court", "summary", "date", "case_number", "stub"]
    assert len(light["summary"]) == 401
    assert light["court"] == "Hoge Raad"

    store.bulk_insert_or_update_nodes(
        "judgments", [_judgment(court="Rechtbank Amsterdam", translation_of="ECLI:X")]
    )
    (light,) = _light(store).values()
    assert light["court"] == "Rechtbank Amsterdam"
    assert light["translation_of"] == "ECLI:X"

    store.execute("DELETE FROM judgments WHERE id = %(id)s", {"id": JUDGMENT})
    assert _light(store) == {}
    # keeping it raises no data version of its own
    assert not list(
        store.query(
            "SELECT 1 FROM lg_data_version WHERE collection = 'lg_judgment_light'"
        )
    )


def test_the_judgments_written_before_are_filled(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``semantic graph-light`` keeps those without (in batches); with ``--all`` every
    judgment again."""
    from lawgraph.pipelines.semantic import graph_light

    store.bulk_insert_or_update_nodes(
        "judgments", [_judgment(f"ecli_nl_hr_2020_{n}") for n in range(1, 6)]
    )
    kept = _light(store)
    store.execute("DELETE FROM lg_judgment_light WHERE id <> %(id)s", {"id": JUDGMENT})
    store.execute(
        'UPDATE lg_judgment_light SET props = \'{"ecli": "old"}\' WHERE id = %(id)s',
        {"id": JUDGMENT},
    )
    monkeypatch.setattr(judgment_light, "BATCH", 2)
    assert judgment_light.fill_judgment_light(store) == 4
    assert _light(store)[JUDGMENT] == {"ecli": "old"}  # had one: left
    assert graph_light.main(["--all"]).updated == 5
    assert _light(store) == kept


def test_a_neighbour_judgment_is_read_light(store: GraphStore) -> None:
    """The neighbours, the neighbourhood and the paths read a judgment from
    ``lg_judgment_light``, not from its props; one not kept there yet from its props, without
    its text."""
    store.bulk_insert_or_update_nodes("judgments", [_judgment()])
    _cites(store)
    # what is kept is what is read: a judgment kept otherwise shows as kept
    store.execute(
        'UPDATE lg_judgment_light SET props = \'{"ecli": "kept"}\' WHERE id = %(id)s',
        {"id": JUDGMENT},
    )
    data = node_queries.get_node_with_neighbors(store, "articles", "w_1")
    (entry,) = [e for bucket in data.buckets for e in bucket.entries]
    assert entry.doc["props"] == {"ecli": "kept"}
    around = node_queries.get_node_neighborhood(store, "articles", "w_1", depth=1)
    assert [n["props"] for n in around["nodes"] if n["_id"] == JUDGMENT] == [
        {"ecli": "kept"}
    ]
    path = get_paths(store, [ARTICLE, JUDGMENT], 1)
    assert [n["props"] for n in path["nodes"] if n["_id"] == JUDGMENT] == [
        {"ecli": "kept"}
    ]

    store.execute("DELETE FROM lg_judgment_light")
    (entry,) = [
        e
        for bucket in node_queries.get_node_with_neighbors(
            store, "articles", "w_1"
        ).buckets
        for e in bucket.entries
    ]
    assert entry.doc["props"]["unresolved_appeal_targets"] == [{"court": "Hof"}]
    assert "text" not in entry.doc["props"]

    # the judgment itself keeps all it has
    own = node_queries.get_node_with_neighbors(store, "judgments", "ecli_nl_hr_2020_1")
    assert own.node["props"]["text"].startswith("De hele tekst.")
