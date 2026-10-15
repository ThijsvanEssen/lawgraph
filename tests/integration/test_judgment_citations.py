"""``REFERS_TO`` between judgments means "named in the text": the real ``semantic
rechtspraak-citations`` on stored judgments.

The Hoge Raad judgment names an earlier ruling in its text, and its metadata names its
conclusion and the judgment it ruled on (``dcterms:relation``). Only the ruling in the text
is cited; the metadata links are the procedural edges ``ADVISES_ON`` and ``APPEAL_OF``, made
by their own steps. An edge an earlier run made from the metadata goes.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    RELATION_REFERS_TO,
)
from lawgraph.db import EdgeWriter, GraphStore
from lawgraph.pipelines.semantic.rechtspraak_citations import EDGE_SOURCE
from tests.integration.graph import cited_judgments
from tests.integration.seed import (
    rechtspraak_relation,
    rechtspraak_xml,
    write_judgments,
)

RULING = "ECLI:NL:HR:2021:10"
CITED = "ECLI:NL:HR:2015:1"
CONCLUSION = "ECLI:NL:PHR:2021:5"
APPEALED = "ECLI:NL:GHDHA:2020:7"

JUDGMENTS = {
    RULING: rechtspraak_xml(
        RULING,
        "Hoge Raad",
        "2021-03-05",
        "20/00001",
        procedure="Cassatie",
        relations=rechtspraak_relation(CONCLUSION, "conclusie", "eerdereAanleg")
        + rechtspraak_relation(APPEALED, "uitspraak", "eerdereAanleg"),
        text=f"Zoals de Hoge Raad eerder oordeelde (HR 1 mei 2015, {CITED}), faalt het "
        "middel.",
    ),
    CITED: rechtspraak_xml(CITED, "Hoge Raad", "2015-05-01", "14/00001"),
    CONCLUSION: rechtspraak_xml(
        CONCLUSION,
        "Parket bij de Hoge Raad",
        "2021-01-15",
        "20/00001",
        document_type="Conclusie",
        relations=rechtspraak_relation(RULING, "conclusie", "latereAanleg"),
    ),
    APPEALED: rechtspraak_xml(
        APPEALED, "Gerechtshof Den Haag", "2020-02-04", "200.000.001"
    ),
}


def test_a_judgment_cites_only_what_its_text_names(database: str, cli: Any) -> None:
    store = GraphStore()
    write_judgments(store, JUDGMENTS)
    cli("normalize", "rechtspraak")
    # what an earlier run made of the metadata
    with EdgeWriter(store, what=None) as edges:
        edges.add(
            "judgments/ecli_nl_hr_2021_10",
            "judgments/ecli_nl_phr_2021_5",
            RELATION_REFERS_TO,
            source=EDGE_SOURCE,
        )
        edges.add(
            "judgments/ecli_nl_phr_2021_5",
            "judgments/ecli_nl_hr_2021_10",
            RELATION_REFERS_TO,
            source=EDGE_SOURCE,
        )

    cli("semantic", "rechtspraak-citations")

    assert cited_judgments(store) == {(RULING, CITED)}


# Before 2013 a decision is cited by its LJN, the number of its ECLI.
LJN_CITING = "ECLI:NL:CRVB:2011:BP0671"
LJN_CITED = "ECLI:NL:CRVB:2009:BG6197"


def test_an_ljn_cites_the_judgment_whose_ecli_has_it(database: str, cli: Any) -> None:
    store = GraphStore()
    judgments = {
        LJN_CITING: rechtspraak_xml(
            LJN_CITING,
            "Centrale Raad van Beroep",
            "2011-02-01",
            "09/1234 WWB",
            text="De Raad verwijst naar zijn uitspraak van 3 februari 2009, LJN BG6197, "
            "en naar LJN ZZ9999, die niet geladen is.",
        ),
        LJN_CITED: rechtspraak_xml(
            LJN_CITED, "Centrale Raad van Beroep", "2009-02-03", "07/1 WWB"
        ),
    }
    write_judgments(store, judgments)
    cli("normalize", "rechtspraak")

    cli("semantic", "rechtspraak-citations")

    # the LJN no judgment has makes no stub
    assert cited_judgments(store) == {(LJN_CITING, LJN_CITED)}
