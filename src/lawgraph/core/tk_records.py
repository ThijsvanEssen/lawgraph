"""Readers for Tweede Kamer OData records: one payload in, node props out.

The field names read here (``Voortouwcommissie_Id``, ``Agendapunt``,
``FractieGrootte``) are the TK API's own. Everything these functions return is
graph vocabulary: a node key plus a props mapping, ready to wrap in a ``Node``.

Nothing in this module touches the database, so every reader is unit-testable
against a single recorded payload.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import SOURCE_TK
from lawgraph.core.display import shorten
from lawgraph.core.dossier_numbers import dossier_order
from lawgraph.core.dossier_stages import dossier_display_name
from lawgraph.core.models import make_node_key
from lawgraph.core.time import iso_date
from lawgraph.core.values import first_str

Payload = dict[str, Any]
Record = tuple[str, dict[str, Any]]

# Toezegging.Status of a commitment still to be kept (the others: Afgedaan, Nagekomen, Niet
# nagekomen, Deels Afgedaan, Vervallen). A commitment keeps the Status the Kamer gives it.
COMMITMENT_OPEN = "Openstaand"

# Stemming.Soort values that mean the vote was cast in favour / against; any
# other value ("Onthouden", "Niet deelgenomen") is kept as the source wrote it.
VOTE_FOR = "Voor"
VOTE_AGAINST = "Tegen"

VOTE_KIND_MEMBER = "member"
VOTE_KIND_FACTION = "faction"

# Activiteit.Voortouwafkorting of an activity of the Kamer as a whole: a plenary debate, the
# votes, the regeling van werkzaamheden. Its Voortouwcommissie_Id names a Commissie record
# that has no name, because the plenary is no committee.
PLENARY_VOORTOUW = "TK"

_COMMITMENT_TEXT_FIELDS = ("Tekst", "TekstAlgemeen", "TekstBrief")

# The Soort prefixes of a motie or amendement (see ``is_motion_or_amendment``).
_MOTION_OR_AMENDMENT_KINDS = ("motie", "amendement")

# The Soort prefixes of a Document or Zaak named by its own Onderwerp (see
# ``is_named_by_subject``): a motie, an amendement, a letter, the report of a debate or a
# visit, a list of questions. The Onderwerp of a bill, its memorandum or the reports on it
# names only the kind of paper (``Voorstel van wet``, ``Nota naar aanleiding van het
# verslag``); those keep their Titel.
_OWN_SUBJECT_KINDS = (
    *_MOTION_OR_AMENDMENT_KINDS,
    "brief ",
    "rapport/brief",
    "verslag van een ",
    "inbreng verslag",
    "lijst van vragen",
    "mededeling",
    "overig",
    "advies van andere adviesorganen",
)

# The Soort prefixes of a paper that changes the text of a bill, and so the law it amends
# (see ``may_amend``): an amendement, the bill and its notes of change, the text as it
# stands or as it was passed, and the memorandum, which sets out the changes article by
# article (``semantic tk-amendment-articles`` reads them in its text).
_AMENDING_KINDS = (
    "amendement",
    "voorstel van wet",
    "memorie van toelichting",
    "nota van wijziging",
    "nota van verbetering",
    "wijzigingen voorgesteld door de regering",
    "oorspronkelijke tekst",
    "bijgewerkte tekst",
    "eindtekst",
)

# DocumentActor.Relatie of who submits a motie or amendement -> the role we give them.
SUBMITTER_FIRST = "indiener"
SUBMITTER_CO = "medeindiener"
_SUBMITTER_ROLES = {
    "Eerste ondertekenaar": SUBMITTER_FIRST,
    "Mede ondertekenaar": SUBMITTER_CO,
}


def _dicts(value: Any) -> Iterator[Payload]:
    """Yield the dicts in *value*, which TK gives as a list, a dict or null."""
    if isinstance(value, dict):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def _text(payload: Payload, *fields: str) -> str:
    """First non-empty string among *fields*."""
    for field in fields:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _external_id(payload: Payload) -> str:
    return str(payload.get("Id") or "")


def is_deleted(payload: Payload) -> bool:
    """Whether the Kamer deleted the record: it then holds its id and nothing else."""
    return payload.get("Verwijderd") is True


def is_motion_or_amendment(kind: str | None) -> bool:
    """A ``Soort`` of a motie or amendement, also a changed one (``Motie (gewijzigd/nader)``,
    ``Amendement (gewijzigd/nader/vervangend)``), of a Document or a Zaak.

    Its ``Titel`` is the title of its dossier; its ``Onderwerp`` is its own: ``Motie van het
    lid Faber over …``.
    """
    return (kind or "").lower().startswith(_MOTION_OR_AMENDMENT_KINDS)


def is_named_by_subject(kind: str | None) -> bool:
    """Whether a Document or Zaak of this ``Soort`` is named by its ``Onderwerp``: a motie,
    an amendement, a ``Brief regering`` or another letter, a ``Verslag van een
    commissiedebat`` …

    Its ``Titel`` is the title of its dossier, the same for every paper on it.
    """
    return (kind or "").lower().startswith(_OWN_SUBJECT_KINDS)


def own_subject(payload: Payload) -> str:
    """The ``Onderwerp`` of a Document or Zaak named by it (``is_named_by_subject``); empty
    for any other kind, and when the Onderwerp only repeats the kind (``Mededeling``)."""
    kind = payload.get("Soort") or ""
    if not is_named_by_subject(kind):
        return ""
    subject = _text(payload, "Onderwerp")
    return "" if subject.lower() == kind.lower() else subject


def may_amend(kind: str | None) -> bool:
    """Whether a Document of this ``Soort`` can amend a law: an amendement, the text of a
    bill (``Voorstel van wet``, ``Nota van wijziging``, ``Eindtekst`` …) or its memorandum.

    Every other paper on a bill's dossier carries the bill's title, a motie too, and
    changes nothing.
    """
    return (kind or "").lower().startswith(_AMENDING_KINDS)


def _distinct(values: Iterable[str]) -> list[str]:
    """Non-empty values, deduplicated, in first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


