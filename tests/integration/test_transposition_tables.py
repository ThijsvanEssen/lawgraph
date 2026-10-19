"""Old law to new law for real: an excerpt of the transposition table of the new Wetboek van
Strafvordering (blg-1081574, as ``retrieve tk-transposition-tables`` stores it), the new law
read from its Staatsblad XML (``normalize staatsblad-laws``) and a few articles of the old
Sv, through ``semantic tk-transposition-tables``, the API and ``lawgraph succession-gaps``.

- A row that holds is a part of the ``TRANSPOSED_TO`` of its pair of articles.
- The API reads it both ways: on the old article where it went, on the new one where it came
  from.
- A row that does not hold, and an old article without a place, is a gap in the report.
- An edge no table gives any more goes.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_STAATSBLAD_LAW,
    RAW_KIND_TK_TRANSPOSITION_TABLE,
    RELATION_PART_OF,
    RELATION_TRANSPOSED_TO,
    SOURCE_STAATSBLAD,
    SOURCE_TK,
)
from lawgraph.db import EdgeWriter, GraphStore, RawSourceWriter, raw_source_doc
from tests.paths import FIXTURES

OLD_SV = "instruments/bwbr0001903"
TABLE = "blg-1081574"


def _lid(number: str) -> dict[str, Any]:
    return {
        "id": f"lid-{number}",
        "kind": "lid",
        "number": number,
        "start": 0,
        "end": 1,
    }


# number -> leden, repealed
_OLD_ARTICLES = {
    "1": ((), False),
    "126ee": ((), False),
    "126ff": (("1", "2", "3", "4"), False),
    "126ffa": (("1", "2", "3", "4"), False),
    "126zz": (("1",), False),  # on no page of the excerpt
    "127a": ((), True),
}


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            {"key": n, "type": "dossier", "labels": ["TK"], "props": {"number": n}}
            for n in ("36327", "36636")
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "key": "bwbr0001903",
                "type": "instrument",
                "labels": ["BWB"],
                "props": {
                    "bwb_id": "BWBR0001903",
                    "title": "Wetboek van Strafvordering",
                    "citation_title": "Wetboek van Strafvordering",
                    "kind": "wet",
                    "in_force": True,
                },
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            {
                "key": f"bwbr0001903_{number}",
                "type": "article",
                "labels": ["BWB", "Article"],
                "props": {
                    "bwb_id": "BWBR0001903",
                    "article_number": number,
                    "label": f"Artikel {number}",
                    "text": "…",
                    "parts": [_lid(n) for n in leden],
                    "repealed": repealed,
                    "position": position,
                },
            }
            for position, (number, (leden, repealed)) in enumerate(
                _OLD_ARTICLES.items()
            )
        ],
    )
    with EdgeWriter(store, what=None) as edges:
        for number in _OLD_ARTICLES:
            edges.add(
                f"articles/bwbr0001903_{number}",
                OLD_SV,
                RELATION_PART_OF,
                source="test",
            )
    with RawSourceWriter(store) as writer:
        for official in ("stb-2026-56", "stb-2026-57"):
            writer.add(
                raw_source_doc(
                    source=SOURCE_STAATSBLAD,
                    kind=RAW_KIND_STAATSBLAD_LAW,
                    external_id=official,
                    payload_text=(
                        FIXTURES / f"{official.replace('-', '_')}_excerpt.xml"
                    ).read_text(),
                    meta={"identifier": official},
                )
            )
        writer.add(
            raw_source_doc(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_TRANSPOSITION_TABLE,
                external_id=TABLE,
                payload_text=base64.b64encode(
                    (FIXTURES / "blg_1081574_excerpt.pdf").read_bytes()
                ).decode("ascii"),
                meta={"identifier": TABLE, "dossier": "36327", "encoding": "base64"},
            )
        )


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = GraphStore()
    _seed(store)
    cli("normalize", "staatsblad-laws")
    cli("semantic", "tk-transposition-tables")
    cli("semantic", "tk-transposition-tables")  # a second run changes nothing
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _transposed() -> dict[tuple[str, str], Any]:
    return {
        (row["from_id"], row["to_id"]): row["meta"]
        for row in GraphStore().query(
            "SELECT from_id, to_id, doc -> 'meta' AS meta FROM edges "
            "WHERE relation = %(r)s",
            {"r": RELATION_TRANSPOSED_TO},
        )
    }


def test_a_row_that_holds_is_a_part_of_the_edge_of_its_pair(client: TestClient) -> None:
    edges = _transposed()
    assert set(edges) == {
        ("articles/bwbr0001903_1", "articles/stb_2026_56_1_1_1"),
        ("articles/bwbr0001903_126ffa", "articles/stb_2026_56_2_8_6"),
    }
    assert edges[("articles/bwbr0001903_126ffa", "articles/stb_2026_56_2_8_6")] == {
        "basis": "transposition_table",
        "source": TABLE,
        "parts": [
            {"from": "1", "to": "2.8.6, 1"},
            {"from": "2", "to": "2.8.6, 1"},
            {"from": "3", "to": "2.8.6, 1"},
            {"from": "4", "to": "2.8.6, 2"},
        ],
    }


def test_the_api_reads_it_both_ways(client: TestClient) -> None:
    old = client.get("/api/articles/BWBR0001903/126ffa").json()
    (successor,) = old["successors"]
    assert successor["article"]["id"] == "articles/stb_2026_56_2_8_6"
    assert successor["article"]["article_number"] == "2.8.6"
    assert (successor["in_force"], successor["status"]) == (False, "vastgesteld")
    assert successor["parts"][-1] == {"old_part": "4", "new_place": "2.8.6, 2"}
    assert successor["source_url"] == (
        "https://zoek.officielebekendmakingen.nl/blg-1081574.html"
    )
    assert old["predecessors"] == []

    new = client.get("/api/articles/STB-2026-56/2.8.6").json()
    (predecessor,) = new["predecessors"]
    assert predecessor["article"]["id"] == "articles/bwbr0001903_126ffa"
    assert predecessor["in_force"] is True
    assert new["successors"] == []


def test_the_report_lists_what_does_not_hold(client: TestClient, cli: Any) -> None:
    out = cli("succession-gaps").stdout
    assert f"{TABLE} (dossier 36327): {OLD_SV} -> instruments/wet_stb_2026_56" in out
    assert "p. 4: art. 126ee: 2.8.4 [the new law has no such article]" in out
    assert "p. 4: art. 126ff 1: 2.8.5, 1 [the new law has no such article]" in out
    assert "art. 126zz [no row]" in out
    assert "art. 126ff [no row of it holds]" in out
    assert "art. 127a" not in out  # repealed
    assert "art. 126ffa" not in out


def test_an_edge_no_table_gives_any_more_goes(client: TestClient, cli: Any) -> None:
    GraphStore().execute(
        "DELETE FROM raw_sources WHERE kind = %(k)s",
        {"k": RAW_KIND_TK_TRANSPOSITION_TABLE},
    )
    cli("semantic", "tk-transposition-tables")
    assert _transposed() == {}
