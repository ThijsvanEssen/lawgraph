"""A stub stops being a stub when the real record is loaded."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RAW_KIND_RS_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import judgment_xml, seed


def _stub_flag(store: ArangoStore, ecli: str) -> Any:
    node = store.db.collection("judgments").get(make_node_key(ecli))
    return None if node is None else node["props"].get("stub")


def test_a_cited_judgment_is_a_stub_until_it_is_loaded(database: str, cli: Any) -> None:
    store = ArangoStore()
    seed(store, documents=10, judgments=5, regulations=2)  # judgment n cites n + 1
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak-citations")
    cited = "ECLI:NL:HR:2020:5"  # cited by the last one, not loaded
    assert _stub_flag(store, cited) is True

    # fill-gaps downloads it; here it arrives the same way.
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id=cited,
                payload_text=judgment_xml(5),
                meta={"ecli": cited},
            )
        )
    cli("normalize", "rechtspraak")

    # Upserts merge props: without a word from the normalizer the flag would stay, the API
    # would go on hiding the judgment and expand-graph would never see a gap close.
    assert _stub_flag(store, cited) is False
    stubs = list(
        store.query(
            "FOR j IN judgments FILTER j.props.stub == true RETURN j.props.ecli"
        )
    )
    assert stubs == []
