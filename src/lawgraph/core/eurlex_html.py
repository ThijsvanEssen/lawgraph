"""Parse the title and the articles of an EU act from its CELLAR HTML — pure, no I/O.

CELLAR serves an act in one of two HTML formats, and the structure is read from the markup
where there is markup:

* the Official Journal format (acts from about 2004): the title is the ``p.oj-doc-ti``
  paragraphs of ``div.eli-main-title``. Every article is a ``div.eli-subdivision`` with its
  number in ``p.oj-ti-art`` ("Artikel 1") and its heading in ``p.oj-sti-art`` ("Onderwerp en
  toepassingsgebied"). A lid is a paragraph that starts with its number ("1.   Deze
  verordening bevat:"); a point is a table row of two cells, the marker ("a)", "1)", "i)",
  "—") and its text, and a point inside a point is a table inside that text cell. The
  divisions an article stands in are the ``div`` elements around it that start with a
  ``p.oj-ti-section-1`` label ("HOOFDSTUK III", "Afdeling 1"), with their
  ``p.oj-ti-section-2`` title;
* the old format (older acts): the title is the ``DC.description`` of the page; the text is
  flat ``<p>`` paragraphs. An article starts at a paragraph that is only "Artikel N"; a short
  paragraph right after it without closing punctuation is its heading; leden and points are
  read from the marker a paragraph starts with. How deep a point sits follows from the kind
  of its marker (letters, digits, roman numerals, dashes): a kind not yet open nests inside
  the point before it, a kind that is open returns to that level. An article ends at the
  next one, at a division heading or at the closing formula ("Gedaan te Brussel, …").
  A division heading is its label with the title after it ("HOOFDSTUK I ALGEMENE
  BEPALINGEN", "Afdeling 1: Vestiging") or in the next paragraph; a kind of division that
  is open ends there and the divisions inside it too, another kind nests in the open ones.
  A heading in capitals without a label right before an article ("SLOTBEPALINGEN") stands
  at the top level.

A division is a ``Crumb`` as for BWB: its ``type`` is the first word of the label in lower
case ("hoofdstuk"), its label is written "Hoofdstuk III", its title as printed.

The text of an article is built as for BWB (``core.bwb_xml.TextBuilder``): a lid as
``1. text``, a point on a line of its own with its marker (``a) text``), every other
paragraph on a line of its own; no empty lines, no heading. Its parts are
``core.bwb_xml.ArticlePart`` spans of that text with the same ids (``lid-1``,
``lid-1-aanhef``, ``lid-1-onder-a``, ``onder-a``, ``…-onder-a-onder-i``, ``_<n>`` for a
dash).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser

from lawgraph.core.bwb_xml import (
    PART_LID,
    PART_ONDERDEEL,
    ArticlePart,
    Crumb,
    TextBuilder,
)
from lawgraph.core.xml import collapse_ws

_TITLE_CLASSES = frozenset({"oj-ti-art", "ti-art"})
_HEADING_CLASSES = frozenset({"oj-sti-art", "sti-art"})
_DOC_TITLE_CLASSES = frozenset({"oj-doc-ti", "doc-ti"})
_DIVISION_LABEL_CLASSES = frozenset({"oj-ti-section-1", "ti-section-1"})
_DIVISION_TITLE_CLASSES = frozenset({"oj-ti-section-2", "ti-section-2"})
# The description of a page of the old format is the title of the act.
_DESCRIPTION_META = "DC.description"

_ARTICLE_RE = re.compile(r"(?:Artikel|Article)\s+(\d+[a-z]*)", re.IGNORECASE)
# A lid: "1.   Deze verordening bevat:"; old acts also print "1 . Het recht".
_LID_RE = re.compile(r"(\d+[a-z]?) ?\.\s+(\S.*)", re.DOTALL)
# The marker of a point in a cell of its own: "a)", "(a)", "1)", "1.", "iv)", "—"; in the
# text an amendment quotes it opens with a quotation mark ("„r)").
_CELL_MARKER_RE = re.compile(r"[„“\"]?(?:\(?(?:\d+[a-z]?|[a-z]{1,5})[.)]|[—–-])")
_MARKER_PUNCTUATION = '().„“"'
# A point in a flat paragraph: "a) text", "a ) text", "1) text", "ii) text", "- text",
# "_ text".
_FLAT_POINT_RE = re.compile(
    r"(\(?(?:\d+[a-z]?|[a-z]|[ivx]+) ?\)|[—–_-])\s+(\S.*)", re.DOTALL
)
_ROMAN_RE = re.compile(r"[ivx]+")
# The container of a lid in the Official Journal format: ``div id="004.002"``.
_LID_DIV_RE = re.compile(r"\d{3}\.(\d{3})")
# Where an article of the old format ends, other than at the next article.
_CLOSING_RE = re.compile(r"(?:Gedaan te|Done at)\b")
_DIVISION_RE = re.compile(
    r"(?:HOOFDSTUK|TITEL|AFDELING|DEEL|SECTIE|BIJLAGE|CHAPTER|TITLE|SECTION|ANNEX)\b"
)
# A division heading of the old format: its kind and number, then maybe its title. In
# capitals ("HOOFDSTUK I ALGEMENE BEPALINGEN") or with a colon ("Afdeling 1: Vestiging").
_DIVISION_LABEL_RE = re.compile(
    r"((?:onder)?afdeling|hoofdstuk|titel|deel|sectie)\s+([ivxlc]+|\d+[a-z]*)\b"
    r"\s*(:)?\s*(.*)",
    re.IGNORECASE | re.DOTALL,
)
# A heading of the old format is short and does not end like a sentence or a lead-in.
_HEADING_MAX_CHARS = 200
_SENTENCE_END = (".", ":", ";", ",")

# HTML elements without an end tag, elements whose text is not law text, and elements
# before which an open <p> ends.
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "wbr"}
)
_SKIP_TAGS = frozenset({"head", "script", "style"})
_CLOSES_P = frozenset({"p", "div", "table", "ul", "ol", "h1", "h2", "h3", "h4", "hr"})

_MARKER_LETTER = "letter"
_MARKER_DIGIT = "digit"
_MARKER_ROMAN = "roman"
_MARKER_DASH = "dash"


@dataclass(frozen=True)
class EuArticle:
    """One article: its number ("1", "12a"), heading, text, the parts of that text and the
    divisions it stands in, outermost first."""

    number: str
    heading: str | None
    text: str
    parts: tuple[ArticlePart, ...] = ()
    breadcrumb: tuple[Crumb, ...] = ()


@dataclass(frozen=True)
class EuAct:
    """An act: its title as printed, in paragraphs ("VERORDENING (EU) 2022/868 VAN HET
    EUROPEES PARLEMENT EN DE RAAD", "van 30 mei 2022", "betreffende …"; one paragraph for
    the old format), and its articles in document order."""

    title: tuple[str, ...]
    articles: tuple[EuArticle, ...]


@dataclass(frozen=True)
class _Block:
    """A paragraph of an article, a lid or a point.

    *depth* 0 is the article (a lid when there is a *marker*), n a point at nesting n, None a
    paragraph of the old format that continues the part that is open. *marker* is the number
    of a lid ("1") or the printed marker of a point ("a)")."""

    text: str
    depth: int | None
    marker: str | None = None


class _TreeBuilder(HTMLParser):
    """Build an ElementTree of an HTML page, tolerating unclosed and stray end tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = ET.Element("html-root")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _CLOSES_P and self._stack[-1].tag == "p":
            self._stack.pop()
        element = ET.SubElement(
            self._stack[-1], tag, {name: value or "" for name, value in attrs}
        )
        if tag == "br":
            self.handle_data("\n")
        elif tag not in _VOID_TAGS:
            self._stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        parent = self._stack[-1]
        if len(parent):
            last = parent[-1]
            last.tail = (last.tail or "") + data
        else:
            parent.text = (parent.text or "") + data


