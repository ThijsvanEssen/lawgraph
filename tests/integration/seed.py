"""Raw records for the integration tests: the shapes of the sources, at any scale.

The payloads follow what the APIs send (a Document with its Zaak, Kamerstukdossier and
DocumentActor; a Stemming with its Besluit; a judgment with its RDF block), and the BWB
toestanden are the recorded fixtures stored under many ids. ``seed`` writes them through the
same ``RawSourceWriter`` the retrieve pipelines use.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_RS_CONTENT,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_TOEZEGGING,
    RAW_KIND_TK_ZAAK,
    SOURCE_BWB,
    SOURCE_RECHTSPRAAK,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DOSSIERS = 50
FACTIONS = 12
MEMBERS = 60


def uid(number: int, salt: int) -> str:
    return str(uuid.UUID(int=(number << 8) + salt))


def _dossier_number(number: int) -> int:
    return 36000 + number % DOSSIERS


def _zaak(number: int) -> dict[str, Any]:
    return {
        "Id": uid(number, 2),
        "Nummer": f"2025Z{number:05d}",
        "Soort": "Wetgeving" if number % 7 == 0 else "Motie",
        "Titel": "Wijziging van de Wegenwet in verband met het beheer van wegen",
        "Onderwerp": f"Zaak {number} over het beheer van wegen",
        "Kamerstukdossier": [
            {"Id": uid(_dossier_number(number), 3), "Nummer": _dossier_number(number)}
        ],
    }


def tk_records(documents: int) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """``(kind, id, payload)`` for a Tweede Kamer of *documents* papers and as many votes."""
    for number in range(DOSSIERS):
        payload = {
            "Id": uid(number, 3),
            "Nummer": 36000 + number,
            "Toevoeging": None,
            "Titel": f"Wijziging van de Wegenwet ({number})",
            "Afgesloten": False,
        }
        yield RAW_KIND_TK_DOSSIER, payload["Id"], payload
    for number in range(FACTIONS):
        payload = {
            "Id": uid(number, 8),
            "Afkorting": f"F{number}",
            "NaamNL": f"Fractie {number}",
        }
        yield RAW_KIND_TK_FRACTIE, payload["Id"], payload
    for number in range(MEMBERS):
        payload = {
            "Id": uid(number, 5),
            "Achternaam": f"Lid{number}",
            "Voornamen": "A.",
        }
        yield RAW_KIND_TK_PERSOON, payload["Id"], payload
    for number in range(5):
        payload = {
            "Id": uid(number, 10),
            "NaamNL": f"Commissie {number}",
            "Afkorting": f"C{number}",
        }
        yield RAW_KIND_TK_COMMISSIE, payload["Id"], payload

    for number in range(documents):
        zaak = _zaak(number)
        yield RAW_KIND_TK_ZAAK, zaak["Id"], zaak
        document = {
            "Id": uid(number, 1),
            "Soort": "Memorie van toelichting" if number % 25 == 0 else "Motie",
            "DocumentNummer": f"2025D{number:05d}",
            "Titel": zaak["Titel"],
            "Onderwerp": "Motie over artikel 5 van de Wegenwet en artikel 8:1 Awb. "
            * 3,
            "Datum": "2025-03-04T00:00:00+01:00",
            "Volgnummer": number % 400 + 1,
            "Zaak": [zaak],
            "DocumentActor": [
                {
                    "Id": uid(number, 4),
                    "ActorNaam": "Lid",
                    "Relatie": "Eerste ondertekenaar",
                    "Persoon_Id": uid(number % MEMBERS, 5),
                }
            ],
        }
        yield RAW_KIND_TK_DOCUMENT, document["Id"], document
        vote = {
            "Id": uid(number, 6),
            "Besluit_Id": uid(number // FACTIONS, 7),
            "Soort": "Voor" if number % 3 else "Tegen",
            "FractieGrootte": 10,
            "ActorFractie": f"Fractie {number % FACTIONS}",
            "Fractie_Id": uid(number % FACTIONS, 8),
            "Persoon_Id": None,
            "GewijzigdOp": "2025-03-05T10:00:00+01:00",
            "Besluit": {
                "Id": uid(number // FACTIONS, 7),
                "BesluitSoort": "Stemmen - aangenomen",
                "BesluitTekst": "Aangenomen.",
                "StemmingsSoort": "Met handopsteken",
                "Zaak": [_zaak(number // FACTIONS)],
            },
        }
        yield RAW_KIND_TK_STEMMING, vote["Id"], vote
        if number % 10 == 0:
            activity = {
                "Id": uid(number, 11),
                "Nummer": f"2025A{number:05d}",
                "Soort": "Commissiedebat",
                "Datum": "2025-03-06T00:00:00+01:00",
                "Voortouwcommissie_Id": uid(number % 5, 10),
                "Agendapunt": [{"Zaak": [zaak]}],
            }
            yield RAW_KIND_TK_ACTIVITEIT, activity["Id"], activity
            commitment = {
                "Id": uid(number, 12),
                "Nummer": f"TZ{number}",
                "Tekst": "De minister zegt toe de Kamer te informeren.",
                "Status": "Openstaand",
                "ActiviteitNummer": activity["Nummer"],
            }
            yield RAW_KIND_TK_TOEZEGGING, commitment["Id"], commitment


def judgment_xml(number: int, paragraphs: int = 40) -> str:
    cited = f"ECLI:NL:HR:2020:{number + 1}"
    body = "".join(
        f"<para>De rechtbank overweegt ({number}.{i}) dat artikel 1 van de Grondwet en "
        f"artikel 8:1 Awb van toepassing zijn, zie ook {cited}.</para>"
        for i in range(paragraphs)
    )
    return (
        '<open xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dcterms="http://purl.org/dc/terms/"><rdf:RDF><rdf:Description>'
        f"<dcterms:identifier>ECLI:NL:HR:2020:{number}</dcterms:identifier>"
        "<dcterms:creator>Hoge Raad</dcterms:creator><dcterms:date>2020-01-02</dcterms:date>"
        "</rdf:Description></rdf:RDF><inhoudsindicatie><para>Samenvatting.</para>"
        f'</inhoudsindicatie><uitspraak><section nr="1"><title>Overwegingen</title>{body}'
        "</section></uitspraak></open>"
    )


def _own_title(toestand_xml: str, copy: int) -> str:
    """The fixture under another id is another law: a name two laws share links to neither."""
    if copy < 2:  # the first use of each fixture keeps its name ("Grondwet")
        return toestand_xml
    return re.sub(
        r"(<citeertitel\b[^>]*>)([^<]+)", rf"\g<1>\g<2> ({copy})", toestand_xml, count=1
    )


def seed(
    store: ArangoStore,
    *,
    documents: int = 500,
    judgments: int = 100,
    regulations: int = 20,
) -> int:
    """Write the raw records; returns how many."""
    toestanden = [
        (FIXTURES / name).read_text()
        for name in ("bwb_grondwet_toestand.xml", "bwb_amvb_toestand.xml")
    ]
    with RawSourceWriter(store) as writer:
        for kind, external_id, payload in tk_records(documents):
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=external_id,
                    payload_json=payload,
                )
            )
        for number in range(regulations):
            bwb_id = "BWBR0001840" if number == 0 else f"BWBR{9000000 + number:07d}"
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND,
                    external_id=bwb_id,
                    payload_text=_own_title(
                        toestanden[number % len(toestanden)], number
                    ),
                    meta={
                        "bwb_id": bwb_id,
                        "state_url": f"https://repo/{bwb_id}/x.xml",
                    },
                )
            )
        for number in range(judgments):
            ecli = f"ECLI:NL:HR:2020:{number}"
            writer.add(
                raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_CONTENT,
                    external_id=ecli,
                    payload_text=judgment_xml(number),
                    meta={"ecli": ecli},
                )
            )
    return writer.written
