"""Raw records for the integration tests: the shapes of the sources, at any scale.

The payloads follow what the APIs send (a Document with its Zaak, Kamerstukdossier and
DocumentActor; a Stemming with its Besluit; a judgment with its RDF block), and the BWB
toestanden are the recorded fixtures stored under many ids. ``seed`` writes them through the
same ``RawSourceWriter`` the retrieve pipelines use.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Iterator, Mapping
from enum import IntEnum
from pathlib import Path
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_RECHTSPRAAK_CONTENT,
    RAW_KIND_RIJKSOVERHEID_CABINET,
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
    SOURCE_RIJKSOVERHEID,
    SOURCE_TK,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DOSSIERS = 50
FACTIONS = 12
MEMBERS = 60


class Salt(IntEnum):
    """The kind of record an id of ``uid`` is of: two kinds never share an id."""

    DOCUMENT = 1
    CASE = 2
    DOSSIER = 3
    DOCUMENT_ACTOR = 4
    PERSON = 5
    VOTE = 6
    DECISION = 7
    FACTION = 8
    COMMITTEE = 10
    ACTIVITY = 11
    COMMITMENT = 12
    # the seats of ``tk_seat``, written apart from ``tk_records``: the numbers of a person
    # and of an actor
    MEMBER_SEAT = 5
    FACTION_SEAT = 4


def uid(number: int, salt: int) -> str:
    """The id of record *number* of the kind *salt* (a ``Salt`` here; a test of its own
    takes a number no ``Salt`` has)."""
    return str(uuid.UUID(int=(number << 8) + salt))


def _dossier_number(number: int) -> int:
    return 36000 + number % DOSSIERS


def _zaak(number: int) -> dict[str, Any]:
    return {
        "Id": uid(number, Salt.CASE),
        "Nummer": f"2025Z{number:05d}",
        "Soort": "Wetgeving" if number % 7 == 0 else "Motie",
        "Titel": "Wijziging van de Wegenwet in verband met het beheer van wegen",
        "Onderwerp": f"Zaak {number} over het beheer van wegen",
        "Kamerstukdossier": [
            {
                "Id": uid(_dossier_number(number), Salt.DOSSIER),
                "Nummer": _dossier_number(number),
            }
        ],
    }


def tk_records(documents: int) -> Iterator[tuple[str, dict[str, Any]]]:
    """``(kind, payload)`` for a Tweede Kamer of *documents* papers and as many votes."""
    for number in range(DOSSIERS):
        payload = {
            "Id": uid(number, Salt.DOSSIER),
            "Nummer": 36000 + number,
            "Toevoeging": None,
            "Titel": f"Wijziging van de Wegenwet ({number})",
            "Afgesloten": False,
        }
        yield RAW_KIND_TK_DOSSIER, payload
    for number in range(FACTIONS):
        payload = {
            "Id": uid(number, Salt.FACTION),
            "Afkorting": f"F{number}",
            "NaamNL": f"Fractie {number}",
        }
        yield RAW_KIND_TK_FRACTIE, payload
    for number in range(MEMBERS):
        payload = {
            "Id": uid(number, Salt.PERSON),
            "Achternaam": f"Lid{number}",
            "Voornamen": "A.",
        }
        yield RAW_KIND_TK_PERSOON, payload
    for number in range(5):
        payload = {
            "Id": uid(number, Salt.COMMITTEE),
            "NaamNL": f"Commissie {number}",
            "Afkorting": f"C{number}",
        }
        yield RAW_KIND_TK_COMMISSIE, payload

    for number in range(documents):
        zaak = _zaak(number)
        yield RAW_KIND_TK_ZAAK, zaak
        document = {
            "Id": uid(number, Salt.DOCUMENT),
            "Soort": "Memorie van toelichting" if number % 25 == 0 else "Motie",
            "DocumentNummer": f"2025D{number:05d}",
            "Titel": zaak["Titel"],
            "Onderwerp": "Motie over artikel 5 van de Wegenwet en artikel 8:1 Awb. "
            * 3,
            "Datum": "2025-03-04T00:00:00+01:00",
            "Volgnummer": number % 400 + 1,
            "Zaak": [zaak],
            "Kamerstukdossier": zaak["Kamerstukdossier"],
            "DocumentActor": [
                {
                    "Id": uid(number, Salt.DOCUMENT_ACTOR),
                    "ActorNaam": "Lid",
                    "Relatie": "Eerste ondertekenaar",
                    "Persoon_Id": uid(number % MEMBERS, Salt.PERSON),
                }
            ],
        }
        yield RAW_KIND_TK_DOCUMENT, document
        vote = {
            "Id": uid(number, Salt.VOTE),
            "Besluit_Id": uid(number // FACTIONS, Salt.DECISION),
            "Soort": "Voor" if number % 3 else "Tegen",
            "FractieGrootte": 10,
            "ActorFractie": f"Fractie {number % FACTIONS}",
            "Fractie_Id": uid(number % FACTIONS, Salt.FACTION),
            "Persoon_Id": None,
            "GewijzigdOp": "2025-03-05T10:00:00+01:00",
            "Besluit": {
                "Id": uid(number // FACTIONS, Salt.DECISION),
                "BesluitSoort": "Stemmen - aangenomen",
                "BesluitTekst": "Aangenomen.",
                "StemmingsSoort": "Met handopsteken",
                "Zaak": [_zaak(number // FACTIONS)],
            },
        }
        yield RAW_KIND_TK_STEMMING, vote
        if number % 10 == 0:
            activity = {
                "Id": uid(number, Salt.ACTIVITY),
                "Nummer": f"2025A{number:05d}",
                "Soort": "Commissiedebat",
                "Datum": "2025-03-06T00:00:00+01:00",
                "Voortouwcommissie_Id": uid(number % 5, Salt.COMMITTEE),
                "Agendapunt": [{"Zaak": [zaak]}],
            }
            yield RAW_KIND_TK_ACTIVITEIT, activity
            commitment = {
                "Id": uid(number, Salt.COMMITMENT),
                "Nummer": f"TZ{number}",
                "Tekst": "De minister zegt toe de Kamer te informeren.",
                "Status": "Openstaand",
                "ActiviteitNummer": activity["Nummer"],
            }
            yield RAW_KIND_TK_TOEZEGGING, commitment


# The namespaces of the metadata of Rechtspraak, as ``open-rechtspraak`` declares them.
RECHTSPRAAK_NS = (
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:psi="http://psi.rechtspraak.nl/" '
    'xmlns:ecli="https://e-justice.europa.eu/ecli"'
)


def judgment_xml(
    ecli: str,
    date: str,
    paragraphs: list[tuple[str, str]],
    *,
    court: str = "Een rechter",
    summary: str | None = None,
    law_references: tuple[str, ...] = (),
) -> str:
    """A judgment of Rechtspraak: its ECLI, court and date, and one section of numbered
    paragraphs ``(number, text)``, with its *summary* (``inhoudsindicatie``) if any and
    a ``Wetsverwijzing`` in its metadata per jci of *law_references*
    (``jci1.31:c:BWBR0001840&artikel=1``)."""
    references = "".join(
        '<dcterms:references rdfs:label="Wetsverwijzing" '
        f'bwb:resourceIdentifier="{jci.replace("&", "&amp;")}">x</dcterms:references>'
        for jci in law_references
    )
    body = "".join(
        f"<paragroup><nr>{number}</nr><para>{text}</para></paragroup>"
        for number, text in paragraphs
    )
    summary_xml = (
        f"<inhoudsindicatie><para>{summary}</para></inhoudsindicatie>"
        if summary is not None
        else ""
    )
    return (
        '<open xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#" '
        'xmlns:bwb="bwb-dl"><rdf:RDF><rdf:Description>'
        f"<dcterms:identifier>{ecli}</dcterms:identifier>"
        f"<dcterms:creator>{court}</dcterms:creator><dcterms:date>{date}</dcterms:date>"
        f"{references}</rdf:Description></rdf:RDF>{summary_xml}<uitspraak><section>"
        f"<title><nr>1</nr>Overwegingen</title>{body}</section></uitspraak></open>"
    )


def seed_judgment_xml(number: int, paragraphs: int = 40) -> str:
    """Judgment *number* of ``seed``: of the Hoge Raad, its paragraphs citing article 1 of
    the Grondwet, article 8:1 Awb and the next judgment."""
    cited = f"ECLI:NL:HR:2020:{number + 1}"
    return judgment_xml(
        f"ECLI:NL:HR:2020:{number}",
        "2020-01-02",
        [
            (
                f"1.{i}",
                f"De rechtbank overweegt ({number}.{i}) dat artikel 1 van de Grondwet en "
                f"artikel 8:1 Awb van toepassing zijn, zie ook {cited}.",
            )
            for i in range(paragraphs)
        ],
        court="Hoge Raad",
        summary="Samenvatting.",
    )


def rechtspraak_relation(ecli: str, kind: str, instance: str) -> str:
    """A ``dcterms:relation`` of the metadata: to *ecli*, of *kind* (``conclusie``), in
    *instance* (``eerdereAanleg``)."""
    return (
        f'<dcterms:relation ecli:resourceIdentifier="{ecli}" '
        f'psi:type="http://psi.rechtspraak.nl/{kind}" '
        f'psi:aanleg="http://psi.rechtspraak.nl/{instance}">{ecli}</dcterms:relation>'
    )


def rechtspraak_xml(
    ecli: str,
    court: str,
    date: str,
    case_number: str,
    *,
    document_type: str = "Uitspraak",
    procedure: str | None = None,
    relations: str = "",
    text: str = "De rechter beslist.",
) -> str:
    """A judgment with the metadata that ties it to others: its case number, its type
    (``Uitspraak`` or ``Conclusie``), its procedure and its *relations*."""
    procedure_xml = f"<psi:procedure>{procedure}</psi:procedure>" if procedure else ""
    return (
        f"<open-rechtspraak {RECHTSPRAAK_NS}><rdf:RDF><rdf:Description>"
        f"<dcterms:identifier>{ecli}</dcterms:identifier>"
        f"<dcterms:creator>{court}</dcterms:creator><dcterms:date>{date}</dcterms:date>"
        f"<psi:zaaknummer>{case_number}</psi:zaaknummer>"
        f"<dcterms:type>{document_type}</dcterms:type>{procedure_xml}{relations}"
        "</rdf:Description></rdf:RDF><uitspraak><section>"
        f"<title><nr>1</nr>De procedure</title><paragroup><nr>1.1</nr><para>{text}</para>"
        "</paragroup></section></uitspraak></open-rechtspraak>"
    )


def write_tk(store: GraphStore, records: Iterable[tuple[str, dict[str, Any]]]) -> int:
    """Store Tweede Kamer records ``(kind, payload)`` under the ``Id`` of each payload, as
    ``retrieve tk`` does; returns how many."""
    with RawSourceWriter(store) as writer:
        for kind, payload in records:
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )
    return writer.written


def write_judgments(store: GraphStore, judgments: Mapping[str, str]) -> int:
    """Store the content of judgments ``{ecli: xml}``, as ``retrieve rechtspraak`` does;
    returns how many."""
    with RawSourceWriter(store) as writer:
        for ecli, xml in judgments.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RECHTSPRAAK_CONTENT,
                    external_id=ecli,
                    payload_text=xml,
                    meta={"ecli": ecli},
                )
            )
    return writer.written


def write_withdrawn(store: GraphStore, ecli: str) -> None:
    """Store the record ``retrieve rechtspraak`` keeps of a judgment the Rechtspraak
    withdrew before it was stored: no XML, ``meta.withdrawn``."""
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RECHTSPRAAK_CONTENT,
                external_id=ecli,
                payload_text="",
                meta={"ecli": ecli, "withdrawn": "ecli"},
            )
        )


def write_toestanden(
    store: GraphStore, toestanden: Iterable[tuple[str, str, str, dict[str, Any]]]
) -> int:
    """Store BWB records ``(kind, id, xml, meta)``, as ``retrieve bwb`` does (*meta* holds
    ``bwb_id`` and ``state_url``, and of a toestand its dates); returns how many."""
    with RawSourceWriter(store) as writer:
        for kind, external_id, xml, meta in toestanden:
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=kind,
                    external_id=external_id,
                    payload_text=xml,
                    meta=meta,
                )
            )
    return writer.written


def _own_title(toestand_xml: str, copy: int) -> str:
    """The fixture under another id is another law: a name two laws share links to neither."""
    if copy < 2:  # the first use of each fixture keeps its name ("Grondwet")
        return toestand_xml
    return re.sub(
        r"(<citeertitel\b[^>]*>)([^<]+)", rf"\g<1>\g<2> ({copy})", toestand_xml, count=1
    )


def seed(
    store: GraphStore,
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
    regulation_ids = [
        "BWBR0001840" if number == 0 else f"BWBR{9000000 + number:07d}"
        for number in range(regulations)
    ]
    written = write_tk(store, tk_records(documents))
    written += write_toestanden(
        store,
        (
            (
                RAW_KIND_BWB_TOESTAND,
                bwb_id,
                _own_title(toestanden[number % len(toestanden)], number),
                {"bwb_id": bwb_id, "state_url": f"https://repo/{bwb_id}/x.xml"},
            )
            for number, bwb_id in enumerate(regulation_ids)
        ),
    )
    written += write_judgments(
        store,
        {
            f"ECLI:NL:HR:2020:{number}": seed_judgment_xml(number)
            for number in range(judgments)
        },
    )
    return written


def tk_faction(fid: str, label: str, start: str, end: str | None, seats: int) -> dict:
    return {
        "Id": fid,
        "Afkorting": label,
        "NaamNL": label,
        "DatumActief": f"{start}T00:00:00+02:00",
        "DatumInactief": f"{end}T00:00:00+02:00" if end else None,
        "AantalZetels": seats,
        "GewijzigdOp": "2026-06-23T09:00:00+02:00",
    }


def tk_person(pid: str, first: str, last: str) -> dict:
    return {"Id": pid, "Voornamen": first, "Roepnaam": first, "Achternaam": last}


def tk_seat(
    number: int, pid: str, fid: str, start: str, end: str | None, role: str = "Lid"
) -> dict:
    return {
        "Id": uid(number, Salt.MEMBER_SEAT),
        "Persoon_Id": pid,
        "FractieZetel": {"Id": uid(number, Salt.FACTION_SEAT), "Fractie_Id": fid},
        "Van": f"{start}T00:00:00+02:00",
        "TotEnMet": f"{end}T00:00:00+02:00" if end else None,
        "Functie": role,
    }


def cabinet_page(name: str, sworn_in: str, *seats: tuple[str, list[str]]) -> str:
    """A cabinet page as Rijksoverheid writes one: title, introduction, ministers and the
    formatie block with the day of the beëdiging."""
    items = "".join(f"<li>{h}<br/>{'<br/>'.join(lines)}</li>" for h, lines in seats)
    return (
        f"<h1>Kabinet-{name}</h1>"
        f'<div class="rich-text larger-text"><p>Op {sworn_in} was de beëdiging van het '
        f"kabinet-{name}.</p></div>"
        f'<div class="rich-text"><h2>Ministers</h2><ul>{items}</ul></div>'
        f'<div class="rich-text"><h2>Kabinetsformatie</h2><ul>'
        f"<li>Beëdiging kabinet: {sworn_in}</li></ul></div>"
    )


def write_cabinet_pages(store: GraphStore, pages: dict[str, str]) -> None:
    with RawSourceWriter(store) as writer:
        for slug, html in pages.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_RIJKSOVERHEID,
                    kind=RAW_KIND_RIJKSOVERHEID_CABINET,
                    external_id=slug,
                    payload_text=html,
                    meta={
                        "url": f"https://example.org/{slug}",
                        "read_on": "2026-09-25",
                    },
                )
            )