def _parse_html(html: str) -> ET.Element:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def _classes(element: ET.Element) -> set[str]:
    return set((element.get("class") or "").split())


def _text(element: ET.Element) -> str:
    """The text of *element* with its whitespace collapsed."""
    return collapse_ws("".join(element.itertext()))


def parse_act(html: str) -> EuAct:
    """The title of the act and its articles, in document order; a number is taken once
    (a quoted article of an amendment with the number of an earlier one is text of the
    amending article), an article without text is left out."""
    root = _parse_html(html)
    titles = [p for p in root.iter("p") if _classes(p) & _TITLE_CLASSES]
    articles = _journal_articles(root, titles) if titles else _flat_articles(root)
    seen: set[str] = set()
    unique: list[EuArticle] = []
    for article in articles:
        if article.number in seen or not article.text:
            continue
        seen.add(article.number)
        unique.append(article)
    return EuAct(_printed_title(root), tuple(unique))


def parse_articles(html: str) -> list[EuArticle]:
    """The articles of the act (see ``parse_act``)."""
    return list(parse_act(html).articles)


def _printed_title(root: ET.Element) -> tuple[str, ...]:
    """The ``doc-ti`` paragraphs of the main title, else the description of the page."""
    main = next((e for e in root.iter() if "eli-main-title" in _classes(e)), root)
    paragraphs = tuple(
        text
        for p in main.iter("p")
        if _classes(p) & _DOC_TITLE_CLASSES and (text := _text(p))
    )
    if paragraphs:
        return paragraphs
    for meta in root.iter("meta"):
        if meta.get("name") == _DESCRIPTION_META:
            description = collapse_ws(meta.get("content"))
            return (description,) if description else ()
    return ()


