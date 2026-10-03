"""A malformed ECLI in a judgment text becomes no stub: the real ``semantic
rechtspraak-citations`` repairs what the text shows (a split LJN, NL and the court swapped, a
range) and drops the rest. The stubs an earlier run made of malformed ECLIs lose their edges
and go; a stub another edge still reaches stays.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    RELATION_APPEAL_OF,
    RELATION_REFERS_TO,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.models import NodeType, make_node_key
from lawgraph.db import EdgeWriter, GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.semantic.rechtspraak_appeal import (
    SEMANTIC_SOURCE as APPEAL_SOURCE,
)
from lawgraph.pipelines.semantic.rechtspraak_citations import SEMANTIC_SOURCE
from tests.integration.test_judgment_citations import _cited
from tests.integration.test_judgment_relations import _xml

RULING = "ECLI:NL:HR:2021:10"
TEXT = (
    # the LJN split by the markup: the text reads "BH 2815"
    "Zie HR 5 juni 2009, ECLI:NL:HR:2009:BH<emphasis>2815</emphasis>, "
    "HR 13 januari 2023, ECLI:HR:NL:2023:26, "
    "HR 18 december 2018, ECLI:NL:HR:2018:2374-2375, "
    "HR 8 december 1978, ECLI:NL:HR:2978:AM4447 en HR 4 december 2004, "
    "ECLI:NL:HR:2004:AQ808."
)
EARLIER_STUBS = (
    "ECLI:NL:HR:2009:BH",
    "ECLI:HR:NL:2023:26",
    "ECLI:NL:HR:2018:2374-2375",
    "ECLI:NL:HR:2978:AM4447",
    "ECLI:NL:HR:2004:AQ808",
)
# a stub another step links: it stays
APPEALED = "ECLI:NL:GHDHA:2020:7"


def _stub_eclis(store: GraphStore) -> set[str]:
    return set(store.query(f"SELECT ecli FROM {COLLECTION_JUDGMENTS} WHERE stub"))


def test_malformed_eclis_are_repaired_or_dropped(database: str, cli: Any) -> None:
    store = GraphStore()
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id=RULING,
                payload_text=_xml(
                    RULING, "Hoge Raad", "2021-03-05", "20/00001", text=TEXT
                ),
                meta={"ecli": RULING},
            )
        )
    cli("normalize", "rechtspraak")
    # what an earlier run made of the malformed ECLIs, and a stub another step links
    ruling_id = f"{COLLECTION_JUDGMENTS}/{make_node_key(RULING)}"
    with EdgeWriter(store, what=None) as edges:
        for ecli in (*EARLIER_STUBS, APPEALED):
            stub = store.ensure_stub_node(
                COLLECTION_JUDGMENTS,
                make_node_key(ecli),
                NodeType.JUDGMENT,
                props={"ecli": ecli},
            )
            assert stub is not None and stub.node_id
            relation = RELATION_APPEAL_OF if ecli == APPEALED else RELATION_REFERS_TO
            source = APPEAL_SOURCE if ecli == APPEALED else SEMANTIC_SOURCE
            edges.add(ruling_id, stub.node_id, relation, source=source)

    cli("semantic", "rechtspraak-citations")

    repaired = {
        "ECLI:NL:HR:2009:BH2815",
        "ECLI:NL:HR:2023:26",
        "ECLI:NL:HR:2018:2374",
        "ECLI:NL:HR:2018:2375",
    }
    assert _cited(store) == {(RULING, ecli) for ecli in repaired}
    assert _stub_eclis(store) == repaired | {APPEALED}
