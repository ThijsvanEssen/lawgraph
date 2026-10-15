"""What a paper of the Tweede Kamer does not say, for real (dossier 36764, the
Cyberbeveiligingswet, 2026).

- The record a paper came with is no text of it: its ``Titel`` is the dossier's title (the EU
  directives a bill implements), its actors hold factions ("VVD", the short title of a
  regulation too), ids and kinds. ``semantic tk`` reads the paper's title, text and
  footnotes, and a citation it no longer finds goes.
- The papers of the bill that made a law do not change that law: no AMENDS to the act
  ``LEGISLATED_IN`` their dossier or to its articles, also when they were linked before the
  act was published and are not read again (``tk-amends --since``).
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
    RELATION_LEGISLATED_IN,
    RELATION_REFERS_TO,
)
from lawgraph.db import GraphStore, make_edge_doc
from lawgraph.pipelines.semantic.tk import EDGE_SOURCE as TK_SOURCE
from lawgraph.pipelines.semantic.tk_amendment_articles import (
    EDGE_SOURCE as ARTICLES_SOURCE,
)
from lawgraph.pipelines.semantic.tk_amends import EDGE_SOURCE as AMENDS_SOURCE

DOSSIER_TITLE = (
    "Regels ter implementatie van Richtlijn (EU) 2022/2555 van het Europees Parlement en "
    "de Raad van 14 december 2022 betreffende maatregelen voor een hoog gezamenlijk niveau "
    "van cyberbeveiliging in de Unie, tot wijziging van Verordening (EU) nr. 910/2014 en "
    "Richtlijn (EU) 2018/1972 en tot intrekking van Richtlijn (EU) 2016/1148 (PbEU 2022, "
    "L 333) (Cyberbeveiligingswet)"
)
CBW = f"{COLLECTION_INSTRUMENTS}/bwbr0052872"
CBW_16 = f"{COLLECTION_ARTICLES}/bwbr0052872_16"
NIS2 = f"{COLLECTION_INSTRUMENTS}/32022l2555"
VITAMINE_D = f"{COLLECTION_INSTRUMENTS}/bwbr0011936"


def _put(
    store: GraphStore, collection: str, key: str, labels: list[str], **props: Any
) -> None:
    store.bulk_insert_or_update_nodes(
        collection,
        [
            {
                "key": key,
                "type": collection.rstrip("s"),
                "labels": labels,
                "props": props,
            }
        ],
    )


def _targets(store: GraphStore, relation: str, source: str, document: str) -> set[str]:
    return set(
        store.query(
            "SELECT to_id FROM edges"
            " WHERE from_id = %(d)s AND relation = %(r)s AND source = %(s)s",
            {"d": f"{COLLECTION_DOCUMENTS}/{document}", "r": relation, "s": source},
        )
    )


def _laws(store: GraphStore) -> None:
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        "bwbr0052872",
        ["BWB"],
        bwb_id="BWBR0052872",
        title="Cyberbeveiligingswet",
        citation_title="Cyberbeveiligingswet",
    )
    _put(
        store,
        COLLECTION_ARTICLES,
        "bwbr0052872_16",
        ["Article"],
        bwb_id="BWBR0052872",
        article_number="16",
    )
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        "32022l2555",
        ["EU"],
        celex="32022L2555",
        title="Richtlijn (EU) 2022/2555 van het Europees Parlement en de Raad",
        citation_title="Richtlijn (EU) 2022/2555",
    )
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        "bwbr0011936",
        ["BWB"],
        bwb_id="BWBR0011936",
        title="Warenwetregeling Vrijstelling vitamine D",
        citation_title="Warenwetregeling Vrijstelling vitamine D",
        short_title="VVD",
        aliases=["VVD"],
    )


def test_the_record_of_a_paper_is_no_text_of_it(database: str, cli: Any) -> None:
    store = GraphStore()
    _laws(store)
    record = {
        "Id": "46944024-8c5d-4003-95de-c89c22f81cb3",
        "DocumentNummer": "2026D13231",
        "Soort": "Motie",
        "Titel": DOSSIER_TITLE,
        "Onderwerp": "Motie van het lid Kathmann over één centraal meldloket",
        "DocumentActor": [
            {
                "ActorNaam": "Bikkers",
                "ActorFractie": "VVD",
                "Functie": "Tweede Kamerlid",
                "Relatie": "Mede ondertekenaar",
                "Id": "d081e81a-0000-4000-8000-000000000001",
            }
        ],
    }
    _put(
        store,
        COLLECTION_DOCUMENTS,
        "motie_19",
        ["TK"],
        external_id=record["Id"],
        kind="Motie",
        title=record["Onderwerp"],
        dossier_title=DOSSIER_TITLE,
        dossier_numbers=["36764"],
        text="De Kamer,\ngehoord de beraadslaging,\nverzoekt de regering één centraal "
        "meldloket in te richten,\nen gaat over tot de orde van de dag.\nKathmann",
        raw=record,
    )
    # a paper whose own text names the directive cites it
    _put(
        store,
        COLLECTION_DOCUMENTS,
        "brief_33",
        ["TK"],
        external_id="brief-33",
        kind="Brief regering",
        title="Brief over de implementatie",
        text="De implementatie van Richtlijn (EU) 2022/2555 is af.",
        raw={**record, "Id": "brief-33", "Soort": "Brief regering"},
    )
    # what an earlier run read in the record
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                f"{COLLECTION_DOCUMENTS}/motie_19",
                target,
                RELATION_REFERS_TO,
                source=TK_SOURCE,
                confidence=0.6,
            )
            for target in (NIS2, VITAMINE_D)
        ]
    )

    cli("semantic", "tk")

    assert _targets(store, RELATION_REFERS_TO, TK_SOURCE, "motie_19") == set()
    assert _targets(store, RELATION_REFERS_TO, TK_SOURCE, "brief_33") == {NIS2}


def test_the_papers_of_the_bill_that_made_a_law_do_not_amend_it(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _laws(store)
    _put(store, COLLECTION_DOSSIERS, "36764", ["TK"], label="36764")
    _put(store, COLLECTION_DOSSIERS, "36900", ["TK"], label="36900")
    _put(
        store,
        COLLECTION_DOCUMENTS,
        "nvw_9",
        ["TK"],
        external_id="nvw-9",
        kind="Nota van wijziging",
        date="2025-10-01",
        title="Nota van wijziging",
        dossier_title=DOSSIER_TITLE,
        dossier_numbers=["36764"],
        text='In artikel 16, eerste lid, wordt "essentiële" vervangen door "belangrijke".',
    )
    # a later bill that does change the Cyberbeveiligingswet
    _put(
        store,
        COLLECTION_DOCUMENTS,
        "bill_2",
        ["TK"],
        external_id="bill-2",
        kind="Voorstel van wet",
        date="2025-10-01",
        title="Voorstel van wet",
        dossier_title="Wijziging van de Cyberbeveiligingswet in verband met toezicht",
        dossier_numbers=["36900"],
        text="Artikel 16 wordt als volgt gewijzigd:",
    )
    # the bill was linked before its act was published
    cli("semantic", "tk-amends")
    cli("semantic", "tk-amendment-articles")
    assert _targets(store, RELATION_AMENDS, ARTICLES_SOURCE, "nvw_9") == {CBW_16}

    # the act is published and names its dossier (BWB brondata); the papers are not read
    # again by the daily run
    store.bulk_insert_or_update_edges(
        [make_edge_doc(CBW, f"{COLLECTION_DOSSIERS}/36764", RELATION_LEGISLATED_IN)]
    )
    cli("semantic", "tk-amends", "--since", "2099-01-01")
    cli("semantic", "tk-amendment-articles")

    assert _targets(store, RELATION_AMENDS, AMENDS_SOURCE, "nvw_9") == set()
    assert _targets(store, RELATION_AMENDS, ARTICLES_SOURCE, "nvw_9") == set()
    assert _targets(store, RELATION_AMENDS, AMENDS_SOURCE, "bill_2") == {CBW}
    assert _targets(store, RELATION_AMENDS, ARTICLES_SOURCE, "bill_2") == {CBW_16}
    statuses = set(
        store.query(
            "SELECT status FROM edges WHERE source = %(s)s", {"s": ARTICLES_SOURCE}
        )
    )
    assert statuses == {EDGE_STATUS_VOORGESTELD}