def _article(
    number: str,
    heading: str | None,
    blocks: list[_Block],
    breadcrumb: tuple[Crumb, ...] = (),
) -> EuArticle:
    text, parts = _build(blocks)
    return EuArticle(number, heading, text, tuple(parts), breadcrumb)


def _crumb(label: str, title: str | None) -> Crumb:
    """A division from its printed label ("HOOFDSTUK III") and title."""
    kind, _, rest = collapse_ws(label).partition(" ")
    written = kind.capitalize() if kind.isupper() else kind
    return Crumb(
        type=kind.lower(),
        label=f"{written} {rest}".strip(),
        title=collapse_ws(title) or None,
    )


# --- The Official Journal format -----------------------------------------------------


def _journal_articles(root: ET.Element, titles: list[ET.Element]) -> list[EuArticle]:
    """An article is its title, its heading and what follows up to the next title; a title
    in a table cell is an article quoted in an amendment, not one of the act."""
    parents = {child: parent for parent in root.iter() for child in parent}
    numbered = {
        title: match[1]
        for title in titles
        if (match := _ARTICLE_RE.fullmatch(_text(title)))
        and not _in_cell(title, parents)
    }
    divisions: dict[ET.Element, Crumb | None] = {}
    articles: list[EuArticle] = []
    for title, number in numbered.items():
        siblings = list(parents[title])
        body: list[ET.Element] = []
        heading: str | None = None
        for element in siblings[siblings.index(title) + 1 :]:
            if any(node in numbered for node in element.iter()):
                break
            if heading is None and not body and _contains(element, _HEADING_CLASSES):
                heading = _heading_text(element)
                continue
            body.append(element)
        blocks: list[_Block] = []
        _add_blocks(body, 0, blocks)
        breadcrumb = _journal_breadcrumb(title, parents, divisions)
        articles.append(_article(number, heading, blocks, breadcrumb))
    return articles


def _journal_breadcrumb(
    title: ET.Element,
    parents: dict[ET.Element, ET.Element],
    divisions: dict[ET.Element, Crumb | None],
) -> tuple[Crumb, ...]:
    """The divisions around the article of *title*, outermost first; *divisions* keeps
    what an element was found to be."""
    crumbs: list[Crumb] = []
    node = parents.get(title)
    while node is not None:
        if node not in divisions:
            divisions[node] = _journal_division(node)
        if (crumb := divisions[node]) is not None:
            crumbs.append(crumb)
        node = parents.get(node)
    return tuple(reversed(crumbs))


def _journal_division(element: ET.Element) -> Crumb | None:
    """The division *element* is when a label paragraph opens it: its label and the
    title in a paragraph of its own or in its ``eli-title``."""
    label: str | None = None
    title: str | None = None
    for child in element:
        classes = _classes(child)
        if child.tag == "p" and classes & _DIVISION_LABEL_CLASSES and label is None:
            label = _text(child)
        elif child.tag == "p" or "eli-title" in classes:
            title = title or next(
                (
                    _text(node)
                    for node in child.iter("p")
                    if _classes(node) & _DIVISION_TITLE_CLASSES
                ),
                None,
            )
    return _crumb(label, title) if label else None


