"""Only an amendement and the text of a bill amend a law: a motie, a letter or a memorandum
on the bill's dossier carries its title and amends nothing."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    EDGE_STATUS_VOORGESTELD,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_ZAAK,
    RELATION_AMENDS,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, RawSourceWriter, make_edge_doc, raw_source_doc
from lawgraph.pipelines.semantic.tk_amends import SEMANTIC_SOURCE_AMENDS
from tests.integration.seed import uid

BWB_ID = "BWBR0005537"
LAW = "Wet op de rechtsbijstand"
DOSSIER_TITLE = f"Wijziging van de {LAW} in verband met de eigen bijdrage"
DOSSIER = {"Id": uid(1, 3), "Nummer": 36990, "Toevoeging": None, "Titel": DOSSIER_TITLE}
BILL_CASE = {
    "Id": uid(1, 2),
    "Nummer": "2026Z10001",
    "Soort": "Wetgeving",
    "Titel": DOSSIER_TITLE,
    "Onderwerp": DOSSIER_TITLE,
    "Kamerstukdossier": [{"Id": DOSSIER["Id"], "Nummer": 36990}],
}

# (number, Soort, Onderwerp) of the papers on the bill's dossier.
PAPERS = [
    (1, "Voorstel van wet", "Voorstel van wet"),
    (2, "Nota van wijziging", "Tweede nota van wijziging"),
    (3, "Amendement", "Amendement van het lid Ellian over de eigen bijdrage"),
    (4, "Motie", "Motie van het lid Faber over de eigen bijdrage"),
    (5, "Motie (gewijzigd/nader)", "Gewijzigde motie van het lid Faber"),
    (
        6,
        "Nota n.a.v. het (nader/tweede nader/enz.) verslag",
        "Nota naar aanleiding van het verslag",
    ),
    (7, "Brief regering", DOSSIER_TITLE),
    (8, "Verslag van een wetgevingsoverleg", DOSSIER_TITLE),
]
AMENDING = {"Voorstel van wet", "Nota van wijziging", "Amendement"}


def _paper(number: int, kind: str, subject: str) -> dict[str, Any]:
    return {
        "Id": uid(number, 1),
        "DocumentNummer": f"2026D1000{number}",
        "Soort": kind,
        "Titel": DOSSIER_TITLE,
        "Onderwerp": subject,
        "Datum": "2026-09-10T00:00:00+02:00",
        "Volgnummer": number,
        "Verwijderd": False,
        "Zaak": [
            {
                **{k: BILL_CASE[k] for k in ("Id", "Nummer", "Soort", "Titel")},
                "Kamerstukdossier": [DOSSIER],
            }
        ],
        "DocumentActor": [],
    }


def _write(store: GraphStore) -> None:
    with RawSourceWriter(store) as writer:
        for kind, payload in [
            (RAW_KIND_TK_DOSSIER, DOSSIER),
            (RAW_KIND_TK_ZAAK, BILL_CASE),
            *((RAW_KIND_TK_DOCUMENT, _paper(*paper)) for paper in PAPERS),
        ]:
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )


def _amending_kinds(store: GraphStore) -> list[str]:
    rows = store.query(
        """
        SELECT n.props ->> 'kind' FROM edges e LEFT JOIN nodes n ON n.id = e.from_id
        WHERE e.relation = %(relation)s AND e.source = %(source)s
        """,
        {"relation": RELATION_AMENDS, "source": SEMANTIC_SOURCE_AMENDS},
    )
    return sorted(rows)


def test_only_an_amendement_and_the_bill_amend_the_law(database: str, cli: Any) -> None:
    store = GraphStore()
    law = f"instruments/{make_node_key(BWB_ID)}"
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "_key": make_node_key(BWB_ID),
                "type": "instrument",
                "labels": ["BWB"],
                "props": {"bwb_id": BWB_ID, "title": LAW, "citation_title": LAW},
            }
        ],
    )
    _write(store)
    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")

    # What an earlier run wrote: an AMENDS edge from every paper whose title named the law.
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                f"documents/{make_node_key(uid(number, 1))}",
                law,
                RELATION_AMENDS,
                source=SEMANTIC_SOURCE_AMENDS,
                confidence=0.85,
                status=EDGE_STATUS_VOORGESTELD,
            )
            for number, _kind, _subject in PAPERS
        ]
    )

    cli("semantic", "tk-amends")

    assert _amending_kinds(store) == sorted(AMENDING)
