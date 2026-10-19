"""Everything about an ECLI (pure, no I/O): its shape, its parts, the source it comes from,
the key of its judgment back to the ECLI, and the ECLIs a text names, checked for their
syntax and repaired where the text shows what was meant.

An ECLI is ``ECLI:<country>:<court>:<year>:<number>``. One is valid when its country is one
that issues ECLIs, its court code has the shape of one (a Dutch one is letters), its year lies
between 1900 and the current year and its number has the shape of one: a Dutch number is a
number or an LJN (two letters and four digits), another country's an alphanumeric ordinal
that may hold dots, underscores or hyphens. Whether a court code exists is not checked here.

What a text shows is repaired: an LJN whose digits the text sets apart ("BH 2815",
"BH:4033"), a number set apart from its year ("2019: 322"), NL and the court swapped
("ECLI:HR:NL:2023:26"), a range ("2018:2374-2375") that is its members, a word glued to the
number ("661verworpen", "BV2954.vgl") or the next ECLI glued to it, and a zero or one typed
for a letter of an LJN ("A09006"). Anything else that is not valid is dropped.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator

# The countries (ISO 3166 codes, EL for Greece) of the ECLI Council conclusions
# (2011/C 127/01, revised in 2019/C 360/01), EU for the courts of the Union, CE for the
# Council of Europe and EP for the boards of appeal of the European Patent Office.
ECLI_COUNTRIES = frozenset(
    {
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "GR", "HR",
        "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
        "CE", "EP", "EU",
    }
)  # fmt: skip
FIRST_YEAR = 1900
# The longest range read as its members.
MAX_RANGE = 20

# The parts of an ECLI as its shape has them; what makes one valid is ``is_valid_ecli``.
_COUNTRY = r"[A-Z]{2}"
_COURT_SHAPE = r"[A-Z0-9]+"
_YEAR = r"\d{4}"
_NUMBER_SHAPE = r"[A-Z0-9]+(?:[._-][A-Z0-9]+)*"
# An ECLI as a query or a value gives it, whole.
_SHAPE = re.compile(
    rf"ECLI:{_COUNTRY}:{_COURT_SHAPE}:{_YEAR}:{_NUMBER_SHAPE}", re.IGNORECASE
)
# An ECLI in a readable address (``/uitspraken/<ECLI>``): the contract with the front end,
# whose ``bron/leesbaar.ts`` has the same pattern (``tests/data/readable-paths.json``).
PATH_ECLI = re.compile(
    rf"^ECLI:{_COUNTRY}:{_COURT_SHAPE}:{_YEAR}:[A-Z0-9.]+$", re.IGNORECASE
)
# The node key of a judgment whose ECLI has no dot in its number (``make_node_key``).
_JUDGMENT_KEY = re.compile(r"^ecli_[a-z]{2}_[a-z0-9]+_\d{4}_[a-z0-9]+$")

# ECLI prefix -> judgment source.
ECLI_SOURCES: tuple[tuple[str, str], ...] = (
    ("ECLI:NL:", "rechtspraak"),
    ("ECLI:CE:ECHR:", "echr"),
    ("ECLI:EU:", "cjeu"),
)

_DUTCH_COURT = re.compile(r"[A-Z]{1,7}")
_COURT = re.compile(r"[A-Z][A-Z0-9]{0,6}")
_DUTCH_NUMBER = re.compile(r"\d{1,6}|[A-Z]{2}\d{4}")
_NUMBER = re.compile(_NUMBER_SHAPE)
_LJN = re.compile(r"[A-Z]{2}\d{4}")
# A word glued to a Dutch number: "661VERWORPEN", "BV2954.VGL".
_GLUED = re.compile(r"(\d{1,6}|[A-Z]{2}\d{4})\.?[A-Z]+")
# "LJN:BX7991" where the number goes.
_LJN_LABEL = re.compile(r":(?P<ljn>[A-Z]{2}\d{4})\b", re.IGNORECASE)

# An ECLI as a text writes it: a space may follow the colon before the number.
_CANDIDATE = re.compile(
    rf"\bECLI:(?P<country>{_COUNTRY}):(?P<court>{_COURT_SHAPE}):(?P<year>{_YEAR}):\s?"
    rf"(?!ECLI:)(?P<number>{_NUMBER_SHAPE})\b",
    re.IGNORECASE,
)
# A Dutch ECLI also as the courts abbreviate it, in a summary: "HR:2025:404".
_SHORT = re.compile(
    rf"\b(?:ECLI:NL:)?(?P<court>[A-Z]{{2,8}}):(?P<year>{_YEAR}):(?P<number>[A-Z0-9]{{1,8}})\b"
)
# An ECLI of a court of the European Union as the Court of Justice writes it, without
# ``ECLI:``: "Schrems, C‑362/14, EU:C:2015:650, punt 73".
_EU_COURT_ECLI = re.compile(
    r"\b(?:ECLI:)?EU:(?P<court>[CTF]):(?P<year>\d{4}):(?P<number>\d+)\b"
)
# The next ECLI glued to the one before: "695ECLI:NL:..." or "1998:ECLI:NL:...".
_GLUED_ECLI = re.compile(r"(?<=[A-Z0-9.:])(?=ECLI:)", re.IGNORECASE)
# The digits of an LJN set apart: "BH 2815", "BH:4033".
_LJN_DIGITS = re.compile(r"(?:\s{1,3}|:)(?P<digits>\d{1,4})\b")
# The end of a range set apart: "992 - 995".
_RANGE_END = re.compile(r"\s?[-–]\s?(?P<end>\d{1,6})\b")
# An LJN a text names on its own, the way decisions before 2013 were cited: "LJN BK9271",
# "LJN: BK9271", "LJN-nummer BK 9271".
_CITED_LJN = re.compile(
    r"\bLJN(?:-?nummer)?[:\s]*(?P<letters>[A-Z]{2})\s?(?P<digits>\d{4})\b",
    re.IGNORECASE,
)
# A Dutch ECLI whose number is an LJN: a decision published before 2013. Both Python and
# PostgreSQL read it (``db/queries/semantic/rechtspraak.eclis_with_an_ljn``).
LJN_ECLI = "^ECLI:NL:[A-Z]+:[0-9]{4}:([A-Z]{2}[0-9]{4})$"
_LJN_ECLI = re.compile(LJN_ECLI)


def _parts(ecli: str) -> list[str]:
    return ecli.strip().upper().split(":")


def country_code(ecli: str) -> str | None:
    """The country of an ECLI: ``NL`` of ``ECLI:NL:HR:2019:1858``; None when it has none."""
    parts = _parts(ecli)
    return parts[1] if len(parts) > 1 else None


def court_code(ecli: str) -> str | None:
    """The court code of an ECLI: ``HR`` of ``ECLI:NL:HR:2019:1858``; None when it has
    none."""
    parts = _parts(ecli)
    return parts[2] if len(parts) > 2 else None


def is_ecli(value: str) -> bool:
    """True for a value that has the shape of an ECLI, whole; whether it is valid is
    :func:`is_valid_ecli`."""
    return bool(_SHAPE.fullmatch(value.strip()))


def ecli_source(ecli: str | None) -> str | None:
    """Judgment source (``rechtspraak`` / ``echr`` / ``cjeu``) from the ECLI prefix."""
    if not ecli:
        return None
    upper = ecli.upper()
    return next(
        (source for prefix, source in ECLI_SOURCES if upper.startswith(prefix)), None
    )


def ecli_of_key(key: str) -> str | None:
    """The ECLI of a judgment's node key, or None (also for a key whose ECLI had a dot)."""
    return key.upper().replace("_", ":") if _JUDGMENT_KEY.match(key) else None