# ── Zaak (Case) references ───────────────────────────────────────────────────


def case_ids(cases: Iterable[Payload]) -> list[str]:
    """Zaak GUIDs of the given Zaak records."""
    return _distinct(str(record.get("Id") or "") for record in cases)


def dossier_label(number: Any, suffix: Any) -> str:
    """``37020-XV`` for Nummer 37020 with Toevoeging XV, ``37020`` without one.

    ``make_node_key`` of the label is the key of the dossier node.
    """
    number_str = str(number or "")
    return f"{number_str}-{suffix}" if number_str and suffix else number_str


def _dossier_label(dossier: Payload) -> str:
    return dossier_label(dossier.get("Nummer"), dossier.get("Toevoeging"))


def dossier_numbers(cases: Iterable[Payload]) -> list[str]:
    """Kamerstukdossier labels (``37020``, ``37020-XV``) of the given Zaak records."""
    return _distinct(
        _dossier_label(dossier)
        for record in cases
        for dossier in _dicts(record.get("Kamerstukdossier"))
    )


def case_kinds(cases: Iterable[Payload]) -> list[str]:
    """Distinct ``Zaak.Soort`` values (Wetgeving, Motie, Amendement, …)."""
    return _distinct(str(record.get("Soort") or "") for record in cases)


def case_kinds_by_dossier(cases: Iterable[Payload]) -> dict[str, list[str]]:
    """Distinct ``Zaak.Soort`` values (Wetgeving, Motie, …) per Kamerstukdossier label.

    Each dossier gets the kinds of its own cases only: one agenda (a day of votes) holds
    the cases of many dossiers.
    """
    pairs = [
        (_dossier_label(dossier), str(record.get("Soort") or ""))
        for record in cases
        for dossier in _dicts(record.get("Kamerstukdossier"))
    ]
    numbers = _distinct(number for number, _ in pairs)
    return {
        number: _distinct(kind for n, kind in pairs if n == number)
        for number in numbers
    }


def case(payload: Payload) -> Record | None:
    """Node key and props for a Zaak record; ``None`` without an id or when deleted.

    A motie, an amendement or a letter is named by its ``Onderwerp`` (``own_subject``): its
    ``Titel`` is the dossier's, the same for every motie on it.
    """
    external_id = first_str(
        [payload.get("Id"), payload.get("ZaakId"), payload.get("ZaakNummer")],
        skip_blank=True,
    )
    if external_id is None or is_deleted(payload):
        return None
    kind = payload.get("Soort") or None
    title = own_subject(payload) or _text(payload, "Titel", "ZaakTitel", "Onderwerp")
    props: dict[str, Any] = {
        "source": SOURCE_TK,
        "external_id": external_id,
        "number": str(payload.get("Nummer") or payload.get("ZaakNummer") or ""),
        "kind": kind,
        # The dossiers this case belongs to; the dossier pipeline turns them into PART_OF
        # edges once the dossier nodes exist.
        "dossier_numbers": dossier_numbers([payload]),
        # What `semantic tk-dossier-relations` lifts to RELATED_TO edges between dossiers.
        "related_cases": related_cases(payload),
    }
    if title:
        props["title"] = title
    if payload.get("Citeertitel"):
        props["citation_title"] = payload["Citeertitel"]
    props["display_name"] = title or f"Zaak {external_id}"
    return make_node_key(external_id), props


def related_cases(payload: Payload) -> list[dict[str, Any]]:
    """The cases the Kamer relates a Zaak to (``GerelateerdNaar``): id, kind and dossiers.

    Mostly a letter of the government and the motion it answers, or an amendment and its
    bill. The dossiers of the other case come with it, so the relation holds also when that
    case itself was not retrieved.
    """
    return [
        {
            "id": str(other["Id"]),
            "kind": str(other.get("Soort") or "") or None,
            "dossier_numbers": dossier_numbers([other]),
        }
        for other in _dicts(payload.get("GerelateerdNaar"))
        if other.get("Id") and not other.get("Verwijderd")
    ]


