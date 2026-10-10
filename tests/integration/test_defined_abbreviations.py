"""An abbreviation several laws claim (WWB: the Participatiewet and the Wet wederzijdse
bijstand) names the law the judgment itself gives it to, also by an earlier title of that law
("Wet werk en bijstand", the Participatiewet until 2015). The real ``normalize bwb``,
``normalize rechtspraak`` and ``semantic rechtspraak`` run on two laws that claim WWB and a
judgment that defines it."""

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
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.test_judgment_mentions import _judgment_xml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PW, WWBI = "BWBR0015703", "BWBR0003270"
ECLI = "ECLI:NL:CRVB:2011:1299"


def _wti(abbreviation: str, current: str, earlier: str | None = None) -> str:
    titles = f'<citeertitel status="officieel">{current}</citeertitel><citeertitels>'
    if earlier:
        titles += (
            '<citeertitel status="officieel" geldig-tot="2015-01-01" '
            f'geldig-van="2004-01-01">{earlier}</citeertitel>'
        )
    titles += (
        f'<citeertitel status="officieel" geldig-van="2015-01-01">{current}</citeertitel>'
        "</citeertitels>"
    )
    return (
        "<algemene-informatie><afkortingen>"
        f"<afkorting>{abbreviation}</afkorting></afkortingen>{titles}"
        "</algemene-informatie>"
    )


def _seed(store: GraphStore) -> None:
    grondwet = (FIXTURES / "bwb_grondwet_toestand.xml").read_text()
    laws = {
        PW: (_wti("Wwb", "Participatiewet", "Wet werk en bijstand"), "Participatiewet"),
        WWBI: (_wti("WWB", "Wet wederzijdse bijstand"), "Wet wederzijdse bijstand"),
    }
    judgment = _judgment_xml(
        ECLI,
        "2011-02-01",
        [
            (
                "1.1",
                "Appellant ontving bijstand op grond van de Wet werk en bijstand "
                "(hierna: WWB).",
            ),
            (
                "4.2",
                "Ingevolge artikel 7, eerste lid, van de WWB verstrekt het college "
                "inlichtingen.",
            ),
        ],
    )
    with RawSourceWriter(store) as writer:
        for bwb_id, (wti, title) in laws.items():
            # any toestand does: the Grondwet fixture has an article 7
            toestand = grondwet.replace("BWBR0001840", bwb_id).replace(
                "Grondwet", title
            )
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND,
                    external_id=bwb_id,
                    payload_text=toestand,
                    meta={
                        "bwb_id": bwb_id,
                        "state_url": f"https://repo/{bwb_id}/x.xml",
                    },
                )
            )
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_WTI_GENERAL,
                    external_id=bwb_id,
                    payload_text=wti,
                    meta={"bwb_id": bwb_id},
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


def test_the_abbreviation_a_judgment_defines_names_that_law(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _seed(store)

    cli("normalize", "bwb")
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak")

    participatiewet = store.get_node("instruments", PW.lower())
    assert participatiewet is not None
    assert participatiewet.props["citation_titles"] == [
        "Participatiewet",
        "Wet werk en bijstand",
    ]
    cited = set(
        store.query(
            "SELECT to_id FROM edges WHERE from_id = %(j)s AND relation = 'REFERS_TO'",
            {"j": "judgments/ecli_nl_crvb_2011_1299"},
        )
    )
    assert cited == {"articles/bwbr0015703_7"}
