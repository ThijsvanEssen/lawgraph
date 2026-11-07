"""The commitments (toezeggingen) of the Eerste Kamer on eerstekamer.nl, read by their
structure (pure functions).

The register (``LIST_PATH``) is a form; sent without a choice (``m=1``) it lists every
commitment since June 2003, the newest first, 50 a page, each with its page
(``/toezegging/…``), the day it was made, its number (``T04275``) and its status. The page of a
commitment opens with the commitment itself ("De minister van … zegt de Kamer … toe …") and
holds its key data in a table of ``<th scope="row">`` and ``<td>``: ``Nummer``, ``Status``
(``openstaand``, ``voldaan``, ``deels voldaan``, ``afgevoerd``), ``Datum toezegging``,
``Deadline``, who is responsible (``Verantwoordelijke(n)``; for an office since renamed or
merged ``Voormalige Verantwoordelijke(n)``, the office of that day, and ``Huidige
Verantwoordelijke(n)``, the one that answers for it now), ``Kamerleden``, ``Commissie``,
``Soort activiteit``, ``Categorie``, ``Onderwerpen`` and ``Kamerstukken`` (each a link with the
number of its dossier in brackets: ``Wet meer zekerheid flexwerkers (36.746)``). Under "Uit de
stukken" it quotes the Handelingen or Kamerstuk the commitment was made in, with who spoke
(``Minister <strong>Vijlbrief:</strong>``). Everything is read as the Kamer writes it.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from lawgraph.core.dutch_dates import dutch_day
from lawgraph.core.ek_bills import ek_dossier_label
from lawgraph.core.signatories import post_kind
from lawgraph.core.xml import collapse_ws, html_text

# The register of commitments: its form, and the list it answers with when sent as it is.
LIST_PATH = "/toezeggingen_2"

_FORM_ID = re.compile(r'<input type="hidden" name="dlgid" value="([^"]+)"')
_ENTRY = re.compile(
    r'<a href="(/toezegging/[^"]+)">.*?<span class="strong">([^<]*)</span>\s*<br\s*/?>'
    r"\s*(T\d+):.*?<span class=\"cursief opm_def\">\s*status:\s*([^<]*?)\s*</span>",
    re.S,
)
_NEXT = re.compile(r'<li class="plus volgende">\s*<a href="(/toezeggingen_2\?[^"]+)"')
_ROW = re.compile(
    r'<th scope="row"[^>]*>\s*([^<]+?)\s*</th>\s*<td[^>]*>(.*?)</td>', re.S
)
_TEXT = re.compile(r'<p class="mnone">(.*?)</p>', re.S)
_LINK = re.compile(r'<a href="([^"]+)"[^>]*>(.*?)</a>', re.S)
# ``(36.746)``, ``(36.915 XII)``, ``(36.455 (R2188))``: the dossier at the end of a link.
_DOSSIER = re.compile(r"\((\d{1,3}\.\d{3}(?:[^()]|\([^()]*\))*)\)\s*$")
# ``(2003-2010)``, ``(2012-2017)``: the years the Kamer adds to an office it names by the name
# of a later period.
_PERIOD = re.compile(r"\s*\(\s*\d{4}\s*-\s*(?:\d{4})?\s*\)\s*$")
_PASSAGE = re.compile(r"<h2>\s*<a id=\"p\d+\"></a>\s*Uit de stukken.*?(?=<h2>|$)", re.S)
# ``Minister <strong>De Graaf</strong>:``, ``Staatssecretaris <strong>Van Ark:</strong>``,
# ``Minister <strong>Pau</strong>l:`` (the rest of the name after the tag): who spoke for the
# government in the passage quoted.
_SPEAKER = re.compile(
    r"\b((?:Vice-?)?[Mm]inister(?:-president)?|[Ss]taatssecretaris)\s*<strong>"
    r"\s*([^<:]+?)\s*:?\s*</strong>([^\s<:]*)"
)
_CITATION = re.compile(r'<p class="mnone">(.*?)</p>', re.S)

# Why a commitment of the Eerste Kamer has no member (``member_missing``): the passage quoted
# names no one who spoke for the government in an office of its kind, or the name fits no one
# or several who held such an office that day.
MemberMissing = Literal["no_name", "unmatched"]
NO_NAME: Final[MemberMissing] = "no_name"
UNMATCHED: Final[MemberMissing] = "unmatched"


class EkCommitmentProps(BaseModel):
    """The props of a commitment that only the Eerste Kamer gives (``core.props``)."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    url: str | None = None
    """Of the Eerste Kamer: its page on eerstekamer.nl."""
    read_on: str | None = None
    """Of the Eerste Kamer: the day its page was read."""
    responsible: list[str] | None = None
    """Of the Eerste Kamer: the offices responsible that day, as written (`Verantwoordelijke(n)`,
    or `Voormalige Verantwoordelijke(n)` for an office since renamed), the years the Kamer
    adds to a later name left out; the first is `minister_role`."""
    responsible_now: list[str] | None = None
    """Of the Eerste Kamer: the offices that answer for it now (`Huidige
    Verantwoordelijke(n)`), when the Kamer names them apart."""
    former_number: str | None = None
    """Of the Eerste Kamer: its number before the register (`tr_BIZA_2004_23`)."""
    asked_by: list[str] | None = None
    """Of the Eerste Kamer: the members it was made to (`Kamerleden`), as written."""
    committees: list[str] | None = None
    """Of the Eerste Kamer: its committees, as written."""
    activity_kind: str | None = None
    """Of the Eerste Kamer: where it was made (`Plenaire vergadering`)."""
    category: str | None = None
    """Of the Eerste Kamer: `brief/nota`, `evaluatie`, `lagere regelgeving`,
    `legisprudentie`, `overig`."""
    subjects: list[str] | None = None
    """Of the Eerste Kamer: its subjects (`Onderwerpen`)."""
    documents: list[str] | None = None
    """Of the Eerste Kamer: its Kamerstukken as named (`Wet meer zekerheid flexwerkers
    (36.746)`)."""
    dossier_labels: list[str] | None = None
    """Of the Eerste Kamer: the dossiers of those Kamerstukken (`36746`, `36915-XII`), each
    stored one `ABOUT` (`basis` `kamerstukken`)."""
    citation: str | None = None
    """Of the Eerste Kamer: the passage it was made in (`Handelingen I, 2025/2026, nr.39,
    item 18, p. 10.`)."""
    member_missing: MemberMissing | None = None
    """Of the Eerste Kamer, without `member_key`: why (`semantic eerstekamer-government`):
    `no_name`, the passage names no one who spoke in an office of its kind; `unmatched`, the
    name fits no one or several who held one that day. A gap, not filled by hand."""
    ministry_held: str | None = None
    """Of the Eerste Kamer: the ministry of the post the member held that day, when it is not
    `ministry` (that of the office the Kamer names): a conflict, not corrected."""