def agenda_cases(payload: Payload) -> list[Payload]:
    """The Zaak records on every Agendapunt of an Activiteit or Besluit."""
    return [
        record
        for item in _dicts(payload.get("Agendapunt"))
        for record in _dicts(item.get("Zaak"))
    ]


# ── Commissie (Committee) ────────────────────────────────────────────────────


def committee(payload: Payload) -> Record | None:
    """Node key and props for a Commissie record; ``None`` without an id or a name.

    The source has records with nothing but an id (the voortouw of every plenary
    activity is one). A record without a name is not written, so no id stands in for a
    name; once the source fills it in, the next run writes it.
    """
    external_id = _external_id(payload)
    name = _text(payload, "NaamNL", "Naam")
    if not external_id or not name:
        return None
    abbreviation = _text(payload, "Afkorting")
    return make_node_key(external_id), {
        "external_id": external_id,
        "name": name,
        "abbreviation": abbreviation,
        "slug": make_node_key(abbreviation or name),
        "kind": committee_kind(name, _text(payload, "Inhoudsopgave")),
        "started_on": iso_date(payload.get("DatumActief")),
        "ended_on": iso_date(payload.get("DatumInactief")),
        "display_name": name,
    }


# The kind of a committee, by its name, else by the group the Kamer lists it in
# (``Commissie.Inhoudsopgave``): an enquête or ondervraging before "Parlementaire".
_COMMITTEE_KINDS = (
    ("enquete", re.compile(r"(?:enqu[eê]te|ondervragings)commissie", re.IGNORECASE)),
    ("vast", re.compile(r"^vaste commissie\b", re.IGNORECASE)),
    ("algemeen", re.compile(r"^algemene commissie\b", re.IGNORECASE)),
    ("tijdelijk", re.compile(r"^(?:tijdelijke\b|themacommissie\b)", re.IGNORECASE)),
    (
        "delegatie",
        re.compile(
            r"^(?:contactgroep|ipc|interparlementaire)\b|assemblee|europol",
            re.IGNORECASE,
        ),
    ),
)
_COMMITTEE_GROUPS = {
    "Vaste commissies": "vast",
    "Algemene commissies": "algemeen",
    "Tijdelijke commissies": "tijdelijk",
    "Delegaties naar internationale vergaderingen": "delegatie",
}


def committee_kind(name: str, group: str | None) -> str:
    """``vast``, ``algemeen``, ``tijdelijk``, ``enquete``, ``delegatie`` or ``overig``."""
    for kind, pattern in _COMMITTEE_KINDS:
        if pattern.search(name):
            return kind
    return _COMMITTEE_GROUPS.get(group or "", "overig")


def unique_committee_slugs(committees: list[dict[str, Any]]) -> None:
    """Give every committee in *committees* (their props) a slug of its own.

    Several committees share an abbreviation (``ez``, ``buhaos``): the one sitting now, else
    the one that ended last, keeps it; the others get the year they started (``ez-2010``),
    with a number behind it when that is taken too.
    """
    by_slug: dict[str, list[dict[str, Any]]] = {}
    for props in committees:
        by_slug.setdefault(props["slug"], []).append(props)
    taken = set(by_slug)
    for slug, group in by_slug.items():
        group.sort(
            key=lambda p: (
                p.get("ended_on") is None,
                p.get("ended_on") or "",
                p.get("started_on") or "",
                p["external_id"],
            ),
            reverse=True,
        )
        for props in group[1:]:
            year = (props.get("started_on") or props.get("ended_on") or "")[:4]
            base = f"{slug}-{year}" if year else slug
            candidate, n = base, 1
            while candidate in taken:
                n += 1
                candidate = f"{base}-{n}"
            props["slug"] = candidate
            taken.add(candidate)


@dataclass(frozen=True)
class CommitteeSeat:
    """One period a person held a seat on a commissie: from, to (inclusive, None while
    open), the role as the Kamer writes it (``CommissieZetel…Persoon.Functie``: ``Lid``,
    ``Voorzitter``, ``OnderVz``, ``Plv. lid``) and whether it was a substitute's seat
    (``CommissieZetelVervangerPersoon``)."""

    from_date: str | None
    to_date: str | None
    role: str | None = None
    substitute: bool = False


def committee_seats(payload: Payload) -> dict[str, list[CommitteeSeat]]:
    """``Persoon_Id`` -> every seat they held on this commissie, a member's
    (``CommissieZetelVastPersoon``) and a substitute's (``CommissieZetelVervangerPersoon``),
    one level below the seat, where the dates and the role live."""
    seats: dict[str, list[CommitteeSeat]] = {}
    for seat in _dicts(payload.get("CommissieZetel")):
        for part, substitute in (
            ("CommissieZetelVastPersoon", False),
            ("CommissieZetelVervangerPersoon", True),
        ):
            for held in _dicts(seat.get(part)):
                person_id = str(held.get("Persoon_Id") or "")
                if person_id and not is_deleted(held):
                    seats.setdefault(person_id, []).append(
                        CommitteeSeat(
                            iso_date(held.get("Van")),
                            iso_date(held.get("TotEnMet")),
                            _text(held, "Functie") or None,
                            substitute,
                        )
                    )
    return seats


