"""When a law expired, and which law an abbreviation of several stands for on a date: the
real ``normalize bwb`` and ``semantic rechtspraak`` on the small test server.

``normalize bwb`` reads the expiry of a regulation from the SRU record of its current
toestand: the last toestand of a repealed regulation ended before it was read. "Bro" in a
judgment is the Besluit op de ruimtelijke ordening 1985 ("BRO") in 2005 and the Besluit
ruimtelijke ordening that replaced it on 1 July 2008 in 2010; "Hw" in 2020 is not the
Huurwet ("HW"), repealed in 2003.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_RS_CONTENT,
    SOURCE_BWB,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.test_echr_convention import _cited, _put
from tests.integration.test_judgment_mentions import _judgment_xml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
XML = (FIXTURES / "bwb_grondwet_toestand.xml").read_text()

BRO_1985, BRO, HUURWET = "BWBR0003889", "BWBR0023798", "BWBR0002066"
BEFORE = "ECLI:NL:RVS:2005:AT2783"
AFTER = "ECLI:NL:RVS:2010:BM7121"
HOUSING = "ECLI:NL:RBAMS:2020:1234"


def test_a_regulation_whose_last_toestand_ended_has_expired(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    with RawSourceWriter(store) as writer:
        for law, end in [("BWBR0001840", "9999-12-31"), (HUURWET, "2003-07-31")]:
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND,
                    external_id=law,
                    payload_text=XML,
                    meta={
                        "bwb_id": law,
                        "state_url": f"https://repo/{law}.xml",
                        "start_date": "2002-07-01",
                        "end_date": end,
                    },
                )
            )
    cli("normalize", "bwb")

    rows = store.query(
        "SELECT bwb_id, props -> 'date_expired' AS expired FROM instruments "
        "WHERE bwb_id = ANY(%(ids)s)",
        {"ids": ["BWBR0001840", HUURWET]},
    )
    assert {row["bwb_id"]: row["expired"] for row in rows} == {
        "BWBR0001840": None,
        HUURWET: "2003-08-01",
    }


def _load_the_laws(store: GraphStore) -> None:
    """As ``normalize bwb`` writes them: the WTI abbreviations, the dates."""
    laws = [
        (BRO_1985, "Besluit op de ruimtelijke ordening 1985", "BRO 1985", ["BRO", "BRO 1985"],
         "1985-12-02", "1986-03-01", "2008-07-01", "19"),
        (BRO, "Besluit ruimtelijke ordening", None, ["Bro"],
         "2008-04-21", "2008-07-01", "2024-01-01", "3.1.6"),
        (HUURWET, "Huurwet", "HW", ["HW"], "1950-12-13", "1951-01-01", "2003-08-01", "28"),
    ]  # fmt: skip
    for law, title, short, aliases, signed, in_force, expired, number in laws:
        _put(
            store,
            COLLECTION_INSTRUMENTS,
            make_node_key(law),
            bwb_id=law,
            title=title,
            citation_title=title,
            short_title=short,
            aliases=aliases,
            kind="AMvB",
            date_signed=signed,
            date_in_force=in_force,
            date_expired=expired,
        )
        _put(
            store,
            COLLECTION_ARTICLES,
            make_node_key(law, number),
            bwb_id=law,
            article_number=number,
            label=f"Artikel {number}",
            text=f"Tekst van artikel {number}.",
        )


def test_an_abbreviation_of_several_laws_is_the_one_in_force_then(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _load_the_laws(store)
    judgments = {
        BEFORE: ("2005-03-02", "Ingevolge artikel 19 Bro is vrijstelling verleend."),
        AFTER: ("2010-06-09", "Gelet op artikel 3.1.6, eerste lid, van het Bro."),
        HOUSING: ("2020-04-01", "Ingevolge artikel 28 Hw is een vergunning nodig."),
    }
    with RawSourceWriter(store) as writer:
        for ecli, (date, text) in judgments.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_CONTENT,
                    external_id=ecli,
                    payload_text=_judgment_xml(ecli, date, [("1", text)]),
                    meta={"ecli": ecli},
                )
            )
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak")

    assert set(_cited(store, make_node_key(BEFORE))) == {make_node_key(BRO_1985, "19")}
    assert set(_cited(store, make_node_key(AFTER))) == {make_node_key(BRO, "3.1.6")}
    assert _cited(store, make_node_key(HOUSING)) == {}
