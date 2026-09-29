"""The kinds of event in the news feed (``GET /api/feed``) and what each is read from.

An event is one node of the graph with a date: a commitment made, a paper submitted, a vote,
a publication, a new version of a law in force. The kinds keep the Dutch word the Kamer
uses, as the dossier tracks and stages do.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Final

from lawgraph.core.tk_records import CAPACITY_GOVERNMENT, CAPACITY_MEMBER

EVENT_COMMITMENT: Final = "toezegging"
EVENT_BILL: Final = "wetsvoorstel"
EVENT_AMENDMENT_NOTE: Final = "nota_van_wijziging"
EVENT_AMENDMENT: Final = "amendement"
EVENT_MOTION: Final = "motie"
EVENT_VOTE: Final = "stemming"
EVENT_PUBLICATION: Final = "publicatie"
EVENT_COMMENCEMENT: Final = "inwerkingtreding"
EVENT_GOVERNMENT_LETTER: Final = "brief_regering"

# The kinds, in the order the facets and the documentation list them.
FEED_KINDS: Final = (
    EVENT_COMMITMENT,
    EVENT_BILL,
    EVENT_AMENDMENT_NOTE,
    EVENT_AMENDMENT,
    EVENT_MOTION,
    EVENT_VOTE,
    EVENT_PUBLICATION,
    EVENT_COMMENCEMENT,
    EVENT_GOVERNMENT_LETTER,
)

# The order of the kinds within one day: what changes the law first, what is said about it
# last. A kind's rank is its place here.
DAY_ORDER: Final = (
    EVENT_BILL,
    EVENT_VOTE,
    EVENT_COMMITMENT,
    EVENT_COMMENCEMENT,
    EVENT_PUBLICATION,
    EVENT_AMENDMENT_NOTE,
    EVENT_AMENDMENT,
    EVENT_MOTION,
    EVENT_GOVERNMENT_LETTER,
)
KIND_RANK: Final[dict[str, int]] = {kind: rank for rank, kind in enumerate(DAY_ORDER)}

# The kinds whose signatories are its submitters, a bewindspersoon too: a bill and a note
# of change are brought in by who signs them.
SUBMITTED_KINDS: Final = (EVENT_BILL, EVENT_AMENDMENT_NOTE)

# The kinds that are a Tweede Kamer document, and the document ``kind`` values (the
# ``Document.Soort`` of the source) each is read from.
DOCUMENT_KINDS: Final[dict[str, tuple[str, ...]]] = {
    EVENT_BILL: ("Voorstel van wet", "Voorstel van wet (initiatiefvoorstel)"),
    EVENT_AMENDMENT_NOTE: (
        "Nota van wijziging",
        "Nota van wijziging (initiatiefvoorstel)",
    ),
    EVENT_AMENDMENT: ("Amendement", "Amendement (gewijzigd/nader/vervangend)"),
    EVENT_MOTION: ("Motie", "Motie (gewijzigd/nader)"),
    EVENT_GOVERNMENT_LETTER: ("Brief regering",),
}

# What a person was to an event: the first signatory submitted it, the others signed with
# them; a bewindspersoon signed for the government (or made the commitment).
ROLE_SUBMITTER: Final = "indiener"
ROLE_CO_SUBMITTER: Final = "medeindiener"
ROLE_GOVERNMENT: Final = "bewindspersoon"
PERSON_ROLES: Final = (ROLE_SUBMITTER, ROLE_CO_SUBMITTER, ROLE_GOVERNMENT)

# The ``kind`` of a memorie van toelichting (also ``… (initiatiefvoorstel)``): a bill's
# signatories sign it where they leave the voorstel unsigned.
EXPLANATORY_MEMORANDUM: Final = "Memorie van toelichting"

# ``DocumentActor.Relatie`` of the first signatory.
FIRST_SIGNATORY: Final = "Eerste ondertekenaar"


def person_role(
    role: str | None, capacity: str | None, kind: str | None = None
) -> str | None:
    """The role in the feed of a signature of an event of *kind*: its ``role`` (``Eerste
    ondertekenaar``) and ``capacity``; None for one that is neither a Kamerlid nor a
    bewindspersoon (the griffier, the Raad van State). Who signs a bill or a note of change
    submits it (``SUBMITTED_KINDS``), a bewindspersoon as well as a Kamerlid."""
    if capacity not in (CAPACITY_GOVERNMENT, CAPACITY_MEMBER):
        return None
    if capacity == CAPACITY_GOVERNMENT and kind not in SUBMITTED_KINDS:
        return ROLE_GOVERNMENT
    return ROLE_SUBMITTER if role == FIRST_SIGNATORY else ROLE_CO_SUBMITTER


@dataclass(frozen=True)
class FeedCursor:
    """Where a page of the feed ends: the date, kind and id (``collection/key``) of its last
    event. The feed is ordered by date, newest first, then by the rank of the kind in
    ``DAY_ORDER``, then by id, so the next page holds the events after this one and every
    event is on one page only."""

    date: str
    kind: str
    id: str

    @property
    def rank(self) -> int:
        return KIND_RANK[self.kind]

    def encode(self) -> str:
        """The cursor as the opaque token the API hands out."""
        raw = json.dumps([self.date, self.kind, self.id], separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str) -> FeedCursor:
        """The cursor of a token; ValueError for one this API did not hand out."""
        try:
            padded = token + "=" * (-len(token) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded.encode()))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"not a feed cursor: {token!r}") from exc
        if (
            not isinstance(value, list)
            or len(value) != 3
            or not all(isinstance(part, str) and part for part in value)
            or value[1] not in KIND_RANK
        ):
            raise ValueError(f"not a feed cursor: {token!r}")
        return cls(date=value[0], kind=value[1], id=value[2])
