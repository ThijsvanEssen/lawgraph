"""A member whose Persoon record the Tweede Kamer leaves empty has the name its roll-call
votes or its signatures give ("Nobel, J.N.J.", "B.J. Bruins": the same Persoon_Id); a member
of old the Kamer knows by initials and surname is named by them. The node props say it, not
only the member route. The real ``normalize tk-dossiers``."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_MEMBERS,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_STEMMING,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import (
    GraphStore,
    RawSourceWriter,
    raw_source_doc,
)
from tests.integration.seed import uid

NOBEL = uid(1, 9)
DECISION = uid(1, 7)
CASE = {"Id": uid(1, 2), "Soort": "Motie", "Onderwerp": "Motie over wonen"}
EMPTY_PERSON = {"Id": NOBEL, "Voornamen": None, "Achternaam": None}


def _roll_call_vote() -> dict[str, Any]:
    return {
        "Id": uid(1, 6),
        "Besluit_Id": DECISION,
        "Soort": "Voor",
        "FractieGrootte": 22,
        "ActorNaam": "Nobel, J.N.J.",
        "ActorFractie": "VVD",
        "Fractie_Id": uid(1, 8),
        "Persoon_Id": NOBEL,
        "GewijzigdOp": "2026-09-23T09:00:00+02:00",
        "Besluit": {
            "Id": DECISION,
            "StemmingsSoort": "Hoofdelijk",
            "BesluitSoort": "Stemmen - aangenomen",
            "BesluitTekst": "Aangenomen.",
            "AgendapuntZaakBesluitVolgorde": 1,
            "Zaak": [CASE],
            "Agendapunt": {"Onderwerp": CASE["Onderwerp"], "Zaak": [CASE]},
        },
    }


def _store(store: GraphStore, kind: str, source: str, payload: dict[str, Any]) -> None:
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=source,
                kind=kind,
                external_id=payload["Id"] if "Id" in payload else payload["id"],
                payload_json=payload,
            )
        )


def test_a_member_the_kamer_gives_no_name_is_named_by_its_votes(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _store(store, RAW_KIND_TK_PERSOON, SOURCE_TK, EMPTY_PERSON)
    _store(store, RAW_KIND_TK_STEMMING, SOURCE_TK, _roll_call_vote())

    cli("normalize", "tk-dossiers")
    cli("normalize", "tk-dossiers")  # a second run keeps the name

    member = store.get_node(COLLECTION_MEMBERS, make_node_key(NOBEL))
    assert member is not None
    assert (member.props["name"], member.props["display_name"]) == (
        "J.N.J. Nobel",
        "J.N.J. Nobel",
    )


BRUINS = uid(2, 9)
BUMA = uid(3, 9)


def _signed_letter() -> dict[str, Any]:
    """A letter the minister signed: its DocumentActor names the Persoon the Kamer leaves
    empty."""
    case = {"Id": uid(2, 2), "Soort": "Brief regering", "Onderwerp": "Zorg"}
    return {
        "Id": uid(1, 1),
        "Soort": "Brief regering",
        "Titel": "Zorg",
        "Onderwerp": "Brief over de zorg",
        "Datum": "2019-03-04T00:00:00+01:00",
        "Zaak": [case],
        "DocumentActor": [
            {
                "Id": uid(1, 4),
                "ActorNaam": "B.J. Bruins",
                "Functie": "minister voor Medische Zorg",
                "Relatie": "Eerste ondertekenaar",
                "Persoon_Id": BRUINS,
            }
        ],
    }


def test_a_member_the_kamer_gives_no_name_is_named_by_what_they_signed(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _store(store, RAW_KIND_TK_PERSOON, SOURCE_TK, {**EMPTY_PERSON, "Id": BRUINS})
    _store(store, RAW_KIND_TK_DOCUMENT, SOURCE_TK, _signed_letter())

    cli("normalize", "tk-dossiers")

    member = store.get_node(COLLECTION_MEMBERS, make_node_key(BRUINS))
    assert member is not None
    assert (member.props["name"], member.props["display_name"]) == (
        "B.J. Bruins",
        "B.J. Bruins",
    )


def test_a_member_of_old_known_by_initials_is_named_by_them(
    database: str, cli: Any
) -> None:
    """W.B. Buma (1807-1848): the Kamer gives him initials and a surname, no first name. He
    is a person of his own, not Sybrand van Haersma Buma."""
    store = GraphStore()
    buma = {
        "Id": BUMA,
        "Initialen": "WB",
        "Achternaam": "Buma",
        "Voornamen": None,
        "Roepnaam": None,
        "Functie": "Oud Kamerlid",
        "Geboortedatum": "1807-03-07",
    }
    _store(store, RAW_KIND_TK_PERSOON, SOURCE_TK, buma)

    cli("normalize", "tk-dossiers")

    member = store.get_node(COLLECTION_MEMBERS, make_node_key(BUMA))
    assert member is not None
    assert (member.props["name"], member.props["full_name"]) == (
        "W.B. Buma",
        "W.B. Buma",
    )
