"""Which article a citation of a loaded law makes an edge to: the real ``normalize bwb``,
``normalize bwb-history``, ``normalize rechtspraak`` and ``semantic rechtspraak`` on a law
whose article 7 was repealed.

A text from before cites the repealed article: its edge goes to the historical article, not
to a stub beside it. A number of a shape the law never uses (``140.1``: article 140, first
lid, written short) or with a leading zero is no article; a plausible number the loaded text
lacks still becomes a stub.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_RS_CONTENT,
    SOURCE_BWB,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.models import NodeType
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.test_judgment_mentions import _judgment_xml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAW = "BWBR0001840"
OLD = (FIXTURES / "bwb_grondwet_toestand.xml").read_text()
# Article 7 repealed: gone from the toestand of 2025.
NEW = re.sub(
    r'<artikel bwb-ng-variabel-deel="/Hoofdstuk1/Artikel7".*?</artikel>',
    "",
    OLD,
    count=1,
    flags=re.DOTALL,
)
ECLI = "ECLI:NL:HR:2020:7"
TEXT = (
    "Op grond van artikel 7 van de Grondwet, artikel 140.1 van de Grondwet, "
    "artikelen 047 en 142 van de Grondwet en artikel 999 van de Grondwet."
)


def _seed(store: ArangoStore) -> None:
    records = [
        (RAW_KIND_BWB_TOESTAND, LAW, NEW, "2025-01-01", None),
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2018-12-21",
            OLD,
            "2018-12-21",
            "2024-12-31",
        ),
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2025-01-01",
            NEW,
            "2025-01-01",
            "9999-12-31",
        ),
    ]
    with RawSourceWriter(store) as writer:
        for kind, external_id, xml, start, end in records:
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=kind,
                    external_id=external_id,
                    payload_text=xml,
                    meta={
                        "bwb_id": LAW,
                        "state_url": f"https://repo/{LAW}/{start}.xml",
                        "start_date": start,
                        "end_date": end,
                    },
                )
            )
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id=ECLI,
                payload_text=_judgment_xml(ECLI, "2020-03-01", [("2.1", TEXT)]),
                meta={"ecli": ECLI},
            )
        )


def test_a_citation_of_a_loaded_law_goes_to_an_article_it_has_or_had(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    _seed(store)
    cli("normalize", "bwb")
    cli("normalize", "bwb-history")
    cli("normalize", "rechtspraak")
    # a stub an earlier run made of a number the law never uses
    store.ensure_stub_node(
        "articles",
        "bwbr0001840_140_1",
        NodeType.ARTICLE,
        props={"bwb_id": LAW, "article_number": "140.1"},
    )
    cli("semantic", "rechtspraak")

    cited = {
        row["key"]: row
        for row in store.query(
            "FOR e IN edges FILTER e._from == @j AND e.relation == 'REFERS_TO' "
            "LET a = DOCUMENT(e._to) RETURN {key: a._key, stub: a.props.stub == true, "
            "last: a.props.last_article_number}",
            {"j": "judgments/ecli_nl_hr_2020_7"},
        )
    }

    assert set(cited) == {
        "bwbr0001840_7_stam_2990103",  # the repealed article, as the graph has it
        "bwbr0001840_142",
        "bwbr0001840_999",  # plausible, not in the text: a stub, as before
    }
    assert cited["bwbr0001840_7_stam_2990103"]["last"] == "7"
    assert cited["bwbr0001840_999"]["stub"] is True
    stubs = set(
        store.query("FOR a IN articles FILTER a.props.stub == true RETURN a._key")
    )
    # no 7 or 047 beside them; the old stub of 140.1 has no edge
    assert stubs == {"bwbr0001840_999", "bwbr0001840_140_1"}