@dataclass(frozen=True)
class ListedCommitment:
    """A commitment as the register lists it."""

    path: str  # /toezegging/uitzondering_pgb_sector_voor_2030
    number: str  # T04275
    made_on: str | None  # YYYY-MM-DD
    status: str  # openstaand


@dataclass(frozen=True)
class Speaker:
    """One who spoke for the government in the passage quoted: ``Minister``, ``Vijlbrief``."""

    function: str
    name: str


@dataclass(frozen=True)
class CommitmentPage:
    """What the page of a commitment of the Eerste Kamer says of it."""

    number: str  # T04275
    text: str | None = None
    status: str | None = None  # openstaand
    made_on: str | None = None  # YYYY-MM-DD
    deadline: str | None = None  # YYYY-MM-DD
    # the offices responsible that day, as written (the years of a later name left out)
    responsible: list[str] = field(default_factory=list)
    # the offices that answer for it now, when the Kamer names them apart
    responsible_now: list[str] = field(default_factory=list)
    former_number: str | None = None  # tr_BIZA_2004_23
    members: list[str] = field(default_factory=list)  # I.M. Lagas MDR (BBB)
    committees: list[str] = field(default_factory=list)
    activity_kind: str | None = None  # Plenaire vergadering
    category: str | None = None  # lagere regelgeving
    subjects: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)  # as the Kamer names them
    dossiers: list[str] = field(default_factory=list)  # 36746, 36915-XII
    citation: str | None = None  # Handelingen I, 2025/2026, nr.39, item 18, p. 10.
    speakers: list[Speaker] = field(default_factory=list)


