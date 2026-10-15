"""The advocate-general of a Rechtspraak conclusion: who wrote it, as its opening lines name
them, and the role they sign in."""

from __future__ import annotations

import itertools
import re
import xml.etree.ElementTree as ET

from lawgraph.core.dutch_names import INITIALS, LONG_WORD, TITLE, surname
from lawgraph.core.judgment_metadata import judgment_bodies
from lawgraph.core.judgment_paragraphs import (
    KOP_MAX_PROSE_LINES,
    PROSE_LINE_CHARS,
    line_elements,
    printed_lines,
)

# A conclusion names who wrote it above its parties, a surname with initials or "mr.":
# "T. Hartlief" on a line of its own below CONCLUSIE, "mr. P.J. Wattel" above
# "Advocaat-Generaal", "Zaaknr: 18/04298 (Prejudicieel) mr. Wattel", "Conclusie van den
# Advocaat-Generaal Mr. Besier."; the signature at the end gives only the office.

# A word that follows a name on its line and is no part of it: "Mr. T.N.B.M. Spronken
# Conclusie inzake:", "D.J.C. Aben Vordering tot cassatie", "S.V. de Jong te Amsterdam".
_AFTER_NAME = (
    r"(?:conclusie|nadere|aanvullende|vordering|zitting|datum|advocaat|procureur|"
    r"raadsheer|staatsraad|parket|en|te|in|uit)"
)
_SURNAME = surname(LONG_WORD, stop=_AFTER_NAME)
_PERSON = rf"(?:{INITIALS})?\s*{_SURNAME}"
# All of a line: "T. Hartlief", "mr. Wattel", "F.F. Langemeijer en M.H. Wissink".
_NAME_LINE = re.compile(
    rf"^(?P<mr>{TITLE}+)?(?P<name>(?P<initials>{INITIALS})?\s*{_SURNAME}"
    rf"(?:\s+en\s+{_PERSON})?)\.?$"
)
_NAME_IN_LINE = re.compile(rf"\b{TITLE}(?P<name>{_PERSON})")
# At the end of a line, with initials: "Zaaknr :26/00083 R.H. de Bock".
_NAME_ENDS_LINE = re.compile(rf"\s(?P<name>{INITIALS}\s*{_SURNAME})\.?$")
# Where the parties begin: a name after it is theirs, or their lawyer's. Not "inzake
# prejudiciële vraag", which says what the conclusion is on.
_PARTIES_BEGIN = re.compile(
    r"\b(?:inzake|in\s+de\s+za(?:ak|ken)|tussen)\b(?!\s+prejudici)", re.IGNORECASE
)
OPENING_LINES = 20


def _name_in(line: str) -> str | None:
    """The name of a person *line* gives: all of it with initials or "mr." in front, one
    behind "mr." in it, or one with initials that ends it."""
    whole = _NAME_LINE.match(line.strip())
    if whole and (whole["mr"] or whole["initials"]):
        return whole["name"].strip()
    found = _NAME_IN_LINE.search(line) or _NAME_ENDS_LINE.search(line.rstrip())
    return found["name"].strip() if found else None


def advocate_general(root: ET.Element) -> str | None:
    """The advocate-general (or procureur-generaal) who wrote a conclusion, as its first
    ``OPENING_LINES`` lines name them before its parties: "T. Hartlief", "P.J. Wattel", or
    only the surname ("Wattel") where the conclusion gives no more; two who wrote it
    together as one ("F.F. Langemeijer en M.H. Wissink"). Prose before the parties names
    no one, and more than ``KOP_MAX_PROSE_LINES`` lines of it end the search. ``None``
    when they name no one."""
    body = next(iter(judgment_bodies(root)), None)
    if body is None:
        return None
    lines = (line for e in line_elements(body) for line in printed_lines(e))
    prose = 0
    for line in list(itertools.islice(lines, OPENING_LINES)):
        begin = _PARTIES_BEGIN.search(line)
        head = line[: begin.start()] if begin else line
        if len(head) <= PROSE_LINE_CHARS and (name := _name_in(head)):
            return name
        prose += len(line) > PROSE_LINE_CHARS
        if begin or prose > KOP_MAX_PROSE_LINES:
            return None
    return None


# Who signs a conclusion: below "De Procureur-Generaal bij de Hoge Raad der Nederlanden," the
# role, as the Parket writes it: "A-G", "AG", "Advocaat-Generaal", "(a.-g.)", "Wnd. A-G",
# "plv." (the plaatsvervangend procureur-generaal). The heading of the office at the top reads
# the same with no role below it. Letters only, lower case -> the role.
_OFFICE = re.compile(
    r"procureur[- ]generaal\s+bij\s+de\s+hoge\s+raad(?:\s+der\s+nederlanden)?\s*,?",
    re.IGNORECASE,
)
ADVOCAAT_GENERAAL = "advocaat-generaal"
WAARNEMEND_ADVOCAAT_GENERAAL = "waarnemend advocaat-generaal"
PLAATSVERVANGEND_PROCUREUR_GENERAAL = "plaatsvervangend procureur-generaal"
PLAATSVERVANGEND_ADVOCAAT_GENERAAL = "plaatsvervangend advocaat-generaal"
_SIGNED_ROLES = {
    "ag": ADVOCAAT_GENERAAL,
    "advocaatgeneraal": ADVOCAAT_GENERAAL,
    "agibd": ADVOCAAT_GENERAAL,  # in buitengewone dienst
    "wndag": WAARNEMEND_ADVOCAAT_GENERAAL,
    "waarnemendadvocaatgeneraal": WAARNEMEND_ADVOCAAT_GENERAAL,
    "plv": PLAATSVERVANGEND_PROCUREUR_GENERAAL,
    "plvag": PLAATSVERVANGEND_ADVOCAAT_GENERAAL,
}


def advocate_general_role(text: str | None) -> str | None:
    """The role of who signs a conclusion, from the line below the office in its signature:
    ``advocaat-generaal``, ``waarnemend advocaat-generaal``, ``plaatsvervangend
    procureur-generaal`` ("plv.") or ``plaatsvervangend advocaat-generaal`` ("plv. AG").
    ``None`` when the conclusion writes none, or one that is not clear: an empty line (an
    A-G signs so too)."""
    for match in reversed(list(_OFFICE.finditer(text or ""))):
        line = (text or "")[match.end() :].lstrip().split("\n", 1)[0]
        role = _SIGNED_ROLES.get(re.sub(r"[^a-z]", "", line.lower()))
        if role:
            return role
    return None