def is_valid_ecli(ecli: str, *, this_year: int | None = None) -> bool:
    """True for an ECLI of the right syntax (see the module); the court code is not looked up."""
    parts = _parts(ecli)
    if len(parts) != 5 or parts[0] != "ECLI":
        return False
    _, country, court, year, number = parts
    if country not in ECLI_COUNTRIES or not year.isdigit():
        return False
    if not FIRST_YEAR <= int(year) <= (this_year or dt.date.today().year):
        return False
    if country == "NL":
        return bool(_DUTCH_COURT.fullmatch(court) and _DUTCH_NUMBER.fullmatch(number))
    return bool(_COURT.fullmatch(court) and _NUMBER.fullmatch(number))


def cited_eclis(text: str | None) -> list[str]:
    """The valid ECLIs *text* names, repaired where it shows what was meant, upper-cased and
    once each, in the order of their first appearance."""
    return list(dict.fromkeys(ecli for ecli, _, _ in ecli_mentions(text)))


def ecli_mentions(text: str | None) -> list[tuple[str, int, int]]:
    """Every place *text* names a valid ECLI, as :func:`cited_eclis` reads it: ``(ecli,
    start, end)``, ``text[start:end]`` the ECLI as written (a range or a repaired LJN gives
    each of its ECLIs at the same place), in their order."""
    if not text:
        return []
    glued = [match.start() for match in _GLUED_ECLI.finditer(text)]
    spaced = _GLUED_ECLI.sub(" ", text)
    found: list[tuple[str, int, int]] = []
    for match in _CANDIDATE.finditer(spaced):
        start, end = _unspaced(match.start(), glued), _unspaced(match.end(), glued)
        for ecli in _repaired(match, spaced[match.end() : match.end() + 12]):
            if is_valid_ecli(ecli):
                found.append((ecli, start, end))
    return found