def _seat_meta(seat: CommitteeSeat) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if seat.from_date:
        meta["from_date"] = seat.from_date
    if seat.to_date:
        meta["to_date"] = seat.to_date
    if seat.role:
        meta["role"] = seat.role
    if seat.substitute:
        meta["substitute"] = True
    return meta


def representative_period(seats: list[CommitteeSeat]) -> dict[str, Any]:
    """Edge meta for the one seat that represents a membership, and every seat.

    An edge key is deterministic per (member, committee), so several seats collapse into
    one edge: an open-ended seat wins over a closed one, a member's over a substitute's,
    and among equals the latest one does. ``periods`` holds every seat, oldest first, when
    there is more than one or it has a role.
    """
    best = max(
        seats,
        key=lambda s: (
            s.to_date is None,
            not s.substitute,
            s.to_date or "",
            s.from_date or "",
        ),
    )
    meta = _seat_meta(best)
    if len(seats) > 1 or best.role:
        meta["periods"] = [
            _seat_meta(s)
            for s in sorted(seats, key=lambda s: (s.from_date or "", s.to_date or ""))
        ]
    return meta


# ── Persoon (Member) ─────────────────────────────────────────────────────────


def member(payload: Payload) -> Record | None:
    """Node key and props for a Persoon record; ``None`` when deleted.

    Party affiliation is not read here: it follows from the
    FractieZetelPersoon timeline, which is the one source that dates it.
    """
    external_id = _external_id(payload)
    if not external_id or is_deleted(payload):
        return None
    surname = f"{payload.get('Tussenvoegsel') or ''} {payload.get('Achternaam') or ''}"
    # a member of old the Kamer knows by initials alone: ``W.B. Buma`` (1807-1848)
    initials = _dotted_initials(_text(payload, "Initialen"))
    first = payload.get("Voornamen") or initials
    full_name = " ".join(f"{first} {surname}".split())
    # the name a person goes by: ``Ard van der Steur``, not ``Gerard Adriaan van der Steur``
    called = payload.get("Roepnaam") or first
    name = " ".join(f"{called} {surname}".split())
    props: dict[str, Any] = {
        "external_id": external_id,
        "full_name": full_name or None,
        # what another source knows a person by (``core.government.match_holder``)
        "family_name": _text(payload, "Achternaam") or None,
        "name_prefix": _text(payload, "Tussenvoegsel") or None,
        "initials": _text(payload, "Initialen") or None,
        "birth_date": iso_date(payload.get("Geboortedatum")),
        # Persoon.Nummer: what a namesake's slug ends in when the year does not tell
        "number": str(payload["Nummer"]) if payload.get("Nummer") else None,
    }
    if name:
        # a Persoon the Kamer gives no name (a record it withholds) keeps the name its
        # roll-call votes and signatures gave (``_tk_members.name_nameless_members``)
        props["name"] = props["display_name"] = name
    return make_node_key(external_id), props


def _dotted_initials(initials: str) -> str:
    """``W.B.`` of ``WB``: the Kamer writes the initials of members of old without dots."""
    if not initials or "." in initials:
        return initials
    return "".join(f"{letter}." for letter in initials if letter.isalpha())


def seat_holding(payload: Payload) -> tuple[str, str, dict[str, Any]] | None:
    """``(Persoon_Id, Fractie_Id, period)`` for a FractieZetelPersoon record; ``None`` when
    deleted."""
    if is_deleted(payload):
        return None
    person_id = str(payload.get("Persoon_Id") or "")
    seat = next(_dicts(payload.get("FractieZetel")), {})
    faction_id = str(seat.get("Fractie_Id") or "")
    if not person_id or not faction_id:
        return None
    return (
        person_id,
        faction_id,
        {
            "from_date": iso_date(payload.get("Van")),
            "to_date": iso_date(payload.get("TotEnMet")),
            "role": payload.get("Functie") or None,
        },
    )


def seat_changed_on(payload: Payload) -> str | None:
    """The day the FractieZetel of a FractieZetelPersoon record last changed (its
    ``GewijzigdOp``): when a seat goes to another faction, the seating of the plenary hall
    may change with it."""
    seat = next(_dicts(payload.get("FractieZetel")), {})
    return iso_date(seat.get("GewijzigdOp"))


# ── Fractie (Faction) ────────────────────────────────────────────────────────


def faction_label(payload: Payload) -> str:
    """The name a Fractie is keyed by: its abbreviation, else its full name."""
    return _text(payload, "Afkorting") or _text(payload, "NaamNL")


