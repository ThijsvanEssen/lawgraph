"""The kind of a motion that judges the government: a motion of censure (``censure``, motie van
afkeuring) or of no confidence (``no_confidence``, motie van wantrouwen), read from its subject
(pure functions, no I/O).

The Tweede Kamer gives a motion an ``Onderwerp`` of one form: "Motie van het lid X over …"
(``Zaak.Onderwerp`` and ``Document.Onderwerp`` in the OData of gegevensmagazijn.tweedekamer.nl;
older ones "Motie-X over …", "Motie X c.s. over …"). What follows the first `` over `` says
what the motion does, and of these two kinds the Kamer words it in a fixed way (counted over
every ``Zaak`` of ``Soort`` ``Motie`` from 2008 to October 2026):

* censure: "afkeuring uitspreken over …" (Kamerstuk 37020-XVI, nr. 60), "het uitspreken van
  afkeuring over …", and before 2020 "afkeuring van de handelwijze van …" or "afkeuring inzake
  …" (20 motions);
* no confidence: "het opzeggen van het vertrouwen in …", "het vertrouwen (in X) opzeggen (in
  …)", "uitspreken dat het vertrouwen in X wordt opgezegd" (136 motions).

A subject that only names the word ("vóór afkeuring van een schip", "afkeuring over de
arrestatie … actief uitdragen", "het vertrouwen in het bevolkingsonderzoek herstellen") is
neither. The form says what the motion does, not whom it judges: a motion that disapproves of
another than the government (the board of KLM) is a censure too.
"""

from __future__ import annotations

import re
from typing import Final, Literal, get_args

from lawgraph.core.xml import collapse_ws

MotionKind = Literal["censure", "no_confidence"]
MOTION_KINDS: Final[tuple[MotionKind, ...]] = get_args(MotionKind)
CENSURE: Final[MotionKind] = "censure"
NO_CONFIDENCE: Final[MotionKind] = "no_confidence"

# What the motion does, as the part of its subject after the first " over " opens.
_OPENINGS: Final[dict[MotionKind, re.Pattern[str]]] = {
    CENSURE: re.compile(
        r"(?:het uitspreken van afkeuring|afkeuring uitspreken|afkeuring (?:van|inzake))\b"
    ),
    NO_CONFIDENCE: re.compile(
        r"(?:uitspreken dat )?(?:het )?"
        r"(?:opzeggen van het vertrouwen|vertrouwen\b[^,]*?\b(?:opzeggen|opgezegd))\b"
    ),
}


def motion_kind(subject: str | None) -> MotionKind | None:
    """The kind of the motion with this *subject* (its ``Onderwerp``, any case and spacing);
    None for any other motion."""
    _, over, does = collapse_ws(subject or "").lower().partition(" over ")
    if not over:
        return None
    return next(
        (kind for kind, opening in _OPENINGS.items() if opening.match(does)), None
    )


# What the Kamer calls each kind, as a search finds it: "motie van wantrouwen" or
# "wantrouwen" are the motions of no confidence, though their subject never holds the word.
MOTION_KIND_NAMES: Final[dict[MotionKind, str]] = {
    CENSURE: "motie van afkeuring",
    NO_CONFIDENCE: "motie van wantrouwen",
}
# The words every name holds ("motie", "van") tell no kind apart.
_NAMING_NO_KIND: Final = frozenset.intersection(
    *(frozenset(name.split()) for name in MOTION_KIND_NAMES.values())
)


def kinds_named(word: str) -> list[MotionKind]:
    """The kinds whose name holds *word* (any case) as a word of its own that tells them
    apart: ``wantrouwen`` the motions of no confidence, ``afkeuring`` of censure."""
    wanted = word.strip().lower()
    if wanted in _NAMING_NO_KIND:
        return []
    return [kind for kind, name in MOTION_KIND_NAMES.items() if wanted in name.split()]
