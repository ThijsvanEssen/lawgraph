"""A run over records that did not change must not write the graph again."""

from __future__ import annotations

import re
from typing import Any

from lawgraph.db import ArangoStore
from tests.integration.seed import seed


def _revisions(store: ArangoStore, collection: str) -> dict[str, str]:
    aql = f"FOR d IN {collection} RETURN [d._key, d._rev]"
    return dict(store.query(aql))


def test_a_second_run_writes_nothing_and_says_so(database: str, cli: Any) -> None:
    store = ArangoStore()
    seed(store, documents=60, judgments=10, regulations=3)
    cli("normalize", "all")
    cli("semantic", "all")
    before = {
        name: _revisions(store, name)
        for name in ("cases", "decisions", "judgments", "articles", "edges")
    }
    assert all(before.values())

    second = cli("normalize", "tk-dossiers")
    cli("normalize", "rechtspraak")
    linked = cli("semantic", "rechtspraak")
    for name, revisions in before.items():
        assert _revisions(store, name) == revisions, name
    # one line to end a step, and it says so: for nodes and for the edges of a semantic step
    for done in (second, linked):
        assert re.search(r"Done in \S+: [\d,]+ unchanged\.", done.stderr), done.stderr[
            -400:
        ]


def test_a_changed_document_is_written_and_the_rest_is_left_alone(
    database: str,
) -> None:
    store = ArangoStore()
    docs = [
        {"_key": f"n{n}", "type": "case", "labels": ["TK"], "props": {"title": "a"}}
        for n in range(3)
    ]
    assert store.bulk_insert_or_update_nodes("cases", docs) == (3, 0)
    before = _revisions(store, "cases")

    docs[1] = docs[1] | {"props": {"title": "b"}}
    assert store.bulk_insert_or_update_nodes("cases", docs) == (0, 1)
    after = _revisions(store, "cases")
    assert after["n0"] == before["n0"] and after["n2"] == before["n2"]
    assert after["n1"] != before["n1"]
    assert store.db.collection("cases").get("n1")["props"]["title"] == "b"

    # The same key twice in one batch: the lookup does not see the write before it.
    new_and_twice = [
        {"_key": "n9", "type": "case", "labels": [], "props": {"title": "x"}},
        {"_key": "n9", "type": "case", "labels": [], "props": {"title": "y"}},
    ]
    store.bulk_insert_or_update_nodes("cases", new_and_twice)
    assert store.db.collection("cases").get("n9")["props"]["title"] == "y"