def faction_aliases(payload: Payload, vote_labels: Iterable[str]) -> list[str]:
    """Every spelling of this fractie that other TK endpoints use.

    ``Fractie.Afkorting`` is sometimes the full party name while
    ``Stemming.ActorFractie`` uses the short form, so the alias set is what
    joins the two. An auto-acronym is accepted only when a vote actually uses
    it; unvalidated guesses would merge distinct parties.
    """
    abbreviation = _text(payload, "Afkorting")
    name = _text(payload, "NaamNL")
    label = abbreviation or name
    labels = set(vote_labels)
    aliases = {value for value in (abbreviation, name) if value}
    acronym = "".join(w[0] for w in name.split() if w and w[0].isalpha()).upper()
    if len(acronym) >= 2 and acronym in labels:
        aliases.add(acronym)
    aliases.update(
        spelling
        for spelling in labels
        if make_node_key(spelling) == make_node_key(label)
    )
    return sorted(aliases)


def faction(
    payload: Payload, aliases: list[str], records: list[Payload] | None = None
) -> Record | None:
    """Node key and props for a faction: *payload* is its current Fractie record,
    *records* every record of it (the Kamer gives a faction that returns a new record, and
    still names the old one: 50PLUS 2012-2021 and again from 2025). The faction is active
    from the first record's start until the last one ends, and knows every record's id.
    ``None`` when *payload* is deleted; a deleted one among *records* is passed over."""
    external_id = _external_id(payload)
    label = faction_label(payload)
    if not external_id or not label or is_deleted(payload):
        return None
    records = [r for r in records or [payload] if not is_deleted(r)]
    abbreviation = _text(payload, "Afkorting")
    name = _text(payload, "NaamNL")
    starts = [d for d in (iso_date(r.get("DatumActief")) for r in records) if d]
    ends = [iso_date(r.get("DatumInactief")) for r in records]
    active = any(end is None for end in ends)
    return make_node_key(label), {
        "external_id": external_id,
        "external_ids": sorted({_external_id(r) for r in records} - {""}),
        "name": name or abbreviation,
        "abbreviation": abbreviation or None,
        "aliases": aliases,
        "active_from": min(starts) if starts else None,
        "active_until": None if active else max(e for e in ends if e),
        # the Kamer keeps the seats a faction had on its record after it ended
        "seats": payload.get("AantalZetels") if active else 0,
        "active": active,
        "display_name": abbreviation or name,
    }


def faction_is_current(payload: Payload) -> tuple[int, str]:
    """Sort key that prefers a seated Fractie, then the most recently changed.

    TK recycles afkortingen — a party that dissolves and reforms gets a fresh
    record with the same one — and both records key to the same node.
    """
    return (
        1 if payload.get("DatumInactief") is None else 0,
        str(payload.get("GewijzigdOp") or ""),
    )


# ── Kamerstukdossier (Dossier) ───────────────────────────────────────────────


def dossier(payload: Payload) -> tuple[str, str, dict[str, Any]] | None:
    """``(node key, dossier number label, props)`` for a Kamerstukdossier; ``None`` when
    deleted."""
    external_id = _external_id(payload)
    number = payload.get("Nummer")
    if not external_id or number is None or is_deleted(payload):
        return None

    number_str = str(number)
    suffix = payload.get("Toevoeging") or ""
    label = dossier_label(number_str, suffix)
    # A dossier with neither Titel nor Citeertitel keeps title None, so the
    # backfill can take one from a voorstel-van-wet document instead of
    # storing a title that only looks valid.
    title = payload.get("Titel") or payload.get("Citeertitel") or None

    # The record says nothing about how far the dossier got: ``Afgesloten`` is false on
    # every dossier, also on those whose law was published years ago. When it was opened
    # and whether and how it ended are derived from the graph (the stage backfill and
    # ``semantic tk-dossier-outcomes``), so they are not written here, where a run would
    # blank them.
    props: dict[str, Any] = {
        "external_id": external_id,
        "number": number_str,
        "suffix": suffix,
        "label": label,
        "order": dossier_order(number_str, suffix),
        "title": title,
        "title_source": "dossier" if title else None,
        "display_name": dossier_display_name(number_str, suffix, title or ""),
    }

    return make_node_key(label), label, props


# ── Activiteit (Activity) ────────────────────────────────────────────────────


def activity(payload: Payload) -> Record | None:
    """Node key and props for an Activiteit record."""
    external_id = _external_id(payload)
    if not external_id:
        return None

    cases = agenda_cases(payload)
    date = iso_date(payload.get("Datum"))
    description = _text(payload, "Onderwerp")
    kind = payload.get("Soort") or ""
    voortouw = payload.get("Voortouwcommissie_Id")
    # A plenary activity has the Kamer itself as voortouw, not a committee.
    plenary = payload.get("Voortouwafkorting") == PLENARY_VOORTOUW

    return make_node_key(external_id), {
        "external_id": external_id,
        "date": date,
        "agenda_title": description,
        "kind": kind,
        "status": _text(payload, "Status") or None,
        "committee_id": str(voortouw) if voortouw and not plenary else None,
        "case_ids": case_ids(cases),
        "dossier_numbers": dossier_numbers(cases),
        "case_kinds_by_dossier": case_kinds_by_dossier(cases),
        "display_name": activity_display_name(date, description or kind),
        "number": str(payload.get("Nummer") or ""),
        # the activities a moved one was replaced by (Activiteit.VervangenDoor): a moved
        # activity keeps no agenda, the one that replaced it has it
        "replaced_by": [
            str(other["Nummer"])
            for other in _dicts(payload.get("VervangenDoor"))
            if other.get("Nummer")
        ],
    }


