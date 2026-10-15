"""DocumentActor and ZaakActor: who signed a paper or submitted a case, and in which
capacity."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Final, Literal

from lawgraph.core.models import make_node_key
from lawgraph.core.tk_records._payload import (
    Payload,
    dicts,
    distinct,
)
from lawgraph.core.tk_records.committees import PLENARY_VOORTOUW
from lawgraph.core.tk_records.kinds import is_motion_or_amendment

# DocumentActor.Relatie of who signs a paper first, and of who signs with them.
FIRST_SIGNATORY: Final = "Eerste ondertekenaar"
CO_SIGNATORY: Final = "Mede ondertekenaar"
# The role we give who submits a motie or amendement, by their DocumentActor.Relatie.
SubmitterRole = Literal["indiener", "medeindiener"]
SUBMITTER_FIRST: Final[SubmitterRole] = "indiener"
SUBMITTER_CO: Final[SubmitterRole] = "medeindiener"
_SUBMITTER_ROLES: dict[str, SubmitterRole] = {
    FIRST_SIGNATORY: SUBMITTER_FIRST,
    CO_SIGNATORY: SUBMITTER_CO,
}


# The capacity a document is signed in (see ``signing_capacity``).
SigningCapacity = Literal["kamerlid", "bewindspersoon", "overig"]
CAPACITY_MEMBER: Final[SigningCapacity] = "kamerlid"
CAPACITY_GOVERNMENT: Final[SigningCapacity] = "bewindspersoon"
CAPACITY_OTHER: Final[SigningCapacity] = "overig"


# DocumentActor.Functie of a member of the government: "minister van Financiën", "minister voor
# Klimaat en Energie", "minister-president", "viceminister-president", "staatssecretaris van
# Defensie". Not "gevolmachtigde minister van Aruba", who speaks for Aruba.
_GOVERNMENT_FUNCTION = re.compile(
    r"^(?:(?:vice)?minister(?:-president)?|staatssecretaris)\b", re.IGNORECASE
)


def signing_capacity(function: str | None, faction: str | None) -> str:
    """In which capacity a person signed a document: ``bewindspersoon``, ``kamerlid`` or
    ``overig``.

    A person's role changes over time (R.A.A. Jetten signed as Tweede Kamerlid until 2025
    and as minister-president in 2026), so the capacity is read from each signature, not
    from the person. ``bewindspersoon`` when the function (``DocumentActor.Functie``) names a
    minister, the minister-president or a staatssecretaris; ``kamerlid`` when the signature
    is for a faction (a member, also as chair of a committee); ``overig`` otherwise: the
    griffier, the vice-president of the Raad van State, the Algemene Rekenkamer. No minister
    or staatssecretaris signs for a faction in the source.
    """
    if _GOVERNMENT_FUNCTION.match((function or "").strip()):
        return CAPACITY_GOVERNMENT
    if faction:
        return CAPACITY_MEMBER
    return CAPACITY_OTHER


def document_actors(payload: Payload) -> list[dict[str, Any]]:
    """Signatories of a Document, from the DocumentActor expansion.

    ``function`` is the function they signed in (``Functie``, as the source writes it) and
    ``capacity`` what that makes the signature (``signing_capacity``).
    """
    actors: list[dict[str, Any]] = []
    for actor in dicts(payload.get("DocumentActor")):
        person_id = str(actor.get("Persoon_Id") or "") or None
        name = actor.get("ActorNaam") or ""
        if not (person_id or name):
            continue
        faction_id = str(actor.get("Fractie_Id") or "") or None
        faction = actor.get("ActorFractie") or ""
        function = (actor.get("Functie") or "").strip() or None
        actors.append(
            {
                "person_id": person_id,
                "faction_id": faction_id,
                "name": name,
                "faction": faction,
                "role": actor.get("Relatie") or "",
                "function": function,
                "capacity": signing_capacity(function, faction_id or faction),
            }
        )
    return actors


# The ZaakActor relations of the people who submitted a Zaak, and of its lead committee.
CASE_SUBMITTER_RELATIONS = ("Indiener", "Medeindiener")
CASE_LEAD_RELATION = "Voortouwcommissie"


def case_actors(payload: Payload) -> dict[str, Any]:
    """Who submitted a Zaak and which committee leads it, from its ``ZaakActor``:
    ``submitters`` (``person_id``, ``role`` as the source writes it, ``function`` and the
    ``capacity`` that makes it, as ``document_actors``) and ``committee_ids`` (the
    voortouwcommissie; none when the plenary leads, as for an activity). Read from a record
    of ``retrieve tk-case-actors``."""
    actors = list(dicts(payload.get("ZaakActor")))
    submitters = []
    for actor in actors:
        person_id = str(actor.get("Persoon_Id") or "")
        if actor.get("Relatie") not in CASE_SUBMITTER_RELATIONS or not person_id:
            continue
        function = (actor.get("Functie") or "").strip() or None
        submitters.append(
            {
                "person_id": person_id,
                "role": actor["Relatie"],
                "function": function,
                "capacity": signing_capacity(
                    function, str(actor.get("Fractie_Id") or "") or None
                ),
            }
        )
    return {
        "submitters": submitters,
        "committee_ids": distinct(
            [
                str(actor.get("Commissie_Id") or "")
                for actor in actors
                if actor.get("Relatie") == CASE_LEAD_RELATION
                and actor.get("ActorAfkorting") != PLENARY_VOORTOUW
            ]
        ),
    }


def submitters(
    kind: str | None, actors: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Who submitted a motie or amendement, the indiener first: ``name``, ``faction``,
    ``member_key`` (their Member node, when the source names the person) and ``role``
    (``indiener`` or ``medeindiener``). Empty for any other kind of paper, whose first
    signatory is no indiener.

    *actors* are the signatures ``document_actors`` reads.
    """
    if not is_motion_or_amendment(kind):
        return []
    rows = [
        {
            "name": actor.get("name") or "",
            "faction": actor.get("faction") or None,
            "member_key": (
                make_node_key(str(actor["person_id"]))
                if actor.get("person_id")
                else None
            ),
            "role": _SUBMITTER_ROLES[actor.get("role") or ""],
        }
        for actor in actors
        if (actor.get("role") or "") in _SUBMITTER_ROLES
    ]
    return sorted(rows, key=lambda row: row["role"] != SUBMITTER_FIRST)
