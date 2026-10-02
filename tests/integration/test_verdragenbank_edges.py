"""What the register of a treaty names, as edges, from the real item XML of 000004 (Granada,
1985) and 004630 (Protocol No. 2 to the ECHR): the real ``normalize verdragenbank`` and
``semantic verdragenbank``, then the API.

- A treaty is PUBLISHED_IN each Tractatenblad it lists; one not in the graph yet becomes a
  publication, one the BWB loaded keeps what the BWB said.
- It is LEGISLATED_IN the dossier of its approval when the dossier is in the graph.
- A Protocol is PART_OF its Convention (005132) when that is in the graph, and the
  Convention does not count it among its articles.
- A second run changes nothing; an edge the register no longer names goes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lawgraph.config.constants import (
    RAW_KIND_VERDRAG,
    RAW_KIND_VERDRAG_XML,
    SOURCE_VERDRAGENBANK,
)
from lawgraph.db import GraphStore, RawSourceWriter, make_edge_doc, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _summary(identifier: str, title: str) -> dict[str, Any]:
    return {
        "uri": f"https://repository.overheid.nl/frbr/vd/{identifier}",
        "verdragsnummer": identifier,
        "title": title,
        "title_nl": title,
        "treaty_type": "Multilateraal",
        "status": "Inwerkinggetreden",
    }


def _seed(store: GraphStore) -> None:
    with RawSourceWriter(store) as writer:
        for identifier, title in (
            (
                "000004",
                "Verdrag tot bescherming van het architectonisch erfgoed van Europa",
            ),
            ("004630", "Protocol nr. 2 bij het EVRM"),
            ("005132", "Verdrag tot bescherming van de rechten van de mens"),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_VERDRAGENBANK,
                    kind=RAW_KIND_VERDRAG,
                    external_id=identifier,
                    payload_json=_summary(identifier, title),
                )
            )
        for identifier in ("000004", "004630"):
            writer.add(
                raw_source_doc(
                    source=SOURCE_VERDRAGENBANK,
                    kind=RAW_KIND_VERDRAG_XML,
                    external_id=identifier,
                    payload_text=(
                        FIXTURES / f"verdragenbank_item_{identifier}.xml"
                    ).read_text(),
                )
            )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            {
                "_key": "22386",
                "type": "dossier",
                "labels": [],
                "props": {"number": "22386"},
            }
        ],
    )
    # a Tractatenblad the BWB loaded already
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "_key": "trb_1994_59",
                "type": "instrument",
                "labels": ["BWB", "Publication"],
                "props": {
                    "kind": "publicatie",
                    "source": "bwb",
                    "citation_title": "BWB",
                },
            }
        ],
    )


def _edges(store: GraphStore) -> dict[tuple[str, str, str], Any]:
    statement = """
    SELECT from_id, to_id, relation, doc -> 'meta' AS meta FROM edges
    WHERE source = 'verdragenbank'
    """
    return {
        (e["from_id"], e["relation"], e["to_id"]): e["meta"]
        for e in store.query(statement)
    }


@pytest.fixture()
def store(database: str, cli: Any) -> GraphStore:
    store = GraphStore()
    _seed(store)
    cli("normalize", "verdragenbank")
    cli("semantic", "verdragenbank")
    return store


def test_a_treaty_is_published_in_its_tractatenbladen(store: GraphStore) -> None:
    edges = _edges(store)
    granada = "instruments/verdrag_000004"
    assert edges[(granada, "PUBLISHED_IN", "instruments/trb_1985_163")] == {
        "tractatenblad": "1985, 163",
        "description": "En, Fr, vert. Ne",
    }
    # a new publication carries what its id says; one the BWB loaded is left as it was
    new = store.get_node("instruments", "trb_1985_163")
    assert new is not None
    assert new.props["citation_title"] == "Trb. 1985, 163"
    assert new.props["kind"] == "publicatie" and new.props["publication_kind"] == "Trb"
    assert (granada, "PUBLISHED_IN", "instruments/trb_1994_59") in edges
    loaded = store.get_node("instruments", "trb_1994_59")
    assert loaded is not None and loaded.props["citation_title"] == "BWB"


def test_a_treaty_is_legislated_in_the_dossier_of_its_approval(
    store: GraphStore,
) -> None:
    edges = _edges(store)
    assert edges[("instruments/verdrag_000004", "LEGISLATED_IN", "dossiers/22386")] == {
        "dossier_number": "22386"
    }
    # a dossier that is not in the graph gets no edge
    assert not any(t == "dossiers/32047" for _, _, t in edges)


def test_a_protocol_is_part_of_its_convention(store: GraphStore, cli: Any) -> None:
    edges = _edges(store)
    assert edges[
        ("instruments/verdrag_004630", "PART_OF", "instruments/verdrag_005132")
    ] == {"verdrag_id": "005132"}
    # the Convention does not count its Protocol among its articles or their citations
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                "judgments/ecli_nl_hr_2020_1",
                "instruments/verdrag_004630",
                "REFERS_TO",
                source="test",
                confidence=1.0,
            )
        ]
    )
    cli("semantic", "graph-list-stats")
    convention = store.get_node("instruments", "verdrag_005132")
    assert convention is not None
    assert convention.props["article_count"] == 0
    assert convention.props["inbound_citation_count"] == 0
    protocol = store.get_node("instruments", "verdrag_004630")
    assert protocol is not None and protocol.props["inbound_citation_count"] == 1


def test_a_second_run_changes_nothing_and_an_edge_no_longer_named_goes(
    store: GraphStore, cli: Any
) -> None:
    before = _edges(store)
    cli("semantic", "verdragenbank")
    assert _edges(store) == before

    store.query(
        """
        UPDATE instruments SET props = lg_unset(props, ARRAY['parent_treaties'])
        WHERE key = 'verdrag_004630'
        """
    )
    cli("semantic", "verdragenbank")
    assert not any(r == "PART_OF" for _, r, _ in _edges(store))