# ── Toezegging (Commitment) ──────────────────────────────────────────────────


def commitment(payload: Payload) -> Record | None:
    """Node key and props for a Toezegging record."""
    external_id = _external_id(payload)
    if not external_id:
        return None

    text = _text(payload, *_COMMITMENT_TEXT_FIELDS)
    raw_status = _text(payload, "Status") or None
    return make_node_key(external_id), {
        "external_id": external_id,
        "text": text,
        "minister_name": _text(payload, "Naam", "MinisterNaam"),
        "minister_role": _text(payload, "Functie", "MinisterTitel"),
        # the ministry the Tweede Kamer gives the commitment (``Justitie en Veiligheid``)
        "ministry_name": _text(payload, "Ministerie") or None,
        "made_on": iso_date(payload.get("Aanmaakdatum")),
        "expected_resolution": iso_date(payload.get("DatumNakoming")),
        "status": raw_status,
        "activity_number": str(payload.get("ActiviteitNummer") or ""),
        "number": _text(payload, "Nummer") or None,
        "display_name": shorten(text, 80),
    }


# ── Document (Kamerstuk) ─────────────────────────────────────────────────────


# The capacity a document is signed in (see ``signing_capacity``).
CAPACITY_MEMBER = "kamerlid"
CAPACITY_GOVERNMENT = "bewindspersoon"
CAPACITY_OTHER = "overig"

# What a Toezegging holds as ``DatumNakoming`` when the Kamer names no date it is due.
NO_DUE_DATE = "0001-01-01"

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
    for actor in _dicts(payload.get("DocumentActor")):
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


def document_title(payload: Payload, cases: list[Payload]) -> str:
    """The title of a Document: its ``Titel``, but the own subject of a paper named by it.

    The ``Titel`` of a motie, an amendement or a letter is its dossier's; what names it is
    its ``Onderwerp`` (``own_subject``), else the ``Onderwerp`` of its Zaak.
    """
    kind = payload.get("Soort") or ""
    if is_named_by_subject(kind):
        own = own_subject(payload) or next(
            (subject for c in cases if (subject := own_subject(c))), ""
        )
        if own:
            return own
    return _text(payload, "Titel", "Onderwerp") or kind


def own_dossier(payload: Payload) -> tuple[str, str | None] | None:
    """``(Nummer, Toevoeging)`` of the Kamerstukdossier a Document is numbered in; ``None``
    for a paper that is no Kamerstuk (a nader rapport sent along with a bill).

    A Document is a Kamerstuk of at most one dossier. Its cases may reach several: the
    report of one consultation on five bills is part of all five and nr. 11 of one.
    """
    dossier = next(_dicts(payload.get("Kamerstukdossier")), None)
    if dossier is None or not dossier.get("Nummer"):
        return None
    return str(dossier["Nummer"]), dossier.get("Toevoeging") or None


def document(payload: Payload) -> Record | None:
    """Node key and props for a Document (Kamerstuk) record; ``None`` when deleted.

    A Document reaches dossiers through Zaak → Kamerstukdossier, and one document may
    reach several; its number (``sequence``) is that in its own dossier
    (``dossier_number``, ``dossier_suffix``).
    """
    external_id = _external_id(payload)
    if not external_id or is_deleted(payload):
        return None

    cases = list(_dicts(payload.get("Zaak")))
    own = own_dossier(payload)
    own_label = dossier_label(*own) if own else None
    dossiers = _distinct([*dossier_numbers(cases), own_label or ""])
    kind = payload.get("Soort") or ""
    title = document_title(payload, cases)
    sequence = payload.get("Volgnummer")  # -1 marks a non-Kamerstuk

    return make_node_key(external_id), {
        "source": SOURCE_TK,
        "external_id": external_id,
        "raw": payload,
        "dossier_numbers": dossiers,
        "dossier_number": own[0] if own else None,
        "dossier_suffix": own[1] if own else None,
        "case_ids": case_ids(cases),
        "case_kinds": case_kinds(cases),
        "sequence": sequence if (sequence or 0) > 0 else None,
        "kind": kind,
        "title": title,
        # The Titel of a paper named by its own subject: the title of its dossier, which
        # says which law an amendement changes (``semantic tk-amends``).
        "dossier_title": (
            _text(payload, "Titel") or None if is_named_by_subject(kind) else None
        ),
        "subject": payload.get("Onderwerp") or "",
        "date": iso_date(payload.get("Datum") or payload.get("DatumRegistratie")),
        "session_year": payload.get("Vergaderjaar") or "",
        # What tweedekamer.nl finds the document by (``2026D44984``); see ``core.tk_links``.
        "document_number": payload.get("DocumentNummer") or None,
        "display_name": document_display_name(own_label, sequence, kind, title),
        "actors": document_actors(payload),
    }


