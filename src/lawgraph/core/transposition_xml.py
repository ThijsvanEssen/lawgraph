"""The transposition tables in the XML of a Kamerstuk: a table of the memorie van toelichting
(or of its bijlage) that places the articles of an old law in a new one.

A ``<table>`` is read in one of these layouts:

* a column of the law the paper proposes (the new law) beside a column of the old law. The
  proposed law's column says so: ``Wetsvoorstel``, ``Wetsvoorstel Energiewet``, ``Plaats
  wetsvoorstel``, ``Artikel wetsvoorstel Waarborgwet``, a name with a year still open
  (``Mediawet 20..``) or ``nieuw``. The old law's column is the other one whose cells read as
  articles (not ``Onderwerp``, ``Opmerking``); it names the old law (``Elektriciteitswet
  1998``, ``Huidige Mediawet``, ``Artikel Waarborgwet 1986``), or the title does (``Tabel 3.
  Boswet`` over ``Onderwerp | Plaats | Plaats wetsvoorstel``, ``Monumentenwet 1988`` over
  ``oud | nieuw | opmerking``). The proposed law is named by its column or by the dossier's
  title (``… (Wet dieren)``), or else it is the law of the dossier
  (``XmlTable.proposed``). A head may hold such pairs side by side (``Wetsvoorstel | Wet GBA
  | Wetsvoorstel | Wet GBA``), each one a table, either way round. Such a table is one
  without a word that names it: the Wet dieren's tables (kst-31389-3) stand under no heading.

* a head row with a column per law, ``Artikel <law>``, and often the old law in its title
  (``h. Transponeringstabel Waterwet``); which of the two is the new law the caller decides
  from the graph (``XmlTable.rows``). The Omgevingswet's tables (kst-34986-3, Bijlage 2) are
  such::

      Onderwerp | Artikel Wabo | Artikel Omgevingswet | Toelichting

* two columns under the heading ``Huidig naar nieuw``: the current and the new text of one
  law, the old in the first column. The new Wetboek van Strafvordering's second table
  (kst-36636-3) is such; its half ``Nieuw naar huidig`` is not read.

The last two only under a title, a heading or a ``<tussenkop>`` right before it that names a
transposition or concordance table (``TABLE_WORDS``); such a table in no layout places
nothing and says so. A head with more than two columns of articles that are no pairs is none:
which two are the old and the new law is not read from it. The Wet voortgezet onderwijs 2020
has a column per law, each with its own column of leden (``artikel WVO | lid/onderdeel |
artikel WVO-BES | lid/onderdeel | artikel WVO 20xx | …``), the Invoeringsbesluit Omgevingswet
the old regulation's article and its places in two new ones (``Artikel | Artikel Omgevingswet
| Artikel AMvB``). Columns are those of the ``<colspec>``: an entry without a ``colname``
stands in the next column not taken by a cell above it (``morerows``).

Each cell holds one or more references as the source writes them (``8.2.26, vierde lid``,
``2.1 en 2.2``, ``5.8 t/m 5.14``, ``2.31, eerste lid, onder a``, ``art. 1.1, lid 1``), apart
by a comma, ``en``, a semicolon, a paragraph of their own or a word that joins them (``16.50
in samenhang met 16.40``, ``5.33 jo. 16.15``, ``3.89 i.c.m. 3.10``, ``5.1 resp. 5.3``); in
the new law's cell also a division (``afdeling 15.2``, ``bijlage A``), a place that is no
article. A law named after the last reference of a cell of the new law is the law of that one
(``12 en 47b WEC``, ``afdeling 3.5 Awb``, ``16.52, eerste lid, Omgevingswet``, with a note
after it: ``art. 1a WED (door artikel 2.46 IwOw)``: ``Place.law``); the word ``besluit``
there is none: the references are of the new law, worked out in an AMvB under them (``20,
derde lid, besluit``);
a cell in prose gives the references after ``komt/keert … terug in`` (``Komt inhoudelijk
gewijzigd terug in artikel 10.23.``). A cell of the new law that does not read as such is a
place that is no article when it has no figure (``–``, ``niet overgenomen``), and does not
read otherwise (``2.21,eerste lid, onder b, … 16.89. 20.7``). A cell of the new law in parts
(``Eerste lid: 3.1 Tweede lid: 3.2``, ``Onder a: 1.1 Onder b-d: 6.1``) places each part of the
old article on its own. A row whose old cell names only a part (``onder a``, ``Tweede lid``,
``Lid 1``) continues the reference above it, and its new cell, when it names only a part too,
the new reference above; in a table of a proposed law also when the row above has no place
(``Artikel 1 |`` over ``Lid 1 | 1.1, lid 1``). A cell over more rows (``morerows``) holds for
each. An old cell that is no reference (``§ 2.3``) is a row of that text: ``core.succession``
reads it as the articles of that division of the old law, else as an article the old law does
not have. Nothing is corrected: ``core.succession`` checks every row against the text of the
laws.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace

from lawgraph.core.qualifiers import ORDINAL, parse_qualifier
from lawgraph.core.succession import Place, SourceRow
from lawgraph.core.xml import collapse_ws, local_name

# The words that name such a table, in a title or a heading.
TABLE_WORDS = (
    "transponeringstabel",
    "transponeringstabellen",
    "concordantietabel",
    "concordantietabellen",
)
_NAMES_A_TABLE = re.compile(
    r"(?:transponerings|concordantie)tabel(?:len)?", re.IGNORECASE
)
# A title "h. Transponeringstabel Waterwet": the law after the words.
_TITLE_LAW = re.compile(
    r"^(?:[a-z]\.\s+)?(?:transponerings|concordantie)tabel(?:len)?\s+(?P<law>.+)$",
    re.IGNORECASE,
)
# A title's label and the words that name a table before its law: "h. Transponeringstabel
# Waterwet", "Tabel 3. Boswet".
_TITLE_LABEL = re.compile(
    r"^(?:[a-z]\.\s+|tabel\s+\d+[a-z]?\.?\s+)?"
    r"(?:(?:transponerings|concordantie)tabel(?:len)?\s*)?",
    re.IGNORECASE,
)
_COLUMN_LAW = re.compile(r"^artikel(?:en)?\s+(?P<law>.+)$", re.IGNORECASE)
# A column of articles, of a law it names or not ("Artikel", "artikel WVO 20xx").
_ARTICLE_COLUMN = re.compile(r"^artikel(?:en)?\b", re.IGNORECASE)
_OLD_TO_NEW = re.compile(r"^huidig\s+naar\s+nieuw\b", re.IGNORECASE)
_NEW_TO_OLD = re.compile(r"^nieuw\s+naar\s+huidig\b", re.IGNORECASE)
# A year a proposed law's name leaves open: "Mediawet 20..", "WVO 20xx".
PLACEHOLDER_YEAR = re.compile(r"\b20(?:\.\.|xx)(?!\w)", re.IGNORECASE)
_PROPOSAL_WORD = re.compile(r"\b(?:wets)?voorstel\b", re.IGNORECASE)
# The column of the law the paper proposes.
_PROPOSAL = re.compile(
    rf"{_PROPOSAL_WORD.pattern}|{PLACEHOLDER_YEAR.pattern}|^nieuw$", re.IGNORECASE
)
# The words of a head before the law it names: "Huidige Mediawet", "bepalingen Waterleidingwet".
_HEAD_WORDS = re.compile(r"^(?:artikel(?:en)?|bepalingen|huidige?)\s+", re.IGNORECASE)
# The law a dossier's title names at its end: "Regels omtrent dieren (Wet dieren)".
_DOSSIER_LAW = re.compile(r"\((?P<law>[^()]+)\)\s*$")

# ── a cell ───────────────────────────────────────────────────────────────────

_NUMBER = r"\d+[a-z]*(?:[.:]\d+[a-z]*)*"
_ORDINALS = rf"{ORDINAL}(?:\s*(?:,|\ben\b|\btot en met\b|\bt/m\b)\s*{ORDINAL})*"
# "lid 1 en 2", "leden 1, 2 en 3": after "lid" a comma starts the next reference ("7, lid 5, 22").
_LID_NUMBER = r"\d+[a-z]?"
_LID_JOIN = r"\s*(?:\ben\b|\bt/m\b|\btot en met\b|[–-])\s*"
# An onderdeel ("a", "2°"); "en" and "of" join them.
_SUB = r"(?!(?:en|of)\b)(?:[a-z]{1,2}|\d{1,2}\s*°)(?![\w°])"
_QUALIFIER = (
    rf"(?:{_ORDINALS}\s+(?:lid|leden)\b"
    rf"|lid\s+{_LID_NUMBER}(?:{_LID_JOIN}{_LID_NUMBER})*(?![\w.:])"
    rf"|leden\s+{_LID_NUMBER}(?:(?:{_LID_JOIN}|\s*,\s*){_LID_NUMBER})*(?![\w.:])"
    rf"|{_ORDINALS}\s+(?:vol)?zin(?:nen)?\b"
    rf"|(?:aanhef(?:\s+en)?\s+)?(?:onder(?:deel|delen)?|sub)\s+{_SUB}"
    rf"(?:\s*(?:,|\ben\b|\bt/m\b|\btot en met\b)\s*{_SUB})*"
    r"|aanhef\b)"
)
_QUALIFIERS = rf"(?:\s*,?\s*(?:\ben\s+)?{_QUALIFIER})*"
_REFERENCE = re.compile(
    rf"(?:(?:artikel(?:en)?|artt?\.?)\s*)?(?P<number>{_NUMBER})(?P<qualifier>{_QUALIFIERS})",
    re.IGNORECASE,
)
# A cell that names only a part ("onder a", "Tweede lid"): of the reference above it.
_PART_ONLY = re.compile(rf"\s*,?\s*{_QUALIFIER}{_QUALIFIERS}", re.IGNORECASE)
_RUN = re.compile(rf"\s*(?:t/m|tot en met|[–-])\s*(?P<last>{_NUMBER})", re.IGNORECASE)
# Between two references: a comma, "en", a semicolon, or a word that joins them ("16.50 in
# samenhang met 16.40", "5.33 jo. 16.15", "3.89 i.c.m. 3.10", "5.1 resp. 5.3").
_SEPARATOR = re.compile(
    r"\s*[,;]?\s*(?:(?:\ben\b|\bin\s+samenhang\s+met\b|\bjo\b\.?|\bjuncto\b"
    r"|\bi\.c\.m\.|\bresp\.)\s*)?",
    re.IGNORECASE,
)
# A cell whose references name a law at their end ("16.52, eerste lid, Omgevingswet",
# "afdeling 3.5 Awb", "16.75 (Aanvullingswet grondeigendom Omgevingswet)", "10.25 van de
# Omgevingswet"), with a note after it ("5.20, derde lid, Awb (nieuw)", "art. 1a WED (door
# artikel 2.46 IwOw)"): the references, the law and the note.
_LAW_AT_END = re.compile(
    r"^(?P<references>.*?\d[^\s,]*(?:,\s*[^,]*?)*?)\s*,?\s+(?:van\s+(?:de|het)\s+)?"
    r"\(?(?P<law>[^\W\d][^\d,;()]*?)\)?(?:\s*(?P<note>\((?:nieuw|door\s[^()]*)\)))?"
    r"\s*\.?$",
    re.IGNORECASE,
)
# The word after the references of the new law that says an AMvB under them works them out
# ("20, derde lid, besluit": kst-36440-3): no law of its own.
_UNDER_THEM = re.compile(r"besluit", re.IGNORECASE)
# A word that names a part of an article, never a law.
_PART_WORDS = re.compile(
    rf"\b(?:lid|leden|onder(?:deel|delen)?|aanhef|(?:vol)?zin(?:nen)?|{ORDINAL})\b",
    re.IGNORECASE,
)
# The words of a cell in prose before its references: "Komt inhoudelijk gewijzigd terug in
# artikel 10.23.", "Komt terug in de Omgevingswet, in artikel 10.1".
_PROSE = re.compile(
    r"^(?:komt|keert)\b[^\d]*?\bterug\s+in\s+(?:(?:de|het)\s+[^,\d]+,\s*in\s+)?"
    r"(?:de\s+)?",
    re.IGNORECASE,
)
# A division of a law, or a list of them: "afdeling 15.2", "afdelingen 16.3, 16.8 en 23.1",
# "§ 2.5.1", "bijlage A bij 1.1", "hoofdstuk 13 en 15": a place that is no article.
_DIVISIONS = re.compile(
    rf"(?:boek|hoofdstuk(?:ken)?|afdeling(?:en)?|§|paragra(?:af|fen)|titel|bijlage)\s*"
    rf"(?:[A-Z]\b|{_NUMBER})?(?:\s+bij\s+{_NUMBER})?"
    rf"(?:\s*(?:,|\ben\b)\s*(?:§\s*)?{_NUMBER}(?![\w.:]))*",
    re.IGNORECASE,
)
# The label of a part of a cell in parts: "Eerste lid:", "Tweede en derde lid:", "Onder b-d:".
_PART_LABEL = re.compile(
    rf"(?:(?<=\s)|^)(?P<part>(?:{_ORDINALS}\s+(?:lid|leden)"
    rf"|(?:aanhef(?:\s+en)?\s+)?onder(?:deel|delen)?\s+{_SUB}"
    rf"(?:\s*(?:,|\ben\b|\bt/m\b|\btot en met\b|[–-])\s*{_SUB})*"
    r"|aanhef))\s*:",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Reference:
    """An article or a run of articles with the part the source names, as it writes it; or
    a division (``article`` None)."""

    text: str  # "8.2.26, vierde lid"
    article: str | None  # "8.2.26"
    part: str = ""  # "vierde lid"; empty for the whole article
    leden: tuple[str, ...] = ()
    through: str | None = None  # "5.14" of "5.8 t/m 5.14"


def references(text: str, *, divisions: bool = False) -> list[Reference] | None:
    """The references of a cell, in its order; with *divisions* a division of the law is
    one too. None when the cell does not read as references."""
    text = collapse_ws(text)
    found: list[Reference] = []
    position = 0
    while position < len(text):
        if found:
            separator = _SEPARATOR.match(text, position)
            if separator is None or separator.end() == position:
                return None
            position = separator.end()
        reference = _reference(text, position, divisions)
        if reference is None:
            return None
        found.append(reference[0])
        position = reference[1]
    return found or None


def _reference(
    text: str, position: int, divisions: bool
) -> tuple[Reference, int] | None:
    """The reference at *position* of *text* and where it ends."""
    match = _REFERENCE.match(text, position)
    if match is None:
        division = _DIVISIONS.match(text, position) if divisions else None
        if division is None:
            return None
        return Reference(division[0], None), division.end()
    end = match.end()
    run = _RUN.match(text, end)
    if run is not None:
        end = run.end()
    part = _part(match["qualifier"])
    return (
        Reference(
            text[position:end],
            match["number"],
            part,
            () if run else parse_qualifier(part).leden,
            run["last"] if run else None,
        ),
        end,
    )


def _part(qualifier: str) -> str:
    return qualifier.strip().lstrip(",").strip()


def _continued(base: Reference, text: str) -> Reference:
    """The reference of a cell that names only a part (*text*) under the cell of *base*."""
    part = ", ".join(p for p in (base.part, _part(text)) if p)
    return Reference(
        f"{base.text}, {_part(text)}", base.article, part, parse_qualifier(part).leden
    )


def places(text: str) -> list[Place]:
    """The places a cell of the new law gives: its references (an article, a run of them,
    a division), or the one place that is no article (no figure in it) or does not read."""
    text = collapse_ws(text)
    found = references(text, divisions=True)
    if found is not None:
        return [_place(r) for r in found]
    if not text:
        return []
    prose = _PROSE.sub("", text).rstrip(".")
    if prose != text and (found := references(prose, divisions=True)):
        return [_place(r) for r in found]
    for cell in dict.fromkeys((text, prose)):
        if read := _with_law(cell):
            return read
    return [Place(text, None, (), readable=not re.search(r"\d", text))]


def _with_law(text: str) -> list[Place] | None:
    """The places of a cell whose last reference names a law at its end ("12 en 47b WEC":
    12 of the new law, 47b of the WEC), that one of the law (``Place.law`` as written, its
    text with the law and its note after it); None for any other cell. A cell of only a
    part ("Tweede lid") names no law. The word ``besluit`` after the references names none
    either: they are of the new law, worked out in an AMvB under them (the last one's text
    as the cell ends)."""
    match = _LAW_AT_END.fullmatch(text)
    if match is None:
        return None
    law = match["law"].strip()
    under = _UNDER_THEM.fullmatch(law) is not None and not match["note"]
    if not (under or _is_law(law)):
        return None
    found = references(match["references"].rstrip(" ,"), divisions=True)
    if found is None:
        return None
    *first, last = [_place(r) for r in found]
    if under:
        return [*first, replace(last, text=last.text + text[match.end("references") :])]
    note = f" {match['note']}" if match["note"] else ""
    return [*first, replace(last, text=f"{last.text} {law}{note}", law=law)]


def _is_law(text: str) -> bool:
    """Whether *text* can be the name of a law: it starts with a capital ("Awb", "Wet op de
    expertisecentra") and names no part of an article ("eerste lid", "onder a")."""
    return text[:1].isupper() and not _PART_WORDS.search(text)


def _place(reference: Reference) -> Place:
    return Place(
        reference.text, reference.article, reference.leden, through=reference.through
    )


def cell_parts(text: str) -> list[tuple[str, str]] | None:
    """The parts of a cell of the new law in parts, ``(part of the old article, its
    places)``: ``Eerste lid: 3.1 Tweede lid: 3.2`` is ``[("Eerste lid", "3.1"), ("Tweede
    lid", "3.2")]``; None for a cell that does not start with the label of a part."""
    text = collapse_ws(text)
    labels = list(_PART_LABEL.finditer(text))
    if not labels or labels[0].start() != 0:
        return None
    ends = [label.start() for label in labels[1:]] + [len(text)]
    return [
        (label["part"], text[label.end() : end].strip())
        for label, end in zip(labels, ends, strict=True)
    ]


# ── a table ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class XmlTable:
    """A transposition table of a Kamerstuk, or why it is not read (``problem``).

    ``columns``: the laws the head names over its two columns of articles, in their order
    (``("Wabo", "Omgevingswet")``); None for the layout ``Huidig naar nieuw``, whose first
    column is the current text of a law and the second the new one. ``title_law``: the law
    the title names (``Waterwet``). ``cells``: per row of the body, the text of the two
    columns of articles and where the row is. Which column is the old law is not read here:
    ``rows`` reads them in the order it is told.

    ``proposed``: of a table of the law the paper proposes, the names that law may go by, to
    try in order (its column's ``Energiewet``, the dossier's ``Wet dieren``; none when
    neither names it: the law of the dossier); its ``columns`` are the old law's column and
    the proposed law's, and its ``cells`` run from the old law to the new one. None for a
    table whose head names both laws."""

    name: str
    source: str
    columns: tuple[str, str] | None = None
    title_law: str | None = None
    cells: tuple[tuple[str, str, str], ...] = ()
    problem: str | None = None
    proposed: tuple[str, ...] | None = None

    def rows(self, *, reverse: bool = False) -> tuple[SourceRow, ...]:
        """Each place of each row: from the first column to the second, or the other way."""
        reader = _RowReader(self.source)
        for first, second, where in self.cells:
            old, new = (second, first) if reverse else (first, second)
            reader.read(old, new, where)
        return tuple(reader.rows)


def read_tables(xml: str, source: str) -> list[XmlTable]:
    """The transposition tables of the Kamerstuk XML *xml* (identifier *source*), in order;
    raises ``ET.ParseError`` for XML that does not read."""
    root = ET.fromstring(xml.lstrip("\ufeff"))
    tables: list[XmlTable] = []
    _walk(root, (), tables, _Document(source, _dossier_law(root)))
    return tables


@dataclass(frozen=True)
class _Document:
    source: str
    dossier_law: str | None  # the law the dossier's title names


def _dossier_law(root: ET.Element) -> str | None:
    """The law the title of the paper's dossier names at its end (``<dossier><titel>``, in
    an older paper ``<onderw><naam>``)."""
    for parent, child in (("dossier", "titel"), ("onderw", "naam")):
        for element in root.iter(parent):
            match = _DOSSIER_LAW.search(_text(element.find(child)))
            if match:
                return match["law"].strip()
    return None


def _walk(
    element: ET.Element,
    headings: tuple[str, ...],
    tables: list[XmlTable],
    document: _Document,
) -> None:
    """Every table under *element*, with the headings it stands under."""
    own = headings
    before = ""  # the tussenkop right before a table
    for child in element:
        name = local_name(child.tag)
        if name == "kop":
            own = (*headings, _text(child))
        elif name in ("tussenkop", "tuskop"):
            before = _text(child)
            continue
        elif name == "table":
            tables += _tables(child, (*own, before), document)
        else:
            _walk(child, own, tables, document)
        before = ""


def _tables(
    element: ET.Element, headings: tuple[str, ...], document: _Document
) -> list[XmlTable]:
    """The tables of *element*: a table of a proposed law per pair of its columns, or the
    one table its title or *headings* name (none: no table)."""
    title = _text(element.find("title"))
    named = any(_NAMES_A_TABLE.search(h) for h in (title, *headings) if h)
    name = title or " – ".join(h for h in headings if h)
    head = _rows(element, "thead", "")
    body = _rows(element, "tbody", " ")
    columns = _columns(element, head)
    pairs = _proposal_pairs(columns, body)
    if pairs:
        return [
            _proposal_table(
                title or " | ".join(columns[c] for c in columns if c in (old, new)),
                document,
                title,
                (columns[old], columns[new]),
                _cells(body, old, new, alone=True),
            )
            for old, new in pairs
        ]
    if not named:
        return []
    entries = [entry for row in head for entry in row.items()]
    table = _table(name, document.source, title, headings, entries, body)
    return [] if table is None else [table]


def _proposal_table(
    name: str,
    document: _Document,
    title: str,
    heads: tuple[str, str],
    cells: tuple[tuple[str, str, str], ...],
) -> XmlTable:
    """The table of a proposed law of the columns *heads* (the old law's, the proposed
    law's) and their *cells*."""
    old, new = heads
    names = (proposed_name(new), document.dossier_law)
    return XmlTable(
        name,
        document.source,
        (_HEAD_WORDS.sub("", old), new),
        title_law(title),
        cells,
        proposed=tuple(dict.fromkeys(n for n in names if n)),
    )


def proposed_name(head: str) -> str | None:
    """The name a column of a proposed law gives it: ``Wetsvoorstel Energiewet`` and
    ``Artikel wetsvoorstel Energiewet`` ``Energiewet``, ``Mediawet (20..)`` itself; none for
    ``Wetsvoorstel``, ``Plaats wetsvoorstel`` and ``nieuw``. A remark in brackets or after a
    comma is no part of it (``Wetsvoorstel (tenzij anders bepaald)``)."""
    head = re.sub(r"\((?!20(?:\.\.|xx)\))[^()]*\)", "", head, flags=re.IGNORECASE)
    head = head.split(",")[0]
    word = _PROPOSAL_WORD.search(head)
    name = _HEAD_WORDS.sub("", head[word.end() :] if word else head).strip()
    return name if name and name.lower() != "nieuw" else None


def title_law(title: str) -> str | None:
    """The law a title names: what is left after its label and the words that name a
    table (``h. Transponeringstabel Waterwet``, ``Tabel 3. Boswet``, ``Monumentenwet
    1988``)."""
    return _TITLE_LABEL.sub("", title).strip() or None


def _table(
    name: str,
    source: str,
    title: str,
    headings: tuple[str, ...],
    head: list[tuple[str, str]],
    body: list[dict[str, str]],
) -> XmlTable | None:
    """The table a heading names, in a layout with a column per law or ``Huidig naar
    nieuw``, or why it is not read; None for the half ``Nieuw naar huidig``."""
    columns = [
        (column, match["law"])
        for column, text in head
        if (match := _COLUMN_LAW.match(text))
    ]
    articles = [text for _, text in head if _ARTICLE_COLUMN.match(text)]
    if len(articles) > 2:
        return XmlTable(
            name,
            source,
            problem=f"columns not recognised: {len(articles)} of articles "
            f"({' | '.join(articles)})",
        )
    if len(columns) >= 2:
        titled = _TITLE_LAW.match(title)
        return XmlTable(
            name,
            source,
            (columns[0][1], columns[1][1]),
            titled["law"] if titled else None,
            _cells(body, columns[0][0], columns[1][0]),
        )
    direction = headings[-1] if headings else ""
    if _NEW_TO_OLD.match(direction):
        return None
    if _OLD_TO_NEW.match(direction):
        return XmlTable(name, source, cells=_cells(body, "col1", "col2"))
    return XmlTable(name, source, problem="no column of an old and of a new law")


def _rows(table: ET.Element, part: str, separator: str) -> list[dict[str, str]]:
    """Per row of the table's *part* (``thead``, ``tbody``), the text of each of its
    columns, the paragraphs of a cell apart by *separator*. A cell over more rows
    (``morerows``) is in each; an entry over more columns (a heading of the table) is in
    none. An entry without a ``colname`` stands in the next column no cell above takes."""
    names = _names(table)
    found: list[dict[str, str]] = []
    above: dict[str, tuple[str, int]] = {}
    for row in (r for section in table.iter(part) for r in section.findall("row")):
        cells = {column: text for column, (text, _) in above.items()}
        taken = set(cells)
        above = {c: (t, n - 1) for c, (t, n) in above.items() if n > 1}
        position = 0
        for entry in row.findall("entry"):
            first, last = entry.get("namest"), entry.get("nameend")
            if first and last and first != last:
                position = _after(names, last, position)
                continue
            column = entry.get("colname") or first
            if column is None:
                while position < len(names) and names[position] in taken:
                    position += 1
                column = names[position] if position < len(names) else ""
            position = _after(names, column, position)
            cells[column] = text = _text(entry, separator)
            more = int(entry.get("morerows") or 0)
            if more > 0:
                above[column] = (text, more)
        found.append(cells)
    return found


def _after(names: list[str], column: str, position: int) -> int:
    """The position after *column* of *names*; after *position* for one not named."""
    return names.index(column) + 1 if column in names else position + 1


def _columns(table: ET.Element, head: list[dict[str, str]]) -> dict[str, str]:
    """The text the head gives each column, in the order of the table: of its last row that
    names it (``A | B`` in a row above ``Artikel wetsvoorstel | Artikel Waarborgwet 1986 |
    …`` groups columns)."""
    columns: dict[str, str] = {}
    for row in head:
        columns |= {column: text for column, text in row.items() if text}
    names = _names(table)
    return dict(
        sorted(
            columns.items(),
            key=lambda item: names.index(item[0]) if item[0] in names else len(names),
        )
    )


def _names(table: ET.Element) -> list[str]:
    """The names of the columns of *table* (``<colspec>``), in order."""
    return [
        spec.get("colname") or f"col{number}"
        for number, spec in enumerate(table.iter("colspec"), start=1)
    ]


def _proposal_pairs(
    columns: dict[str, str], body: list[dict[str, str]]
) -> list[tuple[str, str]] | None:
    """The pairs ``(old law's column, proposed law's column)`` of a head with a column of a
    proposed law (``_PROPOSAL``) beside each column whose cells read as articles; None for
    any other head."""
    proposed = [c for c, text in columns.items() if _PROPOSAL.search(text)]
    if not proposed:
        return None
    old = [
        c
        for c in columns
        if c not in proposed and _of_articles([row.get(c, "") for row in body])
    ]
    order = [c for c in columns if c in proposed or c in old]
    if len(old) != len(proposed):
        return None
    pairs = []
    for first, second in zip(order[::2], order[1::2], strict=True):
        if (first in proposed) == (second in proposed):
            return None
        pairs.append((second, first) if first in proposed else (first, second))
    return pairs


def _of_articles(texts: list[str]) -> bool:
    """Whether a column holds articles: at least half its cells with a figure read as
    references, or as a part of the one above (``Lid 1``); one without (``–``, ``vervalt``)
    tells nothing."""
    filled = [text for text in texts if re.search(r"\d", text)]
    read = [t for t in filled if references(t) is not None or _is_part(t)]
    return bool(filled) and 2 * len(read) >= len(filled)


def _cells(
    body: list[dict[str, str]], first: str, second: str, *, alone: bool = False
) -> tuple[tuple[str, str, str], ...]:
    """The text of the columns *first* and *second* of each row of the *body* that has
    both, with where it is; with *alone* also of a row that has only the first."""
    return tuple(
        (cells[first], cells.get(second, ""), f"rij {number}")
        for number, cells in enumerate(body, start=1)
        if cells.get(first) and (alone or cells.get(second))
    )


class _RowReader:
    """The rows of a table in order: a row whose old cell names only a part ("onder a")
    continues the reference above it, in both columns."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.rows: list[SourceRow] = []
        # the last reference of an old and of a new cell of its own
        self._old: Reference | None = None
        self._new: Reference | None = None

    def read(self, old: str, new: str, where: str) -> None:
        if not collapse_ws(new):  # a row without a place: one below may continue it
            self._olds(old)
            return
        olds = self._olds(old)
        parts = cell_parts(new)
        if parts is not None:
            for base in olds or [Reference(collapse_ws(old), None)]:
                for part, text in parts:
                    self._add(_continued(base, part), places(text), where)
            return
        continued = olds is not None and self._old is not None and _is_part(old)
        if continued and self._new is not None and _is_part(new):
            news = [_place(_continued(self._new, new))]
        elif _is_part(new):
            news = [Place(collapse_ws(new), None, (), readable=False)]
        else:
            news = places(new)
            if not continued:
                found = references(new)
                self._new = found[-1] if found else None
        if olds is None:
            if not re.search(r"\w", old):  # "–": no article of the old law
                return
            olds = [Reference(collapse_ws(old), collapse_ws(old))]
        for reference in olds:
            self._add(reference, news, where)

    def _add(self, old: Reference, news: list[Place], where: str) -> None:
        self.rows += [
            SourceRow(
                old.article or old.text, old.part, n, where, self.source, old.through
            )
            for n in news
        ]

    def _olds(self, old: str) -> list[Reference] | None:
        if _is_part(old):
            return [_continued(self._old, old)] if self._old is not None else None
        found = references(old)
        self._old = found[-1] if found else None
        return found


def _is_part(text: str) -> bool:
    return bool(_PART_ONLY.fullmatch(collapse_ws(text)))


def _text(element: ET.Element | None, separator: str = "") -> str:
    """The text of *element*, its paragraphs (``<al>``) apart by *separator*."""
    if element is None:
        return ""
    paragraphs = element.findall("al")
    if paragraphs and separator:
        return collapse_ws(separator.join("".join(p.itertext()) for p in paragraphs))
    return collapse_ws(" ".join(element.itertext()))
