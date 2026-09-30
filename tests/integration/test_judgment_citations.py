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
    RAW_KIND_RS_CONTENT,
    RELATION_REFERS_TO,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.db import ArangoStore, EdgeWriter, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.semantic.rechtspraak_citations import SEMANTIC_SOURCE
from tests.integration.test_judgment_relations import _relation, _xml

RULING = "ECLI:NL:HR:2021:10"
CITED = "ECLI:NL:HR:2015:1"
CONCLUSION = "ECLI:NL:PHR:2021:5"
APPEALED = "ECLI:NL:GHDHA:2020:7"

JUDGMENTS = {
    RULING: _xml(
        RULING,
        "Hoge Raad",
        "2021-03-05",
        "20/00001",
        procedure="Cassatie",
        relations=_relation(CONCLUSION, "conclusie", "eerdereAanleg")
        + _relation(APPEALED, "uitspraak", "eerdereAanleg"),
        text=f"Zoals de Hoge Raad eerder oordeelde (HR 1 mei 2015, {CITED}), faalt het "
        "middel.",
    ),
    CITED: _xml(CITED, "Hoge Raad", "2015-05-01", "14/00001"),
    CONCLUSION: _xml(
        CONCLUSION,
        "Parket bij de Hoge Raad",
        "2021-01-15",
        "20/00001",
        document_type="Conclusie",
        relations=_relation(RULING, "conclusie", "latereAanleg"),
    ),
    APPEALED: _xml(APPEALED, "Gerechtshof Den Haag", "2020-02-04", "200.000.001"),
}


def _cited(store: ArangoStore) -> set[tuple[str, str]]:
    aql = """
    FOR e IN edges FILTER e.relation == @relation
        FILTER STARTS_WITH(e._from, "judgments/") AND STARTS_WITH(e._to, "judgments/")
        RETURN [DOCUMENT(e._from).props.ecli, DOCUMENT(e._to).props.ecli]
    """
    return {tuple(row) for row in store.query(aql, {"relation": RELATION_REFERS_TO})}


def test_a_judgment_cites_only_what_its_text_names(database: str, cli: Any) -> None:
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        for ecli, xml in JUDGMENTS.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_CONTENT,
                    external_id=ecli,
                    payload_text=xml,
                    meta={"ecli": ecli},
                )
            )
    cli("normalize", "rechtspraak")
    # what an earlier run made of the metadata
    with EdgeWriter(store, what=None) as edges:
        edges.add(
            "judgments/ecli_nl_hr_2021_10",
            "judgments/ecli_nl_phr_2021_5",
            RELATION_REFERS_TO,
            source=SEMANTIC_SOURCE,
        )
        edges.add(
            "judgments/ecli_nl_phr_2021_5",
            "judgments/ecli_nl_hr_2021_10",
            RELATION_REFERS_TO,
            source=SEMANTIC_SOURCE,
        )

    cli("semantic", "rechtspraak-citations")

    assert _cited(store) == {(RULING, CITED)}
