"""What a bill's title names that it does not amend, for real (dossier 36931, 2026): the EU
act it implements, and the act it makes itself, whose citeertitel closes the title and which
the BWB names as ``LEGISLATED_IN`` the dossier once it is published. The laws it changes keep
their AMENDS edge."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_ZAAK,
    RELATION_AMENDS,
    RELATION_LEGISLATED_IN,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, RawSourceWriter, make_edge_doc, raw_source_doc
from lawgraph.pipelines.semantic.tk_amends import SEMANTIC_SOURCE_AMENDS
from tests.integration.seed import uid

TITLE = (
    "Wijziging van de Wet op het financieel toezicht, de Wet toezicht "
    "accountantsorganisaties, het Burgerlijk Wetboek en enkele andere wetten in verband met "
    "de implementatie van Verordening (EU) 2023/2859, Richtlijn (EU) 2023/2864 en "
    "Verordening (EU) 2023/2869 betreffende het Europees centraal toegangspunt (Wet "
    "implementatie Europees centraal toegangspunt)"
)
DOSSIER = {"Id": uid(2, 3), "Nummer": 36931, "Toevoeging": None, "Titel": TITLE}
CASE = {
    "Id": uid(2, 2),
    "Nummer": "2026Z20001",
    "Soort": "Wetgeving",
    "Titel": TITLE,
    "Onderwerp": TITLE,
    "Kamerstukdossier": [{"Id": DOSSIER["Id"], "Nummer": 36931}],
}
BILL = {
    "Id": uid(2, 1),
    "DocumentNummer": "2026D20001",
    "Soort": "Voorstel van wet",
    "Titel": TITLE,
    "Onderwerp": "Voorstel van wet",
    "Datum": "2026-05-12T00:00:00+02:00",
    "Volgnummer": 2,
    "Verwijderd": False,
    "Zaak": [
        {
            **{k: CASE[k] for k in ("Id", "Nummer", "Soort", "Titel")},
            "Kamerstukdossier": [DOSSIER],
        }
    ],
    "DocumentActor": [],
}
# key, ids, name
INSTRUMENTS = [
    ("bwbr0020368", {"bwb_id": "BWBR0020368"}, "Wet op het financieel toezicht"),
    ("bwbr0019079", {"bwb_id": "BWBR0019079"}, "Wet toezicht accountantsorganisaties"),
    (
        "bwbr0052854",
        {"bwb_id": "BWBR0052854"},
        "Wet implementatie Europees centraal toegangspunt",
    ),
    ("32023r2869", {"celex": "32023R2869"}, "Verordening (EU) 2023/2869"),
]


def test_a_bill_amends_the_laws_it_changes_only(database: str, cli: Any) -> None:
    store = GraphStore()
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "_key": key,
                "type": "instrument",
                "labels": ["BWB" if "bwb_id" in ids else "EU"],
                "props": {**ids, "title": name, "citation_title": name},
            }
            for key, ids, name in INSTRUMENTS
        ],
    )
    with RawSourceWriter(store) as writer:
        for kind, payload in (
            (RAW_KIND_TK_DOSSIER, DOSSIER),
            (RAW_KIND_TK_ZAAK, CASE),
            (RAW_KIND_TK_DOCUMENT, BILL),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )
    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")
    # the published act names its dossier (BWB brondata)
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                "instruments/bwbr0052854",
                f"dossiers/{make_node_key('36931')}",
                RELATION_LEGISLATED_IN,
                source="bwb",
            )
        ]
    )

    cli("semantic", "tk-amends")

    targets = sorted(
        store.query(
            "SELECT to_id FROM edges WHERE relation = %(relation)s AND source = %(source)s",
            {"relation": RELATION_AMENDS, "source": SEMANTIC_SOURCE_AMENDS},
        )
    )
    assert targets == ["instruments/bwbr0019079", "instruments/bwbr0020368"]
