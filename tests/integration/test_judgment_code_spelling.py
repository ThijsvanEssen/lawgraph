"""A judgment cites a law by its abbreviation as the WTI writes it: the real ``semantic
rechtspraak`` on the small test server.

"CBW" in a judgment about a furniture purchase is the Centrale Branchevereniging Wonen
("artikel 12 van de CBW-voorwaarden"), not the Cyberbeveiligingswet, whose abbreviation is
"Cbw". Another spelling stands for the law only in a judgment that also names it so or by
its name. An edge an earlier rule made goes when the judgment is read again.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_RS_CONTENT,
    RELATION_REFERS_TO,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.db.edges import make_edge_doc
from lawgraph.pipelines.semantic.rechtspraak import SEMANTIC_SOURCE
from tests.integration.test_echr_convention import _cited, _put
from tests.integration.test_judgment_mentions import _judgment_xml

CBW = "BWBR0052872"
FURNITURE = "ECLI:NL:RBMNE:2026:5077"
CYBER = "ECLI:NL:RBDHA:2026:9001"
BOTH_SPELLINGS = "ECLI:NL:RBDHA:2026:9002"

JUDGMENTS = {
    FURNITURE: _judgment_xml(
        FURNITURE,
        "2026-07-22",
        [
            (
                "3.4",
                "Op grond van artikel 12 van de CBW-voorwaarden voor woonwinkels (2022) "
                "mag de verkoper annuleringskosten rekenen; artikel 11 van de CBW geldt.",
            )
        ],
    ),
    CYBER: _judgment_xml(
        CYBER, "2026-09-01", [("4.1", "De zorgplicht van artikel 21 Cbw geldt.")]
    ),
    BOTH_SPELLINGS: _judgment_xml(
        BOTH_SPELLINGS,
        "2026-09-02",
        [
            ("2.1", "Sinds 15 augustus 2026 geldt de Cyberbeveiligingswet."),
            (
                "2.2",
                "Een belangrijke entiteit als bedoeld in artikel 12 CBW meldt dit.",
            ),
        ],
    ),
}


def _load_the_law(store: GraphStore) -> None:
    """The Cyberbeveiligingswet as ``normalize bwb`` writes it: its WTI abbreviation is Cbw."""
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        make_node_key(CBW),
        bwb_id=CBW,
        title="Cyberbeveiligingswet",
        citation_title="Cyberbeveiligingswet",
        short_title="Cbw",
        aliases=["Cbw"],
        kind="wet",
    )
    for number in ("11", "12", "21"):
        _put(
            store,
            COLLECTION_ARTICLES,
            make_node_key(CBW, number),
            bwb_id=CBW,
            article_number=number,
            label=f"Artikel {number}",
            text=f"Tekst van artikel {number}.",
        )


def test_a_judgment_cites_the_law_by_its_abbreviation_as_written(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _load_the_law(store)
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
    # what the earlier rule made of "artikel 12 van de CBW-voorwaarden"
    furniture = make_node_key(FURNITURE)
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                f"judgments/{furniture}",
                f"articles/{make_node_key(CBW, '12')}",
                RELATION_REFERS_TO,
                source=SEMANTIC_SOURCE,
                confidence=0.95,
            )
        ]
    )

    cli("semantic", "rechtspraak")

    assert _cited(store, furniture) == {}
    (unresolved,) = store.query(
        "SELECT props -> 'unresolved_citations' AS cited FROM judgments WHERE key = %(k)s",
        {"k": furniture},
    )
    assert [c["law"] for c in unresolved] == ["CBW"]
    assert set(_cited(store, make_node_key(CYBER))) == {make_node_key(CBW, "21")}
    assert set(_cited(store, make_node_key(BOTH_SPELLINGS))) == {
        make_node_key(CBW, "12")
    }
