"""Who acts for the parties of a judgment, as its account of the procedure names them (pure:
no I/O, no store).

The kop names a lawyer on a line of its own ("advocaat: mr. X", read with the parties in
``core.judgment_parties``). The account of the procedure names them in a sentence:

- "waar [X] van [appellanten], bijgestaan door mr. drs. R. van Gelder, advocaat te
  Voorschoten, en verweerder, vertegenwoordigd door mr. I.T.F. Vermeulen, ambtenaar in
  dienst van de provincie, zijn verschenen";
- "de verdachte en zijn raadsman, mr. X, advocaat te Y";
- "Namens de verdachte heeft mr. X, advocaat te Y, beroep in cassatie ingesteld".

This reads those sentences in the paragraphs before the court's considerations and adds whom
they name to the party they name them for: the party whose name, alias, head ("het
college", "de minister") or role word ("verweerder", "appellanten") stands closest before.
A party the sentence hears "als partij" that the kop does not name is added. A sentence that
names no party it can tell, or one of several of a role in the singular, adds no one.

The role is the word the text gives: ``advocaat``, ``gemachtigde``, and in a criminal case
``raadsman`` (never in another area of law, where a raadsman is a gemachtigde). Without
one, whoever "vertegenwoordigt" a party is its gemachtigde, and whoever "bijstaat" a
suspect his raadsman. ``place`` is where the text says they practise ("te Voorschoten"),
``capacity`` what else it calls them ("ambtenaar in dienst van de provincie").
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from lawgraph.core.dutch_names import INITIALS, PLACE, TITLE, TITLES, surname
from lawgraph.core.judgment_parties import (
    REPRESENTATIVE_AGENT,
    REPRESENTATIVE_COUNSEL,
    ROLE_WORDS,
    SIDE_OTHER,
    Party,
    Role,
    representative,
    representative_role,
)
from lawgraph.core.judgments import AREA_CRIMINAL, area_of_law
from lawgraph.core.text_fold import fold
from lawgraph.core.xml import collapse_ws

# ── a person ─────────────────────────────────────────────────────────────────

# A person by a title or initials, never by a name alone: "mr. drs. R. van Gelder", "mr.
# Wattel", "G. Veldhuisen", "mr. R. van der Meulen MPM".
_PERSON = re.compile(rf"(?:{TITLE}+(?:{INITIALS}\s*)?|{INITIALS}\s*){surname()}")
# "zijn gemachtigde mr. X", "haar advocaat, mr. Y": the word names the role.
_AHEAD = rf"(?={TITLE}|{INITIALS})"  # a person follows
_NAMED_AS = re.compile(
    r"(?i:(?:(?:zijn|haar|hun|diens|de|een)\s+)?(?P<word>advoca(?:at|te|ten)|"
    r"gemachtigden?|raads(?:man|vrouw|lieden))\s*,?\s*)" + _AHEAD
)

# What the text calls a person after the comma behind the name: "advocaat te Voorschoten",
# "beiden advocaat in Amsterdam", "ambtenaar in dienst van de provincie".
_CAPACITY_WORDS = (
    r"advoca(?:at|te|ten)|gemachtigden?|raads(?:man|vrouw|lieden)|procureur|"
    r"rechtsbijstand\w*|(?:bedrijfs)?juriste?n?|ambtena(?:ar|ren)|werkzaam|"
    r"medewerk(?:st)?ers?|beleidsmedewerk\w*|in\s+dienst|verbonden\s+aan|kantoor\s*houdende|"
    r"(?:belasting|rechtskundig\s+|juridisch\s+)?advis?eurs?|fiscalist\w*|consulent\w*|"
    r"directeur\w*|bestuurders?|voorzitter|secretaris|werknemers?|vennoot|deurwaarder|"
    r"notaris|accountant\w*|deskundigen?|tolk|getuigen?"
)
_CAPACITY = re.compile(
    rf",\s*(?P<all>(?i:beiden|beide|allen|allebei)\s+)?(?P<text>(?i:{_CAPACITY_WORDS})\b"
    rf"(?:(?!\s+(?:en|alsmede)\s+(?:door\s+|de\s|het\s|een\s|\[|{_AHEAD}))"
    r"(?:[^,;.]|\.(?=\S)|\.\s+(?=[a-z])))*)"
)
# No representative: who explains or translates, or testifies.
_NO_REPRESENTATIVE = re.compile(r"^(?:deskundigen?|tolk|getuigen?)\b", re.IGNORECASE)
# "advocaten in Rotterdam": the capacity of every person before it without one.
_PLURAL = re.compile(
    r"^(?:advocaten|gemachtigden|raadslieden|ambtenaren|juristen|medewerkers|werknemers|"
    r"adviseurs)\b",
    re.IGNORECASE,
)
_PLACE = re.compile(rf"\b(?:te|in)\s+(?P<place>{PLACE})")
# Between two persons of one list: ", ", " en ", ", en door ".
_NEXT = re.compile(r"\s*(?:,\s*)?(?:(?:en|alsmede)\s+)?(?:door\s+)?")

# ── where the procedure names them ───────────────────────────────────────────

# "bijgestaan door", "vertegenwoordigd door", "vertegenwoordigd en bijgestaan door"
_BY = re.compile(
    r"\b(?P<how>bijgestaan|vertegenwoordigd)(?:\s+en\s+(?:bijgestaan|vertegenwoordigd))?"
    r"\s+door\s+",
    re.IGNORECASE,
)
# "zijn raadsman, mr. X", "de raadsman van de verdachte, mr. X", "raadsvrouw mr. Y"
_COUNSEL = re.compile(
    r"\b(?i:(?:(?:zijn|haar|diens|hun|de)\s+)?raads(?:man|vrouw|lieden)"
    r"(?:\s+van\s+(?P<who>[^,]{1,60}?))?\s*,?\s*)" + _AHEAD
)
# "Namens de verdachte heeft mr. X, advocaat te Y, ...", "Het cassatieberoep is ingesteld
# namens de verdachte en mr. X, advocaat te Y, heeft twee middelen van cassatie voorgesteld"
_ON_BEHALF = re.compile(
    r"\b(?i:namens\s+(?P<who>[^,.;]{1,80}?)\s*(?:,?\s+(?:heeft|hebben|is|zijn)|"
    r"\s+(?P<and>en))\s+)" + _AHEAD
)
# In a criminal case, who proposed the grounds of cassation: "Namens verdachte is beroep in
# cassatie ingesteld en heeft mr. X, advocaat te Y, bij schriftuur middelen van cassatie
# voorgesteld." Only where the grounds follow: "heeft mr. X" alone names anyone.
_PROPOSED = re.compile(r"\b(?:heeft|hebben)\s+" + _AHEAD)
_GROUNDS = re.compile(r"[^.]{0,80}?\b(?:middel(?:en)?|schriftuur|cassatie)\b")
# What follows a list of the persons who act for a party the kop does not name: it is heard
# as a party ("Voorts is de gemeenteraad, vertegenwoordigd door mr. X, als partij gehoord").
_HEARD_AS_PARTY = re.compile(r"\s*,?\s*als\s+partij\s+gehoord\b", re.IGNORECASE)
# The party such a sentence names: "de gemeenteraad", "het college", "[belanghebbende]".
_HEARD = re.compile(
    r"(?P<name>\[[^\]]{1,60}\]|(?:de|het)\s+[a-z][\w-]{2,})\s*,?\s*"
    r"(?:(?:vertegenwoordigd|bijgestaan)\s+door\s+\[[^\]]{1,60}\]\s*,?\s*)?"
    r"(?:inmiddels\s+)?$"
)
# Who acts for a party is no party: "[gemachtigde]".
_NO_PARTY = re.compile(r"gemachtig|advoca|raads(?:man|vrouw)", re.IGNORECASE)

# The headings of the account of the procedure: the paragraphs under any other heading are
# the court's own.
_PROCEDURE = re.compile(
    r"proces|procedure|geding|zitting|verloop|ontstaan|aanleg|inleiding|partijen|onderzoek|"
    r"instantie|cassatie|hoger\s+beroep|het\s+beroep|verzoek|vordering|ontvankelijk|"
    r"bestreden|voorgeschiedenis",
    re.IGNORECASE,
)
# The paragraphs read at most without a heading that ends the procedure.
MAX_PARAGRAPHS = 30
# A nested heading is at most this long; a longer "subheading" is a paragraph of text.
HEADING_CHARS = 80
# How far before "bijgestaan door" the party it is said of may be named.
WINDOW = 200

# A role word in the plural: "appellanten", "verweerders", "klaagsters".
_PLURAL_ROLE = re.compile(r"(?:en|ers)$")


def _person_words(text: str) -> str:
    """*text* in lower case, without accents and titles: what names one person."""
    plain = re.sub(rf"\b(?:{'|'.join(TITLES)})\b\.?", " ", fold(text))
    return " ".join(re.findall(r"\w+", plain))


# ── the persons of one list ──────────────────────────────────────────────────


def _persons(
    text: str, start: int, default: str, criminal: bool
) -> tuple[list[dict[str, Any]], int]:
    """The persons listed from *start* ("mr. A, advocaat te X, en mr. B"), each with its
    role (the word before it gives, else *default*), place and capacity, and where the
    list ends."""
    found: list[dict[str, Any]] = []
    without: list[dict[str, Any]] = []  # those no capacity was given yet
    excluded: list[dict[str, Any]] = []
    pos = start
    end = start
    while True:
        word = None
        if named := _NAMED_AS.match(text, pos):
            word, pos = named["word"], named.end()
        person = _PERSON.match(text, pos)
        if not person:
            break
        name = collapse_ws(person[0])
        role = representative_role(word, criminal=criminal) or default
        current = representative(name, role)
        found.append(current)
        without.append(current)
        pos = end = person.end()
        if capacity := _CAPACITY.match(text, pos):
            said = collapse_ws(capacity["text"])
            targets = without if capacity["all"] or _PLURAL.match(said) else [current]
            for target in targets:
                _give(target, said, criminal, excluded)
            without = []
            pos = end = capacity.end()
        step = _NEXT.match(text, pos)
        following = step.end() if step else pos
        if not (_NAMED_AS.match(text, following) or _PERSON.match(text, following)):
            break
        pos = following
    return [p for p in found if all(p is not e for e in excluded)], end


def _give(
    person: dict[str, Any], said: str, criminal: bool, excluded: list[dict[str, Any]]
) -> None:
    """Give *person* what the text *said* of them: the role it names, where they practise,
    any other capacity."""
    if _NO_REPRESENTATIVE.match(said):
        excluded.append(person)
        return
    place = _PLACE.search(said)
    if place:
        person["place"] = place["place"]
    if re.match(r"kantoor\s*houdend", said, re.IGNORECASE):
        return  # where they practise, no capacity
    word = said.split()[0]
    named = representative_role(word, criminal=criminal)
    if named:
        person["role"] = named
        rest = _PLACE.sub("", said).strip(" ,")
        rest = re.sub(
            r"^(?:advoca(?:at|te|ten)|gemachtigden?|raads(?:man|vrouw|lieden))\b\s*",
            "",
            rest,
            flags=re.IGNORECASE,
        )
        if rest and not re.fullmatch(r"(?:en\s+procureur|kantoor\s*houdende)", rest):
            person["capacity"] = rest
    else:
        person["capacity"] = _PLACE.sub("", said).strip(" ,") or None


# ── the party a list is for ──────────────────────────────────────────────────


def _labels(party: dict[str, Any]) -> set[str]:
    """The roles a party goes by: its own, those the kop names, that of its anonymised
    name ("[betrokkene A]")."""
    labels = {party.get("role"), *(party.get("roles") or [])}
    name = party.get("name") or ""
    if name.startswith("["):
        for label, pattern in ROLE_WORDS.items():
            if re.match(rf"\[\s*(?:de\s+)?(?:{pattern})\b", name, re.IGNORECASE):
                labels.add(label)
    return {label for label in labels if label}


def _short_names(party: dict[str, Any]) -> list[str]:
    """What the procedure may call a party short: an office by its head ("het college" of
    "het college van burgemeester en wethouders van Utrecht", "het algemeen bestuur" of "het
    algemeen bestuur van de bestuurscommissie ..."), an anonymised name without its
    brackets ("de vreemdeling" of "[de vreemdeling]")."""
    name = party["name"]
    found = []
    if head := re.match(
        r"^((?:de|het)\s+(?:[a-z][\w-]+\s+){0,2}[a-z][\w-]+)\s+(?:van|voor)\b", name
    ):
        found.append(head[1])
    if inner := re.fullmatch(r"\[\s*([^\]]+?)\s*\]", name):
        found.append(inner[1])
    return found


def _mentions(
    parties: list[dict[str, Any]], window: str
) -> Iterable[tuple[int, int, list[int]]]:
    """``(end, length, parties)`` of each mention of parties in *window*."""
    lower = window.lower()
    for index, party in enumerate(parties):
        for written in (party.get("name"), party.get("alias"), *_short_names(party)):
            if not written:
                continue
            for match in re.finditer(
                rf"(?<!\w){re.escape(written.lower())}(?!\w)", lower
            ):
                yield match.end(), len(written), [index]
    for label, pattern in ROLE_WORDS.items():
        holders = [i for i, p in enumerate(parties) if label in _labels(p)]
        if not holders:
            continue
        for match in re.finditer(rf"\b(?:{pattern})\b", lower):
            plural = bool(_PLURAL_ROLE.search(match[0])) and len(holders) > 1
            if plural or len(holders) == 1:
                yield match.end(), len(match[0]), holders


def _party_in(parties: list[dict[str, Any]], window: str) -> list[int]:
    """The parties *window* names last: those a list of persons after it acts for."""
    best = max(_mentions(parties, window), key=lambda m: (m[0], m[1]), default=None)
    return best[2] if best else []


# ── the paragraphs of the procedure ──────────────────────────────────────────


def procedure_text(paragraphs: list[dict[str, Any]]) -> list[str]:
    """The account of the procedure, a text per section: the kop, and the paragraphs up to
    the first heading that is not of the procedure ("Overwegingen", "De beoordeling"), at
    most ``MAX_PARAGRAPHS``. The paragraphs of a section are one text: a sentence may run
    over two ("... en zijn raadsvrouw," / "mr. N.E. Renders, hebben aangevoerd")."""
    sections: list[list[str]] = [[]]
    seen_body = False
    for index, paragraph in enumerate(paragraphs[:MAX_PARAGRAPHS]):
        text = re.sub(r"\s+", " ", (paragraph.get("text") or "").replace("\u00a0", " "))
        kind = paragraph.get("kind")
        heading = kind == "heading" or (
            index > 0 and kind == "subheading" and len(text) <= HEADING_CHARS
        )
        if heading:
            if seen_body and not _PROCEDURE.search(text):
                break
            sections.append([])
            continue
        seen_body = seen_body or index > 0
        sections[-1].append(text)
        if index == 0:
            sections.append([])  # the kop is a section of its own
    return [" ".join(texts) for texts in sections if texts]


def _heard_party(
    text: str, window: str, end: int, context: str
) -> dict[str, Any] | None:
    """The party a sentence hears "als partij" that the kop does not name: what stands
    last in *window*, before "vertegenwoordigd door", the fuller name the procedure gives it
    ("de gemeenteraad van Nieuwerkerk aan den IJssel") with the short one as its alias."""
    if not _HEARD_AS_PARTY.match(text, end):
        return None
    heard = _HEARD.search(window)
    if not heard or _NO_PARTY.search(heard["name"]):
        return None
    short = heard["name"]
    name, alias = short, None
    if not short.startswith("["):
        fuller = re.search(rf"\b(?i:{re.escape(short)})\s+van\s+({PLACE})", context)
        if fuller:
            name, alias = f"{short} van {fuller[1]}", short
    party = Party(name=name, side=SIDE_OTHER, alias=alias)
    party.state(Role.PARTY)
    return party.as_dict()


def _initials_and_surname(name: str) -> tuple[list[str], list[str]]:
    words = _person_words(name).split()
    initials = 0
    while initials < len(words) - 1 and len(words[initials]) == 1:
        initials += 1
    return words[:initials], words[initials:]


def same_person(a: str, b: str) -> bool:
    """Do two names name one person: the same surname, and initials of which one starts the
    other or none ("mr. B. van Dijk" and later "mr. Van Dijk")?"""
    (ia, sa), (ib, sb) = _initials_and_surname(a), _initials_and_surname(b)
    shorter = min(len(ia), len(ib))
    return sa == sb and ia[:shorter] == ib[:shorter]


def _add(party: dict[str, Any], persons: list[dict[str, Any]]) -> None:
    """Add *persons* to those of *party*, each once."""
    known = party["representatives"]
    for person in persons:
        if not any(same_person(person["name"], r["name"]) for r in known):
            known.append(dict(person))


def _resolve(
    parties: list[dict[str, Any]], who: str | None, window: str, criminal: bool
) -> list[int]:
    if who:
        found = _party_in(parties, who)
        if found:
            return found
    found = _party_in(parties, window)
    if not found and criminal:
        suspects = [i for i, p in enumerate(parties) if Role.SUSPECT in _labels(p)]
        found = suspects if len(suspects) == 1 else []
    return found


def _read_paragraph(
    parties: list[dict[str, Any]], text: str, context: str, criminal: bool
) -> None:
    # (start, end, who the text says it is for, the role without a word, whether the
    # grounds of cassation must follow)
    anchors: list[tuple[int, int, str | None, str, bool]] = []
    for match in _BY.finditer(text):
        how = match["how"].lower()
        default = (
            REPRESENTATIVE_COUNSEL
            if criminal and how == "bijgestaan"
            else REPRESENTATIVE_AGENT
        )
        anchors.append((match.start(), match.end(), None, default, False))
    counsel = REPRESENTATIVE_COUNSEL if criminal else REPRESENTATIVE_AGENT
    for match in _COUNSEL.finditer(text):
        anchors.append((match.start(), match.end(), match["who"], counsel, False))
    for match in _ON_BEHALF.finditer(text):
        default = REPRESENTATIVE_COUNSEL if criminal else REPRESENTATIVE_AGENT
        anchors.append(
            (match.start(), match.end(), match["who"], default, bool(match["and"]))
        )
    if criminal:
        for match in _PROPOSED.finditer(text):
            anchors.append(
                (match.start(), match.end(), None, REPRESENTATIVE_COUNSEL, True)
            )
    anchors.sort()
    after = 0  # the end of the list before: the window of the next starts there
    for start, end, who, default, grounds in anchors:
        if start < after:
            continue
        persons, listed = _persons(text, end, default, criminal)
        if grounds and not _GROUNDS.match(text, listed):
            persons = []
        window = text[max(after, start - WINDOW) : start]
        if not persons:
            continue  # "[X], vertegenwoordigd door [gemachtigde], bijgestaan door ...": the
            # window of the next still holds the party
        after = listed
        targets = _resolve(parties, who, window, criminal)
        if not targets and (heard := _heard_party(text, window, after, context)):
            parties.append(heard)
            targets = [len(parties) - 1]
        for index in targets:
            _add(parties[index], persons)


def read_counsel(
    parties: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    subjects: list[str] | None,
) -> list[dict[str, Any]]:
    """*parties* (``read_parties``) with whom the account of the procedure in *paragraphs*
    (``judgment_text``) names for each added to its ``representatives``, and the parties it
    hears that the kop does not name."""
    criminal = area_of_law(subjects) == AREA_CRIMINAL
    texts = procedure_text(paragraphs)
    context = " ".join(texts)
    for text in texts:
        _read_paragraph(parties, text, context, criminal)
    return parties