def _in_cell(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> bool:
    node = parents.get(element)
    while node is not None:
        if node.tag == "td":
            return True
        node = parents.get(node)
    return False


def _contains(element: ET.Element, classes: frozenset[str]) -> bool:
    """Whether *element* or an element inside it has one of *classes*."""
    return any(_classes(node) & classes for node in element.iter())


def _heading_text(element: ET.Element) -> str | None:
    for node in element.iter():
        if _classes(node) & _HEADING_CLASSES:
            return _text(node) or None
    return None


def _add_blocks(elements: Iterable[ET.Element], depth: int, out: list[_Block]) -> None:
    """The paragraphs and points under *elements* at nesting *depth*, in document order."""
    for element in elements:
        if element.tag in _SKIP_TAGS:
            continue
        if element.tag == "p":
            text = _text(element)
            if text:
                out.append(_paragraph(text, depth))
            continue
        cells = _point_cells(element)
        if cells is not None:
            _add_point(*cells, depth, out)
            continue
        inner: list[_Block] = []
        _add_blocks(element, depth, inner)
        out.extend(_as_lid(element, inner) if depth == 0 else inner)


def _add_point(marker: str, body: ET.Element, depth: int, out: list[_Block]) -> None:
    """A point: its marker with the first paragraph of its text cell, then the rest."""
    inner: list[_Block] = []
    _add_blocks(body, depth + 1, inner)
    first = inner[0] if inner else None
    if first is not None and first.marker is None and first.depth == depth + 1:
        out.append(_Block(first.text, depth + 1, marker))
        inner = inner[1:]
    else:
        out.append(_Block("", depth + 1, marker))
    out.extend(inner)


def _as_lid(element: ET.Element, blocks: list[_Block]) -> list[_Block]:
    """*blocks* of a lid container (``div id="004.002"``: article 4, lid 2) that is laid
    out as one point numbered like the lid ("2."): that point is the lid."""
    lid = (
        _LID_DIV_RE.fullmatch(element.get("id") or "") if element.tag == "div" else None
    )
    if not lid or not blocks:
        return blocks
    first = blocks[0]
    if first.depth != 1 or (first.marker or "").rstrip(".") != str(int(lid[1])):
        return blocks
    return [_Block(first.text, 0, str(int(lid[1])))] + [
        _Block(
            block.text, block.depth - 1 if block.depth else block.depth, block.marker
        )
        for block in blocks[1:]
    ]


def _paragraph(text: str, depth: int) -> _Block:
    lid = _LID_RE.fullmatch(text) if depth == 0 else None
    if lid:
        return _Block(lid[2], 0, lid[1])
    return _Block(text, depth)


def _point_cells(element: ET.Element) -> tuple[str, ET.Element] | None:
    """(marker, text cell) of a table row that is a point, else None."""
    if element.tag != "tr":
        return None
    cells = [cell for cell in element if cell.tag == "td"]
    if len(cells) != 2:
        return None
    marker = _text(cells[0])
    if not _CELL_MARKER_RE.fullmatch(marker):
        return None
    return marker, cells[1]


# --- The old format --------------------------------------------------------------------


def _flat_articles(root: ET.Element) -> list[EuArticle]:
    """Articles of flat paragraphs: from "Artikel N" to the next article, a division
    heading or the closing formula. "Artikel N" with a number taken before is an article
    an amendment quotes: text of the article that quotes it."""
    paragraphs = [  # a <p> around other paragraphs is not one itself
        text
        for p in root.iter("p")
        if all(node is p for node in p.iter("p")) and (text := _text(p))
    ]
    reader = _FlatReader()
    for index, text in enumerate(paragraphs):
        following = paragraphs[index + 1] if index + 1 < len(paragraphs) else ""
        reader.read(text, following)
    reader.end_article()
    return reader.articles


class _FlatReader:
    """Reads the paragraphs of the old format one by one: the article that is open, its
    paragraphs and the divisions it stands in."""

    def __init__(self) -> None:
        self.articles: list[EuArticle] = []
        self.number: str | None = None
        self.body: list[str] = []
        self.crumbs: list[Crumb] = []
        self.untitled = False  # the last division has no title yet

    def read(self, text: str, following: str) -> None:
        number = self._new_article(text)
        division = _flat_division(text)
        if number is not None or _CLOSING_RE.match(text) or _DIVISION_RE.match(text):
            self.end_article()
            self.number = number
        elif division is not None:
            self.end_article()
        elif self._is_untitled_heading(text, following):
            self.end_article()
            self.crumbs = (
                [Crumb(self.crumbs[0].type, None, text)] if self.crumbs else []
            )
            return
        elif self.number is not None:
            self.body.append(text)
        elif self.untitled and _is_heading(text):
            self.crumbs[-1] = _crumb(self.crumbs[-1].label or "", text)
        self.untitled = False
        if division is not None:
            self._open(division)

    def end_article(self) -> None:
        if self.number is not None:
            self.articles.append(
                _flat_article(self.number, self.body, tuple(self.crumbs))
            )
        self.number, self.body = None, []

    def _new_article(self, text: str) -> str | None:
        """The number of the article *text* starts, None for one taken before."""
        match = _ARTICLE_RE.fullmatch(text)
        if not match or match[1] == self.number:
            return None
        if any(article.number == match[1] for article in self.articles):
            return None
        return match[1]

    def _is_untitled_heading(self, text: str, following: str) -> bool:
        """A heading in capitals without a label between two articles."""
        return (
            self.number is not None
            and text.isupper()
            and not text.endswith(_SENTENCE_END)
            and self._new_article(following) is not None
        )

    def _open(self, division: Crumb) -> None:
        """A kind that is open ends with what is inside it; another kind nests."""
        kinds = [crumb.type for crumb in self.crumbs]
        if division.type in kinds:
            del self.crumbs[kinds.index(division.type) :]
        self.crumbs.append(division)
        self.untitled = division.title is None


def _flat_division(text: str) -> Crumb | None:
    """The division a paragraph of the old format opens, if it is a division heading."""
    match = _DIVISION_LABEL_RE.fullmatch(text)
    if not match or not (match[1].isupper() or match[3]):
        return None
    return _crumb(f"{match[1]} {match[2]}", match[4])


def _flat_article(
    number: str, paragraphs: list[str], breadcrumb: tuple[Crumb, ...]
) -> EuArticle:
    heading: str | None = None
    if len(paragraphs) > 1 and _is_heading(paragraphs[0]):
        heading, paragraphs = paragraphs[0], paragraphs[1:]
    return _article(number, heading, _flat_blocks(paragraphs), breadcrumb)


def _is_heading(text: str) -> bool:
    return (
        len(text) <= _HEADING_MAX_CHARS
        and not text.endswith(_SENTENCE_END)
        and not _LID_RE.fullmatch(text)
        and not _FLAT_POINT_RE.fullmatch(text)
    )


def _flat_blocks(paragraphs: list[str]) -> list[_Block]:
    """Leden and points by the marker a paragraph starts with; a paragraph without one
    continues the part that is open."""
    blocks: list[_Block] = []
    levels: list[str] = []  # the marker kinds of the open points, outermost first
    last_letter = ""
    for text in paragraphs:
        lid = _LID_RE.fullmatch(text)
        point = _FLAT_POINT_RE.fullmatch(text)
        if lid:
            levels = []
            blocks.append(_Block(lid[2], 0, lid[1]))
        elif point:
            marker = point[1].replace(" ", "")
            kind = _marker_kind(marker, last_letter if _MARKER_LETTER in levels else "")
            if kind in levels:
                del levels[levels.index(kind) + 1 :]
            else:
                levels.append(kind)
            if kind == _MARKER_LETTER:
                last_letter = marker.strip("()")
            blocks.append(_Block(point[2], len(levels), marker))
        else:
            blocks.append(_Block(text, None))
    return blocks


def _marker_kind(marker: str, open_letter: str) -> str:
    """The kind of a flat marker; "i)" after "h)" is a letter, else a roman numeral."""
    core = marker.strip("()")
    if core[0].isdigit():
        return _MARKER_DIGIT
    if not core.isalnum():
        return _MARKER_DASH
    follows_letter = (
        len(core) == 1 and open_letter and ord(core) == ord(open_letter) + 1
    )
    if _ROMAN_RE.fullmatch(core) and not follows_letter:
        return _MARKER_ROMAN
    return _MARKER_LETTER


# --- Text and parts ----------------------------------------------------------------------


def _build(blocks: list[_Block]) -> tuple[str, list[ArticlePart]]:
    """The text of an article and its parts. The paragraphs of a lid (or of an article
    without leden) before its first point are its aanhef. A lid or point without text of
    its own shares its line with what follows ("f) — de ontbinding …")."""
    builder = TextBuilder()
    aanhef: list[int] = []  # start and end of the text before the first point
    in_points = glue = False
    for block in blocks:
        if builder.length:
            if block.depth is not None:
                # A lid ends every part; a point the points at its depth and deeper; a
                # paragraph the points deeper than it.
                builder.close_from(block.depth + (0 if block.marker else 1))
            builder.add("" if glue else "\n")
        if block.marker and block.depth == 0:
            builder.add(f"{block.marker}. ")
            builder.open_part(PART_LID, "lid", block.marker, 0)
            aanhef, in_points = [], False
        elif block.marker:
            if not in_points and len(aanhef) == 2 and aanhef[0] < aanhef[1]:
                builder.add_aanhef(aanhef[0], aanhef[1])
            in_points = True
            builder.add(f"{block.marker} ")
            number = block.marker.strip(_MARKER_PUNCTUATION)
            builder.open_part(PART_ONDERDEEL, "onder", number or None, block.depth or 1)
        start = builder.length
        builder.add(block.text)
        if not in_points and not (block.marker and block.depth):
            aanhef = [aanhef[0] if aanhef else start, builder.length]
        glue = bool(block.marker) and not block.text
    builder.close_from(0)
    text = builder.value().rstrip()  # a marker without text at the very end
    parts = sorted(
        (part for part in builder.structure if part.start < part.end <= len(text)),
        key=lambda part: (part.start, -part.end),
    )
    return text, parts
