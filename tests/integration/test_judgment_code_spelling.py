"""A judgment cites a law by its abbreviation as the WTI writes it: the real ``semantic
rechtspraak`` on the small test server.

"CBW" in a judgment about a furniture purchase is the Centrale Branchevereniging Wonen
("artikel 12 van de CBW-voorwaarden"), not the Cyberbeveiligingswet, whose abbreviation is
"Cbw". Another spelling stands for a new law only in a judgment that also names it so or by
its name, and for a law in force for years by itself: "Vw" is the Vreemdelingenwet 2000
("VW"). A judgment cites no law that came to be after it: "Vw" in 1998 and "CBW" in 2000
are other laws. An edge an earlier rule made goes when the judgment is read again.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.edges import make_edge_doc
from lawgraph.pipelines.semantic.rechtspraak import SEMANTIC_SOURCE
from tests.integration.graph import cited_articles, put_node
from tests.integration.seed import judgment_xml, write_judgments

CBW = "BWBR0052872"
VW = "BWBR0011823"
FURNITURE = "ECLI:NL:RBMNE:2026:5077"
CYBER = "ECLI:NL:RBDHA:2026:9001"
BOTH_SPELLINGS = "ECLI:NL:RBDHA:2026:9002"
CONDITIONS_2000 = "ECLI:NL:GHARN:2000:AB0645"
ALIENS = "ECLI:NL:RBDHA:2013:13683"
ALIENS_1998 = "ECLI:NL:RBSGR:1998:AA6560"

JUDGMENTS = {
    FURNITURE: judgment_xml(
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
    CYBER: judgment_xml(
        CYBER, "2026-09-01", [("4.1", "De zorgplicht van artikel 21 Cbw geldt.")]
    ),
    BOTH_SPELLINGS: judgment_xml(
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
    CONDITIONS_2000: judgment_xml(
        CONDITIONS_2000,
        "2000-12-12",
        [
            (
                "4.2",
                "Ingevolge artikel 10 van de CBW is de koper een vergoeding verschuldigd.",
            )
        ],
    ),
    ALIENS: judgment_xml(
        ALIENS,
        "2013-09-17",
        [
            (
                "5",
                "Verweerder had niet de bevoegdheid om tegen eiser een inreisverbod uit te "
                "vaardigen, gelet op hetgeen is bepaald in artikel 66a, eerste lid, Vw.",
            )
        ],
    ),
    ALIENS_1998: judgment_xml(
        ALIENS_1998,
        "1998-05-06",
        [("2", "Ingevolge artikel 1a Vw is verweerder bevoegd.")],
    ),
}


def _load_the_law(store: GraphStore) -> None:
    """The Cyberbeveiligingswet as ``normalize bwb`` writes it: its WTI abbreviation is Cbw."""
    put_node(
        store,
        COLLECTION_INSTRUMENTS,
        make_node_key(CBW),
        bwb_id=CBW,
        title="Cyberbeveiligingswet",
        citation_title="Cyberbeveiligingswet",
        short_title="Cbw",
        aliases=["Cbw"],
        kind="wet",
        date_signed="2026-07-08",
        date_published="2026-07-10",
        date_in_force="2026-08-15",
    )
    put_node(
        store,
        COLLECTION_INSTRUMENTS,
        make_node_key(VW),
        bwb_id=VW,
        title="Vreemdelingenwet 2000",
        citation_title="Vreemdelingenwet 2000",
        short_title="VW",
        aliases=["VW", "Vw 2000"],
        kind="wet",
        date_signed="2000-11-23",
        date_published="2000-12-07",
        date_in_force="2001-04-01",
    )
    for law, number in [(CBW, "10"), (CBW, "11"), (CBW, "12"), (CBW, "21")] + [
        (VW, "1a"),
        (VW, "66a"),
    ]:
        put_node(
            store,
            COLLECTION_ARTICLES,
            make_node_key(law, number),
            bwb_id=law,
            article_number=number,
            label=f"Artikel {number}",
            text=f"Tekst van artikel {number}.",
        )


def test_a_judgment_cites_the_law_by_its_abbreviation_as_written(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _load_the_law(store)
    write_judgments(store, JUDGMENTS)
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

    assert cited_articles(store, furniture) == {}
    (unresolved,) = store.query(
        "SELECT props -> 'unresolved_citations' AS cited FROM judgments WHERE key = %(k)s",
        {"k": furniture},
    )
    assert [c["law"] for c in unresolved] == ["CBW"]
    assert set(cited_articles(store, make_node_key(CYBER))) == {
        make_node_key(CBW, "21")
    }
    assert set(cited_articles(store, make_node_key(BOTH_SPELLINGS))) == {
        make_node_key(CBW, "12")
    }
    assert cited_articles(store, make_node_key(CONDITIONS_2000)) == {}
    assert set(cited_articles(store, make_node_key(ALIENS))) == {
        make_node_key(VW, "66a")
    }
    assert cited_articles(store, make_node_key(ALIENS_1998)) == {}
