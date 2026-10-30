"""A Kamerstuk of the Tweede Kamer as the KOOP SRU lists it: its own title and its kind.

The SRU names a paper by the short title of its dossier and its own, ``; `` between them
(``Wet op de inlichtingen- en veiligheidsdiensten 19..; Memorie van toelichting``); a dossier
with a subtitle has three parts or more (``Ziekenfondswet …; wijz. verlening …; Amendement
over …``). It gives no kind (``Document.Soort``): that is read from the start of its own
title, in the words of the Tweede Kamer, so the readers of a kind (an explanatory memorandum,
an amendment, a motion) find these papers as they find those of its API.
"""

from __future__ import annotations

import re

from lawgraph.core.tk_records.kinds import (
    KIND_ADVICE,
    KIND_AMENDMENT,
    KIND_AMENDMENT_NOTE,
    KIND_BILL,
    KIND_EXPLANATORY_MEMORANDUM,
    KIND_GOVERNMENT_LETTER,
    KIND_MOTION,
)

# The start of an own title (lower case, up to a word boundary) and the kind it names, the
# longer starts first. ``Brief minister`` and ``Brief staatssecretaris`` are letters of the
# government; a letter of a committee or member is named so (``Brief van de vaste commissie``).
_KINDS: tuple[tuple[str, str], ...] = (
    ("gewijzigde memorie van toelichting", KIND_EXPLANATORY_MEMORANDUM),
    ("memorie van toelichting", KIND_EXPLANATORY_MEMORANDUM),
    ("nader gewijzigd voorstel van wet", KIND_BILL),
    ("gewijzigd voorstel van wet", KIND_BILL),
    ("voorstel van wet", KIND_BILL),
    ("nota van verbetering", "Nota van verbetering"),
    ("nota n.a.v.", "Nota n.a.v. het (nader/tweede nader/enz.) verslag"),
    ("nota naar aanleiding", "Nota n.a.v. het (nader/tweede nader/enz.) verslag"),
    ("gewijzigde motie", "Motie (gewijzigd/nader)"),
    ("motie", KIND_MOTION),
    ("gewijzigd amendement", "Amendement (gewijzigd/nader/vervangend)"),
    ("amendement", KIND_AMENDMENT),
    ("advies", KIND_ADVICE),
    ("nader rapport", "Nader rapport"),
    ("brief minister", KIND_GOVERNMENT_LETTER),
    ("brief staatssecretaris", KIND_GOVERNMENT_LETTER),
    ("brief regering", KIND_GOVERNMENT_LETTER),
    ("verslag algemeen overleg", "Verslag van een algemeen overleg"),
    ("verslag schriftelijk overleg", "Verslag van een schriftelijk overleg"),
    ("verslag wetgevingsoverleg", "Verslag van een wetgevingsoverleg"),
    (
        "verslag houdende een lijst van vragen en antwoorden",
        "Verslag houdende een lijst van vragen en antwoorden",
    ),
    ("lijst van vragen en antwoorden", "Lijst van vragen en antwoorden"),
    ("nader verslag", "Verslag"),
    ("verslag", "Verslag"),
    ("oorspronkelijke tekst", "Oorspronkelijke tekst"),
    ("bijlagen", "Bijlage"),
    ("bijlage", "Bijlage"),
    ("rapport", "Rapport"),
    ("geleidende brief", "Geleidende brief"),
    ("brief", "Brief"),
)
_NOTE_OF_CHANGE = re.compile(r"^(?:\w+ )?nota van wijziging\b", re.IGNORECASE)


def kind_of(own_title: str) -> str | None:
    """The kind an own title starts with (``Tweede nota van wijziging``: ``Nota van
    wijziging``); None when it names none."""
    if _NOTE_OF_CHANGE.match(own_title):
        return KIND_AMENDMENT_NOTE
    lower = own_title.lower()
    for start, kind in _KINDS:
        if lower.startswith(start) and lower[len(start) : len(start) + 1] in ("", " "):
            return kind
    return None


def kind_and_title(title: str) -> tuple[str, str]:
    """``(kind, own title)`` of an SRU title: the own title begins at the first part past the
    dossier's that names a kind, else it is all past the first part; the kind is empty when
    no part names one."""
    parts = title.split("; ")
    for i, part in enumerate(parts[1:], start=1):
        kind = kind_of(part)
        if kind:
            return kind, "; ".join(parts[i:])
    return "", "; ".join(parts[1:]) or title
