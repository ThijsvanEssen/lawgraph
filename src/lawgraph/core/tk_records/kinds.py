"""The kinds of paper (``Document.Soort``, ``Zaak.Soort``) told apart, and what each kind is
named by."""

from __future__ import annotations

from typing import Final

from lawgraph.core.tk_records._payload import (
    Payload,
    first_text,
)

# Document.Soort (and Zaak.Soort) of the papers told apart, as the Kamer writes them. A
# changed paper adds to it: ``Motie (gewijzigd/nader)`` is a motion (``is_motion``).
KIND_MOTION: Final = "Motie"
KIND_AMENDMENT: Final = "Amendement"
KIND_BILL: Final = "Voorstel van wet"
KIND_AMENDMENT_NOTE: Final = "Nota van wijziging"
KIND_EXPLANATORY_MEMORANDUM: Final = "Memorie van toelichting"
KIND_GOVERNMENT_LETTER: Final = "Brief regering"
# The papers the Kamer decides on by a vote of their own.
DECIDED_KINDS: Final = (KIND_MOTION, KIND_AMENDMENT)

# The Soort prefixes of a motie or amendement (see ``is_motion_or_amendment``).
_MOTION_OR_AMENDMENT_KINDS = tuple(kind.lower() for kind in DECIDED_KINDS)

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
    KIND_AMENDMENT.lower(),
    KIND_BILL.lower(),
    KIND_EXPLANATORY_MEMORANDUM.lower(),
    KIND_AMENDMENT_NOTE.lower(),
    "nota van verbetering",
    "wijzigingen voorgesteld door de regering",
    "oorspronkelijke tekst",
    "bijgewerkte tekst",
    "eindtekst",
)


def is_motion(kind: str | None) -> bool:
    """A ``Soort`` of a motion, also a changed one (``Motie (gewijzigd/nader)``)."""
    return (kind or "").startswith(KIND_MOTION)


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
    subject = first_text(payload, "Onderwerp")
    return "" if subject.lower() == kind.lower() else subject


def may_amend(kind: str | None) -> bool:
    """Whether a Document of this ``Soort`` can amend a law: an amendement, the text of a
    bill (``Voorstel van wet``, ``Nota van wijziging``, ``Eindtekst`` …) or its memorandum.

    Every other paper on a bill's dossier carries the bill's title, a motie too, and
    changes nothing.
    """
    return (kind or "").lower().startswith(_AMENDING_KINDS)


def starts_with_kind(title: str, kind: str) -> bool:
    """Whether *title* names its own kind ("Motie van de leden …" for a Motie)."""
    return bool(kind) and title.lower().startswith(kind.split(" (")[0].lower())