def form_id(page: str) -> str | None:
    """The id of the register's form on its page, which a list asked for names."""
    found = _FORM_ID.search(page)
    return found[1] if found else None


def list_path(form: str) -> str:
    """The first page of the list of every commitment: the form of *form_id* sent as it is."""
    return f"{LIST_PATH}?dlgid={form}&_charset_=utf-8&u=%E2%9C%93&m=1"


def listed(page: str) -> tuple[list[ListedCommitment], str | None]:
    """The commitments a page of the list names, and the path of its next page (None on the
    last)."""
    entries = [
        ListedCommitment(
            path=html_lib.unescape(path),
            number=number,
            made_on=dutch_day(html_text(day)),
            status=collapse_ws(status),
        )
        for path, day, number, status in _ENTRY.findall(page)
    ]
    following = _NEXT.search(page)
    if not following:
        return entries, None
    return entries, html_lib.unescape(following[1]).split("#")[0]


def _lines(cell: str) -> list[str]:
    """The lines of a cell (``<br />`` between them), as plain text."""
    lines = (html_text(line) for line in re.split(r"<br\s*/?>", cell))
    return [line for line in lines if line]


def _offices(cell: str) -> list[str]:
    """The offices a cell names, without the years the Kamer adds to a later name."""
    return [_PERIOD.sub("", line) for line in _lines(cell)]


def _documents(cell: str) -> tuple[list[str], list[str]]:
    """The Kamerstukken a cell names, and the dossier labels of those with a number."""
    names = [html_text(label) for _, label in _LINK.findall(cell)] or _lines(cell)
    dossiers: list[str] = []
    for name in names:
        number = _DOSSIER.search(name)
        label = ek_dossier_label(number[1]) if number else None
        if label and label not in dossiers:
            dossiers.append(label)
    return names, dossiers


def _passage(page: str) -> tuple[str | None, list[Speaker]]:
    """The citation of the passage quoted and who spoke for the government in it, each
    once, in order."""
    found = _PASSAGE.search(page)
    if not found:
        return None, []
    citation = _CITATION.search(found[0])
    speakers: list[Speaker] = []
    for function, name, rest in _SPEAKER.findall(found[0]):
        speaker = Speaker(function.capitalize(), html_text(name + rest))
        if speaker.name and speaker not in speakers:
            speakers.append(speaker)
    return (html_text(citation[1]) or None) if citation else None, speakers


def commitment_page(page: str) -> CommitmentPage | None:
    """The commitment the page is of; None for a page without its number."""
    rows = {html_text(name).lower(): cell for name, cell in _ROW.findall(page)}
    number = html_text(rows.get("nummer", ""))
    if not re.fullmatch(r"T\d+", number):
        return None
    text = _TEXT.search(page)
    former = _offices(rows.get("voormalige verantwoordelijke(n)", ""))
    now = _offices(rows.get("huidige verantwoordelijke(n)", ""))
    documents, dossiers = _documents(rows.get("kamerstukken", ""))
    citation, speakers = _passage(page)
    return CommitmentPage(
        number=number,
        text=html_text(text[1]) or None if text else None,
        status=html_text(rows.get("status", "")) or None,
        made_on=dutch_day(html_text(rows.get("datum toezegging", ""))),
        deadline=dutch_day(html_text(rows.get("deadline", ""))),
        responsible=former or _offices(rows.get("verantwoordelijke(n)", "")),
        responsible_now=now if former else [],
        former_number=html_text(rows.get("oorspronkelijke nummer", "")) or None,
        members=_lines(rows.get("kamerleden", "")),
        committees=_lines(rows.get("commissie", "")),
        activity_kind=html_text(rows.get("soort activiteit", "")) or None,
        category=html_text(rows.get("categorie", "")) or None,
        subjects=_lines(rows.get("onderwerpen", "")),
        documents=documents,
        dossiers=dossiers,
        citation=citation,
        speakers=speakers,
    )


def maker(page: CommitmentPage) -> str | None:
    """The name of who made the commitment, as the passage quoted writes it: the first who
    spoke for the government in an office of the kind of the first one responsible (a
    minister, a state secretary); None when no one did, or none is responsible."""
    if not page.responsible:
        return None
    kind = post_kind(page.responsible[0])
    return next((s.name for s in page.speakers if post_kind(s.function) == kind), None)
