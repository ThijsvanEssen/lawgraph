"""The aanhef of a regulation on its page: the real ``normalize bwb`` on the Regeling
cyberbeveiliging EZK (BWBR0052884), then ``/api/instruments/{identifier}``.

- The aanhef is its text, a block a part: who enacts it, its considerans with the line
  "Gelet op …" marked inside it, and "Besluit:".
- Its links name the articles of the Cyberbeveiligingsbesluit they cite, and say whether
  the data holds them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lawgraph.config.constants import COLLECTION_ARTICLES, RAW_KIND_BWB_TOESTAND
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from tests.databases import Api
from tests.integration.graph import put_node
from tests.integration.seed import write_toestanden

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGULATION = "BWBR0052884"
BESLUIT = "BWBR0052875"  # Cyberbeveiligingsbesluit


def test_the_page_of_a_regulation_has_its_aanhef_with_its_links(
    store: GraphStore, cli: Any, api: Api
) -> None:
    write_toestanden(
        store,
        [
            (
                RAW_KIND_BWB_TOESTAND,
                REGULATION,
                (
                    FIXTURES / "bwb_regeling_cyberbeveiliging_ezk_toestand.xml"
                ).read_text(),
                {
                    "bwb_id": REGULATION,
                    "state_url": f"https://repo/{REGULATION}.xml",
                    "start_date": "2026-08-15",
                    "end_date": "9999-12-31",
                },
            )
        ],
    )
    cli("normalize", "bwb")
    put_node(store, COLLECTION_ARTICLES, make_node_key(BESLUIT, "19"), bwb_id=BESLUIT)

    preamble = api.get_json(f"/api/instruments/{REGULATION}")["preamble"]

    text = preamble["text"]
    assert text.split("\n")[1:] == [
        "Gelet op de artikelen 19, 23, eerste lid, en 28 van het "
        "Cyberbeveiligingsbesluit;",
        "Besluit:",
    ]
    assert [part["kind"] for part in preamble["parts"]] == [
        "wie",
        "considerans",
        "gelet_op",
        "afkondiging",
    ]
    assert [
        (
            text[ref["start"] : ref["end"]],
            ref["target"]["key"],
            ref["target"]["exists"],
            ref["leden"],
        )
        for ref in preamble["references"]
    ] == [
        ("artikelen 19", make_node_key(BESLUIT, "19"), True, []),
        ("23, eerste lid", make_node_key(BESLUIT, "23"), False, ["1"]),
        (
            "28 van het Cyberbeveiligingsbesluit",
            make_node_key(BESLUIT, "28"),
            False,
            [],
        ),
    ]
