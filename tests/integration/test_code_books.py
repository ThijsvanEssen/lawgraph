"""Citations of the Burgerlijk Wetboek when only one of its books is loaded.

Every book of the Burgerlijk Wetboek is a regulation of its own. With only book 7 in the
graph, ``BW`` is the one abbreviation of its WTI (``BW``, ``BW Boek 7``, ``BW7``) that no
other loaded regulation claims; were it its short title, ``art. 6:162 BW`` would be a stub
"6:162" of book 7 and ``art. 7:7 BW`` a stub "7:7" beside the real article 7. The real
``normalize bwb`` and ``semantic rechtspraak`` run here on one loaded book and a judgment
that cites two.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_WTI_GENERAL,
    RAW_KIND_RS_CONTENT,
    SOURCE_BWB,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.test_judgment_mentions import _judgment_xml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
BW6, BW7 = "BWBR0005289", "BWBR0005290"
ECLI = "ECLI:NL:HR:2020:1"


def _seed(store: ArangoStore) -> None:
    # Any toestand does as book 7: the Grondwet fixture has an article 7.
    toestand = (
        (FIXTURES / "bwb_grondwet_toestand.xml").read_text().replace("BWBR0001840", BW7)
    )
    wti = (
        (FIXTURES / "bwb_wti_bw1_general.xml")
        .read_text()
        .replace("BW Boek 1", "BW Boek 7")
        .replace("BW1", "BW7")
    )
    judgment = _judgment_xml(
        ECLI,
        "2020-03-01",
        [
            (
                "3.1",
                "Op grond van art. 6:162 BW en art. 7:7 BW is de werkgever aansprakelijk.",
            )
        ],
    )
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_TOESTAND,
                external_id=BW7,
                payload_text=toestand,
                meta={"bwb_id": BW7, "state_url": f"https://repo/{BW7}/x.xml"},
            )
        )
        writer.add(
            raw_source_doc(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_WTI_GENERAL,
                external_id=BW7,
                payload_text=wti,
                meta={"bwb_id": BW7},
            )
        )
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id=ECLI,
                payload_text=judgment,
                meta={"ecli": ECLI},
            )
        )


def test_a_citation_of_a_book_lands_in_that_book(database: str, cli: Any) -> None:
    store = ArangoStore()
    _seed(store)

    cli("normalize", "bwb")
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak")

    book7 = store.get_node("instruments", BW7.lower())
    assert book7 is not None and book7.props["short_title"] == "BW7"
    cited = {
        row["id"]: row["props"]
        for row in store.query(
            "FOR e IN edges FILTER e._from == @j AND e.relation == 'REFERS_TO' "
            "RETURN {id: e._to, props: DOCUMENT(e._to).props}",
            {"j": "judgments/ecli_nl_hr_2020_1"},
        )
    }
    assert set(cited) == {"articles/bwbr0005289_162", "articles/bwbr0005290_7"}
    # book 6 is not loaded: a stub of book 6 with its own number, waiting for it
    assert cited["articles/bwbr0005289_162"]["stub"] is True
    assert cited["articles/bwbr0005289_162"]["bwb_id"] == BW6
    assert cited["articles/bwbr0005289_162"]["article_number"] == "162"
    # book 7 is: the real article, no stub beside it
    assert not cited["articles/bwbr0005290_7"].get("stub")
    assert store.get_node("articles", "bwbr0005290_7_7") is None
