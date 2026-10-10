"""A citation a court makes in a footnote: the real ``normalize rechtspraak`` keeps the
footnotes of a judgment, ``semantic rechtspraak`` links what they cite, and a run in slices
names where the next one goes on."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lawgraph.config.constants import RAW_KIND_RS_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.core.models import Node, NodeType
from lawgraph.db import GraphStore, NodeWriter, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ECLI = "ECLI:NL:RBZWB:2026:1134"
BW10 = "BWBR0030068"


def _seed(store: GraphStore) -> None:
    with NodeWriter(store) as nodes:
        nodes.add(
            Node(
                collection="instruments",
                type=NodeType.INSTRUMENT,
                key=BW10.lower(),
                labels=[],
                props={"bwb_id": BW10, "citation_title": "Burgerlijk Wetboek Boek 10"},
            )
        )
        nodes.add(
            Node(
                collection="articles",
                type=NodeType.ARTICLE,
                key=f"{BW10.lower()}_56",
                labels=[],
                props={"bwb_id": BW10, "article_number": "56"},
            )
        )
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id=ECLI,
                payload_text=(FIXTURES / "rechtspraak_rbzwb_2026_1134.xml").read_text(),
                meta={"ecli": ECLI},
            )
        )


def test_a_citation_in_a_footnote_is_linked_for_its_paragraph(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _seed(store)

    sliced = cli("normalize", "rechtspraak", "--limit", "1")
    cli("semantic", "rechtspraak")

    assert "go on with --after" in sliced.stderr
    judgment = store.get_node("judgments", "ecli_nl_rbzwb_2026_1134")
    assert judgment is not None
    assert judgment.props["footnotes"] == [
        {
            "label": "1",
            "paragraph_id": "rov-3.1",
            "text": "Echtscheiding: art. 3 Brussel II-ter en art. 10:56 BW.",
        }
    ]
    (meta,) = list(
        store.query(
            "SELECT doc -> 'meta' FROM edges WHERE from_id = %(j)s AND to_id = %(a)s"
            " AND relation = 'REFERS_TO'",
            {
                "j": "judgments/ecli_nl_rbzwb_2026_1134",
                "a": f"articles/{BW10.lower()}_56",
            },
        )
    )
    meta = meta if isinstance(meta, dict) else json.loads(meta)
    (mention,) = meta["mentions"]
    assert (mention["paragraph_id"], mention["footnote"], mention["raw_match"]) == (
        "rov-3.1",
        "1",
        "art. 10:56 BW",
    )
