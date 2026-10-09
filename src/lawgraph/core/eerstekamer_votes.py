"""The votes of the Eerste Kamer on bills, as eerstekamer.nl lists them (pure functions).

``/stemmingen_per_vergaderdag?filter=alles`` lists every vote since June 2015, newest first,
25 to a page and grouped by the day of the meeting (``<h2>`` with the date; a day that runs
over a page starts the next one again, ``(vervolg)``). Each vote is one item: the outcome as
the image the Kamer shows (its ``alt``: ``Aangenomen``, ``Verworpen``), what was voted on
with a link to its page, and a link to the part of the report of the meeting whose text is
how it was decided (``Hamerstuk``, ``Stemming bij zitten en opstaan, aangenomen``), with the
factions that voted for, against, or asked to have their vote recorded. What was voted on is
a bill (``/wetsvoorstel/``, its number: ``36.791``, ``36.600 VII``, ``36.455 (R2188)``) or a
motion (``/motiedossier/``, the number of its dossier and its letter: ``37.020, M``, its name
before it: ``Motie-Beukering (Fractie-Beukering) c.s. over …``). The list of bills alone
(``filter=wetsvoorstellen``) shows a vote on a motion as one on its bill, under the bill's
name and number.

``/verworpen_in_de_eerste_kamer`` lists every bill the Kamer rejected since 1996, newest
first, 50 to a page: the day, the bill's page and its number.

Everything is read as the Kamer writes it: the outcome, the method and the names of the
factions are its values. Only the page structure is parsed, never a sentence.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field

from lawgraph.core.rijksoverheid import parse_date

VOTES_PATH = "/stemmingen_per_vergaderdag?filter=alles"
REJECTED_PATH = "/verworpen_in_de_eerste_kamer"

# The outcome the Kamer shows (``alt`` of the image of a vote).
RESULT_ADOPTED = "Aangenomen"
RESULT_REJECTED = "Verworpen"

# ``<h2><a id="p1"></a>29 september 2026`` opens a day; ``(vervolg)`` after the date says the
# day began on the page before.
_DAY = re.compile(r'<h2><a id="p\d+"></a>([^<]*)</h2>')
_CONTINUED = "(vervolg)"
_ITEM = '<li class="opsomitem met_image image_breed">'
_RESULT = re.compile(r'<img [^>]*alt="([^"]*)"')
_BILL = re.compile(r'<a href="(/wetsvoorstel/[^"]+)">([^<]+)</a>')
_MOTION = re.compile(r'<a href="(/motiedossier/[^"]+)">([^<]+)</a>')
# The number of a motion: that of its dossier and its letter, ``37.020, M``.
_MOTION_NUMBER = re.compile(r"^(?P<number>.+?),\s*(?P<letter>[A-Z]{1,3})$")
_METHOD = re.compile(r'<a href="([^"]*verslagdeel[^"]*)">\s*([^<]+?)\s*</a>')
_FACTIONS = re.compile(r"<strong>([^<]+):</strong>([^<]*)")
# ``eerdere stemmingen``: the link to the page before (in time) of the list.
_EARLIER = re.compile(
    r'<a href="([^"]+)" class="grid-x nowr">\s*<span>eerdere stemmingen'
)
# The number of a bill as the Kamer writes it: ``36.791``, ``36.600 VII``, ``36.455 (R2188)``.
_NUMBER = re.compile(r"^(\d{1,3})\.(\d{3})(?: (\S.*))?$")

_REJECTED_ITEM = re.compile(
    r'<li class="grid-x nowr lnk_f">\s*<a href="(/wetsvoorstel/[^"]+)">(.*?)</a>\s*</li>',
    re.S,
)
_REJECTED_DATE = re.compile(r'<span class="strong opm_def">([^<]+)</span>')
# The number that ends the title of a rejected bill: ``(36.855)``, ``(36.455 (R2188))``.
_REJECTED_NUMBER = re.compile(r"\((\d{1,3}\.\d{3}(?: [^()]*(?:\([^)]*\))?)?)\)\s*$")
_NEXT_REJECTED = re.compile(r'href="(/verworpen_in_de_eerste_kamer\?start_\d+=\d+)"')

# The factions a vote names, by the label before them.
LABEL_FOR = "voor"
LABEL_AGAINST = "tegen"
LABEL_NOTED = "aantekening gevraagd"


@dataclass(frozen=True)
class Vote:
    """One vote of the Eerste Kamer on a bill."""

    date: str  # YYYY-MM-DD
    number: str  # as the Kamer writes it: 36.600 VII
    label: str  # the dossier label of the Tweede Kamer: 36600-VII
    title: str
    result: str  # Aangenomen, Verworpen
    bill_path: (
        str | None
    )  # /wetsvoorstel/36791_wet_toekomstbestendige; None of a motion
    method: str | None = None  # Hamerstuk, Stemming bij zitten en opstaan, aangenomen
    report_path: str | None = None  # the part of the report of the meeting
    factions: dict[str, list[str]] = field(default_factory=dict)  # by label
    # of a vote on a motion: its letter in its dossier (M) and its page
    letter: str | None = None
    motion_path: str | None = None  # /motiedossier/37020_m_motie_beukering_fractie


def text(fragment: str) -> str:
    """*fragment* of HTML as one line of plain text."""
    plain = html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", plain.replace("\xa0", " ")).strip()


def dossier_label(number: str) -> str | None:
    """The dossier label of the Tweede Kamer of a number as the Eerste Kamer writes it:
    ``36.791`` -> ``36791``, ``36.600 VII`` -> ``36600-VII``, ``36.455 (R2188)`` ->
    ``36455-(R2188)``; None for anything else."""
    match = _NUMBER.match(number.strip())
    if not match:
        return None
    base = match[1] + match[2]
    return f"{base}-{match[3]}" if match[3] else base


def days(page: str) -> list[tuple[str | None, bool, str]]:
    """``(date, continued, fragment)`` of every day on a page of the vote list, in order;
    ``continued`` when the day began on the page before."""
    parts = _DAY.split(page)
    return [
        (parse_date(heading), _CONTINUED in heading, fragment)
        for heading, fragment in zip(parts[1::2], parts[2::2], strict=True)
    ]


def earlier_page(page: str) -> str | None:
    """The path of the next page of the vote list (older votes), None on the last."""
    match = _EARLIER.search(page)
    return html_lib.unescape(match[1]) if match else None


def _names(value: str) -> list[str]:
    """``CDA, D66 en VVD`` -> ``["CDA", "D66", "VVD"]``: the list as the Kamer writes it."""
    head, _, last = text(value).rpartition(" en ")
    return [n.strip() for n in [*head.split(","), last] if n.strip()]


def votes(date: str, fragment: str) -> list[Vote]:
    """The votes of one day (its fragment of one or more pages): on a bill or a motion."""
    found = []
    for item in fragment.split(_ITEM)[1:]:
        result = _RESULT.search(item)
        subject = _BILL.search(item) or _MOTION.search(item)
        if not result or not subject:
            continue
        number, letter = text(subject[2]), None
        motion = subject[1].startswith("/motiedossier/")
        if motion:
            parts = _MOTION_NUMBER.match(number)
            if not parts:
                continue
            number, letter = parts["number"], parts["letter"]
        label = dossier_label(number)
        if label is None:
            continue
        method = _METHOD.search(item)
        found.append(
            Vote(
                date=date,
                number=number,
                label=label,
                title=text(item[: subject.start()]).rstrip(" ("),
                result=result[1],
                bill_path=None if motion else subject[1],
                method=text(method[2]) if method else None,
                report_path=method[1] if method else None,
                factions={
                    text(name): _names(names) for name, names in _FACTIONS.findall(item)
                },
                letter=letter,
                motion_path=subject[1] if motion else None,
            )
        )
    return found


def rejected(page: str) -> list[Vote]:
    """The bills on a page of the list of rejected bills."""
    found = []
    for path, body in _REJECTED_ITEM.findall(page):
        date = _REJECTED_DATE.search(body)
        lines = [text(line) for line in re.split(r"<br\s*/?>", body)]
        title = next((line for line in lines[1:] if line), "")
        number = _REJECTED_NUMBER.search(title)
        day = parse_date(date[1]) if date else None
        label = dossier_label(number[1]) if number else None
        if not day or not number or not label:
            continue
        found.append(
            Vote(
                date=day,
                number=number[1],
                label=label,
                title=title[: number.start()].strip(),
                result=RESULT_REJECTED,
                bill_path=path,
            )
        )
    return found


def next_rejected_page(page: str, seen: set[str]) -> str | None:
    """The path of a page of the list of rejected bills not yet in *seen*."""
    return next(
        (
            html_lib.unescape(p)
            for p in _NEXT_REJECTED.findall(page)
            if html_lib.unescape(p) not in seen
        ),
        None,
    )