def activity_display_name(date: str | None, subject: str | None) -> str:
    """``Digitale grondrechten en data-ethiek (2027-02-11)``: the subject, then the day."""
    subject = subject or "Activiteit"
    return f"{subject} ({date})" if date else subject


def _starts_with_kind(title: str, kind: str) -> bool:
    """Whether *title* names its own kind ("Motie van de leden …" for a Motie)."""
    return bool(kind) and title.lower().startswith(kind.split(" (")[0].lower())


def document_display_name(
    dossier_number: str | None,
    sequence: Any,
    kind: str,
    title: str,
) -> str:
    """``Kamerstuk 29684, nr. 7. Amendement: <title>``, or ``Kamerstuk 29684, nr. 7: Motie
    van de leden …`` when the title names its kind. No dash: it is a heading."""
    if dossier_number and (sequence or 0) > 0:
        name = f"Kamerstuk {dossier_number}, nr. {sequence}"
    elif dossier_number:
        name = f"Kamerstuk {dossier_number}"
    else:
        name = ""
    if not title or title == kind:
        return f"{name}. {kind}" if name and kind else name or kind or "Document"
    title = shorten(title, 120)
    if _starts_with_kind(title, kind) or not kind:
        return f"{name}: {title}" if name else title
    return f"{name}. {kind}: {title}" if name else f"{kind}: {title}"


# ── Stemming / Besluit (Decision and its votes) ──────────────────────────────


@dataclass(frozen=True, slots=True)
class VoteCast:
    """One Stemming row: who voted on which Besluit, how, and with what weight.

    ``person_id`` is set on a roll-call vote and absent otherwise, which is
    what decides whether the VOTED edge starts at a member or at a faction.

    Every cast of a run is kept until the VOTED edges are written (190K for two years), so
    this is a slotted object with its repeating strings interned, not a dict: about a
    fifth of the memory.
    """

    decision_id: str
    choice: str
    seats: int
    person_id: str | None
    faction_id: str | None
    faction_label: str
    changed_at: str | None
    actor_name: str | None = None  # "Nobel, J.N.J.": who voted, as the row names them
    record_id: str | None = None  # the Stemming ``Id``, which its VOTED edge keeps


def decision_key(decision_id: str) -> str:
    """The node key of the decision on the Besluit *decision_id* (see ``decision``)."""
    return make_node_key("decision", decision_id)


def vote(payload: Payload) -> VoteCast | None:
    decision_id = str(payload.get("Besluit_Id") or "")
    if not decision_id:
        return None
    faction_id = str(payload.get("Fractie_Id") or "")
    person_id = str(payload.get("Persoon_Id") or "") or None
    return VoteCast(
        decision_id=sys.intern(decision_id),
        choice=sys.intern(str(payload.get("Soort") or "")),
        # a row of a roll-call is one member, whose FractieGrootte is that of the faction
        seats=1 if person_id else payload.get("FractieGrootte") or 0,
        person_id=person_id,
        faction_id=sys.intern(faction_id) if faction_id else None,
        faction_label=sys.intern((payload.get("ActorFractie") or "").strip()),
        changed_at=payload.get("GewijzigdOp"),
        actor_name=(payload.get("ActorNaam") or "").strip() or None
        if person_id
        else None,
        record_id=str(payload.get("Id") or "") or None,
    )