def _unspaced(position: int, glued: list[int]) -> int:
    """*position* in the text with a space put in at each of *glued* (offsets into the text
    as written, ascending), as an offset into the text as written."""
    return position - sum(1 for index, at in enumerate(glued) if at + index < position)


def cited_ljns(text: str | None) -> list[str]:
    """The LJNs *text* names on its own ("LJN BK9271"), upper-cased and once each, in the
    order of their first appearance."""
    return list(dict.fromkeys(ljn for ljn, _, _ in ljn_mentions(text)))


def ljn_mentions(text: str | None) -> list[tuple[str, int, int]]:
    """Every place *text* names an LJN on its own: ``(ljn, start, end)``, ``text[start:end]``
    the citation as written ("LJN BK9271"), in their order."""
    return [
        ((match["letters"] + match["digits"]).upper(), match.start(), match.end())
        for match in _CITED_LJN.finditer(text or "")
    ]


def eu_ecli_mentions(text: str | None) -> list[tuple[str, int, int]]:
    """Every place *text* names a judgment of a court of the European Union by its ECLI, also
    as the Court writes it ("EU:C:2015:650"): ``(ecli, start, end)``, the ECLI whole, in
    their order."""
    found = []
    for match in _EU_COURT_ECLI.finditer(text or ""):
        ecli = f"ECLI:EU:{match['court']}:{match['year']}:{match['number']}"
        if is_valid_ecli(ecli):
            found.append((ecli, match.start(), match.end()))
    return found


def short_ecli_mentions(text: str | None) -> list[tuple[str, int, int]]:
    """Every place *text* names a Dutch ECLI, also as the courts abbreviate it ("HR:2025:404"):
    ``(ecli, start, end)``, ``text[start:end]`` as written, in their order; not checked."""
    return [
        ("ECLI:NL:{court}:{year}:{number}".format(**match.groupdict()), *match.span())
        for match in _SHORT.finditer(text or "")
    ]


def ljn_of(ecli: str) -> str | None:
    """The LJN that is the number of *ecli* (``ECLI:NL:CRVB:2010:BK9271``: ``BK9271``), the
    ECLI of a decision published before 2013; None for any other."""
    match = _LJN_ECLI.match(ecli.strip().upper())
    return match[1] if match else None


def _repaired(match: re.Match[str], after: str) -> Iterator[str]:
    """The ECLIs a candidate stands for, given the text right *after* it; not yet checked."""
    country, court, year, number = (
        match.group(name).upper() for name in ("country", "court", "year", "number")
    )
    if court == "NL" and country != "NL":
        country, court = court, country
    prefix = f"ECLI:{country}:{court}:{year}:"
    if country != "NL":
        yield prefix + number
        return
    for dutch in _dutch_numbers(number, after):
        yield prefix + dutch


def _dutch_numbers(number: str, after: str) -> list[str]:
    """What a Dutch number stands for: the members of a range, a completed or corrected LJN,
    the number without a word glued to it, or the number as it is."""
    if number == "LJN":
        label = _LJN_LABEL.match(after)
        return [label.group("ljn").upper()] if label else []
    if "-" in number:
        start, _, end = number.partition("-")
        return _range(start, end)
    if number.isdigit():
        range_end = _RANGE_END.match(after)
        return _range(number, range_end.group("end")) if range_end else [number]
    return [_completed_ljn(number, after)]


def _range(start: str, end: str) -> list[str]:
    """The numbers from *start* to *end*; none for what is no short ascending range."""
    if not (start.isdigit() and end.isdigit()):
        return []
    first, last = int(start), int(end)
    if not first < last <= first + MAX_RANGE:
        return []
    return [str(n) for n in range(first, last + 1)]


def _completed_ljn(number: str, after: str) -> str:
    """An LJN with the digits the text sets apart joined to it, a zero or one read as the
    letter it stands for (and a letter as the digit), a glued word cut off."""
    digits = _LJN_DIGITS.match(after)
    if digits and re.fullmatch(r"[A-Z]{2}\d{0,3}", number):
        joined = number + digits.group("digits")
        if _LJN.fullmatch(joined):
            return joined
    if len(number) == 6 and number[0].isalpha():
        typed = (
            number[0]
            + number[1].replace("0", "O").replace("1", "I")
            + number[2:].replace("O", "0").replace("I", "1")
        )
        if _LJN.fullmatch(typed):
            return typed
    glued = _GLUED.fullmatch(number)
    return glued.group(1) if glued else number
