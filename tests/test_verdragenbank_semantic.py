"""``semantic verdragenbank``: the Tractatenblad a register names becomes a publication."""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_INSTRUMENTS
from lawgraph.pipelines.semantic.verdragenbank import trb_node


def test_a_new_tractatenblad_is_a_publication_with_what_its_id_says() -> None:
    node = trb_node("trb-1951-154")
    assert node is not None
    assert (node.collection, node.key) == (COLLECTION_INSTRUMENTS, "trb_1951_154")
    assert node.labels == ["Verdrag", "Publication"]
    assert node.props == {
        "display_name": "Trb. 1951, 154",
        "citation_title": "Trb. 1951, 154",
        "kind": "publicatie",
        "jurisdiction": "nl",
        "source": "verdragenbank",
        "official_id": "trb-1951-154",
        "publication_kind": "Trb",
        "publication_year": 1951,
        "publication_number": "154",
    }


def test_another_id_is_no_tractatenblad() -> None:
    assert trb_node("stb-1951-154") is None
    assert trb_node("trb-1951") is None