def decision(decision_id: str, decision: Payload, votes: list[VoteCast]) -> Record:
    """Node key and props for one Besluit and the votes cast on it.

    The tally is stored so a list row costs no edge traversal; who voted how
    is on the VOTED edges.
    """
    own = list(_dicts(decision.get("Zaak")))
    cases = own + agenda_cases(decision)
    agenda_item = next(_dicts(decision.get("Agendapunt")), {})
    activity = next(_dicts(agenda_item.get("Activiteit")), {})
    decision_text = decision.get("BesluitTekst") or ""

    # The Besluit's own Zaak is the case it decided: what tells the vote on a bill from
    # the votes on its amendments, and eighteen moties on one Agendapunt apart. Without
    # it only an Agendapunt of one case says which. AgendapuntZaakBesluitVolgorde is the
    # place of the Besluit on the Agendapunt, not of its Zaak in the list.
    order = _int_or_none(decision.get("AgendapuntZaakBesluitVolgorde"))
    listed = agenda_cases(decision)
    primary = own[0] if own else (listed[0] if len(listed) == 1 else None)

    # Prefer the per-motie subject over the agenda-item headline it shares with
    # its siblings. Zaak.Titel is deliberately not used: on a motie it carries
    # the parent dossier's umbrella title.
    subject = (
        (primary or {}).get("Onderwerp")
        or agenda_item.get("Onderwerp")
        or decision_text
        or f"Besluit {decision_id[:8]}"
    )

    # The rows of a decision come in no fixed order: in that of their ids, the first vote
    # (whose date stands in for a missing one) is the same on every run.
    votes = sorted(votes, key=lambda cast: (cast.record_id or "", cast.person_id or ""))
    tally: dict[str, int] = {}
    voters: dict[str, int] = {}
    for cast in votes:
        choice = cast.choice
        tally[choice] = tally.get(choice, 0) + int(cast.seats or 0)
        voters[choice] = voters.get(choice, 0) + 1

    roll_call = any(cast.person_id for cast in votes)
    if roll_call:
        # In a roll-call each row is one member, so FractieGrootte would count
        # the whole faction for every one of them.
        tally = dict(voters)

    tally, voters = _in_vote_order(tally), _in_vote_order(voters)
    return make_node_key("decision", decision_id), {
        "decision_id": decision_id,
        "agenda_item_id": str(decision.get("Agendapunt_Id") or ""),
        # The day of the vote; a row's GewijzigdOp is when it was last edited.
        "date": iso_date(activity.get("Datum"))
        or (iso_date(votes[0].changed_at) if votes else None),
        "subject": subject,
        "agenda_item_subject": agenda_item.get("Onderwerp") or "",
        "decision_text": decision_text,
        "decision_kind": decision.get("BesluitSoort") or None,
        "decision_order": order,
        "meeting_kind": agenda_item.get("Vergadering_Soort") or "",
        "case_ids": case_ids(cases),
        "primary_case_id": str(primary.get("Id") or "") if primary else None,
        "primary_case_kind": (primary.get("Soort") or None) if primary else None,
        "kind": decision_kind(primary, listed),
        "dossier_numbers": dossier_numbers(cases),
        "vote_kind": (VOTE_KIND_MEMBER if roll_call else VOTE_KIND_FACTION)
        if votes
        else None,
        "tally": tally,
        "voters": voters,
        "passed": decision_passed(decision, tally),
        "display_name": decision_display_name(primary, order, len(listed), subject),
    }


def _in_vote_order(counts: dict[str, int]) -> dict[str, int]:
    """*counts* per choice as a tally is read: for, against, then the others in alphabetical
    order (``Niet deelgenomen``)."""
    order = {VOTE_FOR: 0, VOTE_AGAINST: 1}
    return dict(
        sorted(counts.items(), key=lambda item: (order.get(item[0], 2), item[0]))
    )


def decision_kind(primary: Payload | None, listed: list[Payload]) -> str | None:
    """What was decided on: the ``Zaak.Soort`` of the case decided (``Motie``,
    ``Amendement``, ``Wetgeving``, ...), as the Kamer writes it.

    Without a primary case, the cases on the Agendapunt answer when they are all of one
    Soort: an Agendapunt of moties alone decides a motie, whichever it is. None otherwise.
    """
    cases = [primary] if primary else listed
    kinds = {case.get("Soort") or None for case in cases}
    return kinds.pop() if len(kinds) == 1 else None


def decision_passed(decision: Payload, tally: dict[str, int]) -> bool | None:
    """Whether the decision carried: the source says so (``Stemmen - aangenomen``,
    ``Stemmen - zonder stemming aannemen``, ``Stemmen - verworpen``), or the tally of its
    votes does; None for a decision that is no vote (``Stemmen - uitstellen``)."""
    kind = (
        decision.get("BesluitSoort") or decision.get("StemmingsSoort") or ""
    ).lower()
    if "aangenomen" in kind or "aannemen" in kind:
        return True
    if "verworpen" in kind:
        return False
    if not tally:
        return None
    return tally.get(VOTE_FOR, 0) > tally.get(VOTE_AGAINST, 0)


def decision_display_name(
    primary: Payload | None,
    order: int | None,
    case_count: int,
    subject: str,
) -> str:
    """``Motie 2024Z17945: <subject>``, or the subject alone when it names its kind
    ("Motie van de leden …"); distinct per sibling on an Agendapunt. No dash: it is a
    heading.

    The outcome is left out: the frontend renders it as a badge.
    """
    kind = str((primary or {}).get("Soort") or "")
    if subject and _starts_with_kind(subject, kind):
        return subject
    if primary and primary.get("Nummer"):
        head = f"{kind or 'Stemming'} {primary['Nummer']}"
    elif order is not None and case_count:
        head = f"Stemming {order}/{case_count}"
    else:
        head = "Stemming"
    return f"{head}: {subject}" if subject else head


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def display_person_name(actor_name: str | None) -> str | None:
    """ "J.N.J. Nobel" of "Nobel, J.N.J.", as a Stemming or a DocumentActor names a person."""
    if not actor_name:
        return None
    family, _, initials = actor_name.partition(",")
    return " ".join(f"{initials.strip()} {family.strip()}".split()) or None
