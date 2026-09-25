"""Parse a BWB *toestand* (one dated version of a regulation) — pure, no I/O.

The BWB XML already says most of what we need, so we read it instead of guessing:

* every ``<artikel>`` has a stable identity across versions (``stam-id``), a
  version id (``versie-id``), the date it entered into force (``inwerking``) and
  the publication that created this version (``bron`` such as ``Stb.2019-33``)
  together with its ``effect`` (nieuw / wijziging / vervallen …);
* ``<meta-data><brondata>`` names the originating and the commencement
  publication, each optionally with ``<dossierref dossier="35786">`` — the
  parliamentary dossier of the amending bill;
* references in the text are ``<extref>`` / ``<intref>`` with a machine-readable
  ``doc="jci1.3:c:BWBR0001854&artikel=287"``;
* the preamble (``<aanhef>/<considerans>``) lists the legal basis in the
  paragraph that starts with "Gelet op", again as ``<extref>``.

Text offsets of references and of the structure of the article (``ArticleXml.parts``: aanhef,
leden, onderdelen) refer to ``ArticleXml.text`` (same string).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from lawgraph.config.constants import SOURCE_BWB
from lawgraph.core.annex_xml import AnnexXml, parse_annexes
from lawgraph.core.identifiers import (
    find_celex_ids,
    has_possible_year,
    is_bwb_id,
    rebuilt_celex,
)
from lawgraph.core.models import make_node_key
from lawgraph.core.qualifiers import Qualifier, parse_qualifier, part_slug
from lawgraph.core.xml import find_descendant, iter_named, local_name, text_of

# ``effect`` values on an article version, mapped to what the version did.
EFFECT_INTRODUCES = "introduces"
EFFECT_AMENDS = "amends"
EFFECT_REPEALS = "repeals"
_EFFECT_KIND = {
    "nieuw": EFFECT_INTRODUCES,
    "wijziging": EFFECT_AMENDS,
    "tekstplaatsing-wijziging": EFFECT_AMENDS,
    "tekstplaatsing-vernummering": EFFECT_AMENDS,
    "vervallen": EFFECT_REPEALS,
}


def effect_kind(effect: str | None) -> str | None:
    """``introduces`` / ``amends`` / ``repeals`` for a BWB ``effect``, else None."""
    return _EFFECT_KIND.get(effect or "")


@dataclass(frozen=True)
class Jci:
    """A parsed ``jci1.3:c:BWBR0001854&hoofdstuk=1&artikel=287`` reference."""

    bwb_id: str | None
    params: dict[str, str]

    @property
    def article(self) -> str | None:
        """The article as the graph numbers it: an article of an annex names its annex."""
        article = self.params.get("artikel")
        annex = self.params.get("bijlage")
        return annex_article_number(annex, article) if annex and article else article


def annex_article_number(annex: str, number: str) -> str:
    """The number of an article of an annex: ``bijlage 2 artikel 9``.

    An annex numbers its articles on its own (Bijlage 2 and Bijlage 3 of the Awb each have
    an article 1), as the JCI does (``bijlage=2&artikel=9``), so the annex is part of the
    number: it keeps the article apart from an article of the regulation or of another
    annex with the same number.
    """
    return f"bijlage {annex} artikel {number}"


_ANNEX_ARTICLE = re.compile(r"^bijlage (?P<annex>\S+) artikel (?P<number>.+)$")


def article_label(number: str) -> str:
    """``Artikel 287``; ``Artikel 9 van bijlage 2`` for an article of an annex."""
    match = _ANNEX_ARTICLE.match(number)
    if match:
        return f"Artikel {match['number']} van bijlage {match['annex']}"
    return f"Artikel {number}"


def article_key(bwb_id: str, number: str | None, stam_id: str | None) -> str | None:
    """The key of a current article: its number (``bwbr0001854_287``), or, for an article
    without one (a heading only: "Algemene bepaling"), its ``stam-id``
    (``bwbr0001840_stam_16464063``), which it keeps across versions. ``None`` without
    either."""
    if number:
        return make_node_key(bwb_id, number)
    if stam_id:
        return historical_article_key(bwb_id, None, stam_id)
    return None


def article_address(bwb_id: str, key: str, number: str | None) -> str:
    """The ``{article_number}`` segment of the article routes: the number, or for an
    article without one the rest of its key (``stam-16464063`` works as well as
    ``stam_16464063``), which the routes turn back into the key."""
    return number or key.removeprefix(f"{make_node_key(bwb_id)}_")


def parse_jci(doc: str | None) -> Jci:
    """Split a JCI string into the regulation id and its ``key=value`` parts."""
    if not doc:
        return Jci(None, {})
    head, *rest = doc.split("&")
    candidate = head.rsplit(":", 1)[-1]
    params = dict(part.split("=", 1) for part in rest if "=" in part)
    return Jci(candidate if is_bwb_id(candidate) else None, params)


@dataclass(frozen=True)
class Reference:
    """An ``<extref>``/``<intref>`` inside an article."""

    kind: str  # "extref" | "intref"
    bwb_id: str | None
    article: str | None
    doc: str
    text: str
    start: int
    end: int
    # Which parts of the article the link text names ("eerste lid, onder a"). The ``doc`` of
    # a link never does: it stops at the article.
    qualifier: Qualifier = Qualifier()

    def to_dict(self) -> dict[str, Any]:
        """JSON-able form stored in ``props.references``."""
        return {
            "kind": self.kind,
            "bwb_id": self.bwb_id,
            "article": self.article,
            "doc": self.doc,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            **self.qualifier.to_dict(),
        }


PART_AANHEF = "aanhef"
PART_LID = "lid"
PART_ONDERDEEL = "onderdeel"


@dataclass(frozen=True)
class ArticlePart:
    """A lid, an onderdeel or an aanhef of an article, as a span of ``ArticleXml.text``.

    ``text[start:end]`` is the content without its printed number (``number``: ``"2"``,
    ``"a"``, ``"1°"``, None for an aanhef or an unnumbered item). A lid or onderdeel with
    onderdelen inside spans them too; the parts are listed by ``start``, an enclosing part
    before the parts inside it. The ``id`` says where the part sits:

    * ``aanhef``: the text before the onderdelen of an article without leden;
    * ``lid-2``, ``lid-2a``; ``lid-2-aanhef``: the text of a lid before its onderdelen;
    * ``lid-2-onder-a``, ``onder-a`` (an article without leden), ``lid-2-onder-a-onder-1`` (an
      onderdeel of an onderdeel: the id of the part it sits in, then its own).

    The number of a lid or onderdeel is written as ``qualifiers.part_slug`` does (``1°`` is
    ``1``). An item without a letter or a digit is ``_<n>``, its position among its siblings;
    one whose marker repeats one before it gets ``_<n>``, its occurrence (``lid-1_2``). Ids
    are unique in an article.
    """

    id: str
    kind: str  # PART_AANHEF | PART_LID | PART_ONDERDEEL
    number: str | None
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        """JSON-able form stored in ``props.parts`` (offsets only: the text is in the article)."""
        return {
            "id": self.id,
            "kind": self.kind,
            "number": self.number,
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True)
class Publication:
    """A publication in the Staatsblad, Tractatenblad, Staatscourant, …"""

    kind: str  # "Stb", "Trb", "Stcrt" …
    year: int | None
    number: str | None
    identifier: str  # e.g. "stb-2019-33"
    effect: str | None
    signed: str | None  # ISO date
    published: str | None  # ISO date
    dossiers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """JSON-able form stored in node props (``origin_publication`` etc.)."""
        return {
            "id": self.identifier,
            "kind": self.kind,
            "year": self.year,
            "number": self.number,
            "effect": self.effect,
            "signed": self.signed,
            "published": self.published,
            "dossiers": list(self.dossiers),
        }


@dataclass(frozen=True)
class Crumb:
    """A division an article stands in: its element (``hoofdstuk``), its label
    ("Hoofdstuk 1") and its title ("Inleidende bepalingen")."""

    type: str
    label: str | None
    title: str | None

    def to_dict(self) -> dict[str, Any]:
        return _drop_none({"type": self.type, "label": self.label, "title": self.title})


# The divisions of a regulation that hold articles, as the toestand XML names them.
DIVISIONS = frozenset(
    {
        "boek",
        "deel",
        "titeldeel",
        "hoofdstuk",
        "afdeling",
        "paragraaf",
        "sub-paragraaf",
        "divisie",
    }
)


@dataclass(frozen=True)
class ArticleXml:
    number: str | None
    # "Artikel 287"; for an article without a number its heading ("Algemene bepaling")
    label: str | None
    text: str
    stam_id: str | None
    versie_id: str | None
    path: str | None  # bwb-ng-variabel-deel, e.g. "/Hoofdstuk1/Artikel7"
    valid_from: str | None  # inwerking
    source: str | None  # bron, e.g. "Stb.2019-33"
    effect: str | None
    origin: Publication | None = None
    commencement: Publication | None = None
    references: tuple[Reference, ...] = ()
    parts: tuple[ArticlePart, ...] = ()
    breadcrumb: tuple[Crumb, ...] = ()  # the divisions it stands in, outermost first

    @property
    def is_repealed(self) -> bool:
        return effect_kind(self.effect) == EFFECT_REPEALS


@dataclass(frozen=True)
class BasisRef:
    """An article an instrument is issued under ('Gelet op artikel …')."""

    bwb_id: str
    article: str | None
    doc: str
    text: str


@dataclass(frozen=True)
class ToestandXml:
    bwb_id: str | None
    kind: str | None  # wetgeving@soort: wet, amvb, …
    title: str | None  # citation title, else the official title
    official_title: str | None
    citation_title: str | None
    valid_from: str | None
    origin: Publication | None
    commencement: Publication | None
    basis: tuple[BasisRef, ...] = ()
    articles: tuple[ArticleXml, ...] = field(default_factory=tuple)
    annexes: tuple[AnnexXml, ...] = ()


# ── keys (one definition, used by normalize, semantic and the API) ───────────


def publication_key(identifier: str) -> str:
    """Instrument key of an amending publication (``stb-2019-33`` -> node key)."""
    return make_node_key(identifier)


def publication_display_name(publication: Mapping[str, Any]) -> str:
    """``Stb. 2019, 33`` — falls back to the publication id when parts are missing."""
    kind, year, number = (publication.get(k) for k in ("kind", "year", "number"))
    if kind and year and number:
        return f"{kind}. {year}, {number}"
    return str(publication.get("id") or "")


def publication_props(publication: Mapping[str, Any]) -> dict[str, Any]:
    """Instrument props of a publication; unknown (None) values are left out.

    The argument is the dict form of :class:`Publication` as stored on article
    versions (``origin_publication`` / ``commencement_publication``). Leaving
    unknown values out matters: the node upsert merges props, so a missing value
    must not overwrite one written earlier. ``dossier_numbers`` is not included —
    the caller merges the dossiers of all versions naming the publication.
    """
    props: dict[str, Any] = {
        "display_name": publication_display_name(publication),
        "source": SOURCE_BWB,
        "publication_kind": publication.get("kind") or None,
        "publication_year": publication.get("year"),
        "publication_number": publication.get("number"),
        "date_signed": publication.get("signed"),
        "date_published": publication.get("published"),
    }
    return _drop_none(props)


def article_version_key(bwb_id: str, stam_id: str, versie_id: str) -> str:
    """Key of one version of an article; identical in every toestand that repeats it."""
    return make_node_key(bwb_id, "av", stam_id, versie_id)


def historical_article_key(bwb_id: str, number: str | None, stam_id: str) -> str:
    """Key of an article identity that is no longer in the current toestand."""
    return make_node_key(bwb_id, number or "", "stam", stam_id)


# ── publications ─────────────────────────────────────────────────────────────


def _iso(element: ET.Element | None) -> str | None:
    return element.get("isodatum") if element is not None else None


def _child(element: ET.Element, name: str) -> ET.Element | None:
    for node in element:
        if local_name(node.tag) == name:
            return node
    return None


def _publication(element: ET.Element | None) -> Publication | None:
    """Parse the ``<publicatie>`` directly inside an ``oorspronkelijk``/``inwerkingtreding``."""
    if element is None:
        return None
    pub = _child(element, "publicatie")
    if pub is None:
        return None
    kind = pub.get("soort") or ""
    year_text = text_of(_child(pub, "publicatiejaar"))
    number = text_of(_child(pub, "publicatienr")) or None
    year = int(year_text) if year_text.isdigit() else None
    identifier = pub.get("urlidentifier") or (
        f"{kind.lower()}-{year}-{number}" if kind and year and number else ""
    )
    dossiers = tuple(
        dict.fromkeys(
            d.get("dossier") or text_of(d)
            for d in iter_named(pub, "dossierref")
            if d.get("dossier") or text_of(d)
        )
    )
    return Publication(
        kind=kind,
        year=year,
        number=number,
        identifier=identifier,
        effect=pub.get("effect"),
        signed=_iso(_child(pub, "ondertekeningsdatum")),
        published=_iso(_child(pub, "uitgiftedatum")),
        dossiers=dossiers,
    )


def _brondata(container: ET.Element) -> tuple[Publication | None, Publication | None]:
    """(originating, commencement) publication from the element's own ``meta-data``."""
    meta = _child(container, "meta-data")
    brondata = _child(meta, "brondata") if meta is not None else None
    if brondata is None:
        return None, None
    return (
        _publication(_child(brondata, "oorspronkelijk")),
        _publication(_child(brondata, "inwerkingtreding")),
    )


# ── article text with reference offsets ──────────────────────────────────────


@dataclass
class _OpenPart:
    id: str
    kind: str
    number: str | None
    start: int
    depth: int  # 0 for a lid, 1 + the nesting for an onderdeel


class _TextBuilder:
    """Accumulate text and remember where references and the parts of the article sit."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.length = 0
        self.refs: list[Reference] = []
        self.structure: list[ArticlePart] = []
        self._open: list[_OpenPart] = []
        self._siblings: dict[tuple[str, str], list[str]] = {}

    def add(self, text: str) -> None:
        self.parts.append(text)
        self.length += len(text)

    def inline(self, element: ET.Element) -> None:
        """Append the (stripped) inline text of *element*, tracking its references."""
        raw = _flatten(element)
        text = raw.text.strip()
        lead = len(raw.text) - len(raw.text.lstrip())
        base = self.length
        for ref in raw.refs:
            start, end = ref.start - lead, ref.end - lead
            if start < 0 or end > len(text):
                continue  # reference fell into stripped whitespace
            self.refs.append(replace(ref, start=base + start, end=base + end))
        self.add(text)

    def value(self) -> str:
        return "".join(self.parts)

    def open_part(self, kind: str, label: str, number: str | None, depth: int) -> None:
        """Start a lid or onderdeel at the current position, inside the part it sits in."""
        self.close_from(depth)
        parent = self._open[-1].id if self._open else ""
        slug = part_slug(number)
        seen = self._siblings.setdefault((parent, label), [])
        seen.append(slug)
        if not slug:
            slug = f"_{len(seen)}"
        elif seen.count(slug) > 1:
            slug = f"{slug}_{seen.count(slug)}"
        ident = "-".join(part for part in (parent, label, slug) if part)
        self._open.append(_OpenPart(ident, kind, number, self.length, depth))

    def close_from(self, depth: int) -> None:
        """End the open parts at *depth* and deeper, here."""
        while self._open and self._open[-1].depth >= depth:
            part = self._open.pop()
            self.structure.append(
                ArticlePart(part.id, part.kind, part.number, part.start, self.length)
            )

    def add_aanhef(self, start: int, end: int) -> None:
        """An aanhef: the lid it belongs to is the part that is open, else the article."""
        parent = self._open[-1].id if self._open else ""
        ident = "-".join(part for part in (parent, PART_AANHEF) if part)
        self.structure.append(ArticlePart(ident, PART_AANHEF, None, start, end))


@dataclass
class _Flat:
    text: str
    refs: list[Reference]


def _flatten(element: ET.Element) -> _Flat:
    """Concatenate all text of *element*; note reference offsets (unstripped)."""
    out: list[str] = []
    refs: list[Reference] = []
    length = 0

    def walk(node: ET.Element) -> None:
        nonlocal length
        name = local_name(node.tag)
        if name == "meta-data":
            return
        start = length
        if node.text:
            out.append(node.text)
            length += len(node.text)
        for child in node:
            walk(child)
            if child.tail:
                out.append(child.tail)
                length += len(child.tail)
        if name in ("extref", "intref"):
            doc = node.get("doc") or ""
            jci = parse_jci(doc)
            bwb_id = node.get("bwb-id") or jci.bwb_id
            text = "".join(out)[start:length]
            refs.append(
                Reference(
                    kind=name,
                    bwb_id=bwb_id,
                    article=jci.article,
                    doc=doc,
                    text=text,
                    start=start,
                    end=length,
                    # A link to a chapter or a title names no lid: only a link to an article does.
                    qualifier=parse_qualifier(text if jci.article else None),
                )
            )

    walk(element)
    return _Flat("".join(out), refs)


def _article_number(article: ET.Element) -> str | None:
    kop = find_descendant(article, "kop")
    if kop is not None:
        nr = find_descendant(kop, "nr")
        if nr is not None and text_of(nr):
            return text_of(nr)
    label = (article.get("label") or "").strip()
    if label.lower().startswith("artikel"):
        rest = label[len("artikel") :].lstrip(":. ").strip()
        if rest:
            return rest
    return None


def _article_heading(article: ET.Element) -> str | None:
    """The heading of an article without a number: the ``<titel>`` of its ``<kop>``
    ("Algemene bepaling"), else the ``<label>`` of its ``<kop>`` or its ``label`` attribute
    ("Slotartikel" of the Overgangswet nieuw Burgerlijk Wetboek); whitespace collapsed."""
    kop = _child(article, "kop")
    for text in (
        text_of(_child(kop, "titel")) if kop is not None else "",
        text_of(_child(kop, "label")) if kop is not None else "",
        article.get("label") or "",
    ):
        heading = " ".join(text.split())
        if heading:
            return heading
    return None


def _add_paragraphs(builder: _TextBuilder, paragraphs: list[ET.Element]) -> None:
    """Add *paragraphs* separated by a space."""
    for index, al in enumerate(paragraphs):
        if index:
            builder.add(" ")
        builder.inline(al)


def _list_items(
    element: ET.Element, depth: int = 1
) -> Iterator[tuple[ET.Element, int]]:
    """Every ``li`` under *element* in document order, with how deep the lists nest."""
    for child in element:
        if local_name(child.tag) == "li":
            yield child, depth
            yield from _list_items(child, depth + 1)
        else:
            yield from _list_items(child, depth)


def _add_item(
    builder: _TextBuilder, li: ET.Element, body: list[ET.Element], depth: int
) -> None:
    """Add one list item on a new line: its marker (``a.``, ``1°.``) and its paragraphs."""
    # The item before it ends here, not after the marker of this one.
    builder.close_from(depth)
    builder.add("\n")
    marker = text_of(find_descendant(li, "li.nr"))
    if marker:
        builder.add(f"{marker} ")
    builder.open_part(PART_ONDERDEEL, "onder", marker.rstrip(".") or None, depth)
    _add_paragraphs(builder, body)


def _add_lid(builder: _TextBuilder, lid: ET.Element) -> None:
    """Add one ``lid``: ``1. paragraph`` followed by its list items on new lines."""
    paragraphs = [c for c in lid if local_name(c.tag) == "al"]
    items = list(_list_items(lid))
    if not paragraphs and not items:
        return
    if builder.parts:
        builder.add("\n")
    number = text_of(find_descendant(lid, "lidnr"))
    if number:
        builder.add(f"{number}. ")
    builder.open_part(PART_LID, "lid", number.rstrip(".") or None, 0)
    aanhef_start = builder.length
    _add_paragraphs(builder, paragraphs)
    aanhef_end = builder.length
    has_onderdelen = False
    for li, depth in items:
        body = [c for c in li if local_name(c.tag) == "al"]
        if not body:
            continue
        if paragraphs and not has_onderdelen:  # the paragraphs lead up to the list
            builder.add_aanhef(aanhef_start, aanhef_end)
        has_onderdelen = True
        _add_item(builder, li, body, depth)
    builder.close_from(0)


def _add_block(builder: _TextBuilder, element: ET.Element, depth: int = 1) -> None:
    """Add the law text under *element* (paragraphs and list items) on new lines."""
    name = local_name(element.tag)
    if name == "meta-data":
        return
    if name == "al":
        if builder.parts:
            builder.add("\n")
        builder.inline(element)
        return
    if name == "li":
        body = [c for c in element if local_name(c.tag) == "al"]
        if body:
            _add_item(builder, element, body, depth)
        for child in element:  # nested lists
            if local_name(child.tag) != "al":
                _add_block(builder, child, depth + 1)
        builder.close_from(depth)
        return
    for child in element:
        _add_block(builder, child, depth)


def _shift_part(
    part: ArticlePart, raw: str, lead: int, length: int
) -> ArticlePart | None:
    """*part* within the stripped text: its whitespace trimmed, None when nothing is left."""
    start, end = part.start, min(part.end, lead + length)
    while start < end and raw[start].isspace():
        start += 1
    while end > start and raw[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    return replace(part, start=start - lead, end=end - lead)


def _article_text(
    article: ET.Element,
) -> tuple[str, list[Reference], list[ArticlePart]]:
    """Article text in document order: leden as ``1. text``, other paragraphs and
    list items on their own lines. A paragraph next to the leden (for example
    "Dit artikel is nog niet in werking getreden") is part of the article.

    Also the offsets of the leden, onderdelen and aanhef in that text, and of the references.
    An article without leden but with a list has the paragraphs before it as its aanhef."""
    builder = _TextBuilder()
    children = [c for c in article if local_name(c.tag) not in ("kop", "meta-data")]
    first_list = next(
        (i for i, c in enumerate(children) if local_name(c.tag) == "lijst"), None
    )
    has_leden = any(local_name(c.tag) == "lid" for c in children)
    intro: list[tuple[int, int]] = []  # spans of the paragraphs before the list
    for index, child in enumerate(children):
        start = builder.length
        if local_name(child.tag) == "lid":
            _add_lid(builder, child)
        else:
            _add_block(builder, child)
            if (
                not has_leden
                and first_list is not None
                and index < first_list
                and local_name(child.tag) == "al"
            ):
                intro.append((start, builder.length))
    if intro and any(part.kind == PART_ONDERDEEL for part in builder.structure):
        builder.add_aanhef(intro[0][0], intro[-1][1])
    builder.close_from(0)
    raw = builder.value()
    text = raw.strip()
    lead = len(raw) - len(raw.lstrip())
    refs = [
        replace(ref, start=ref.start - lead, end=ref.end - lead)
        for ref in builder.refs
        if ref.start >= lead and ref.end - lead <= len(text)
    ]
    shifted = (_shift_part(part, raw, lead, len(text)) for part in builder.structure)
    parts = sorted(
        (part for part in shifted if part is not None),
        key=lambda part: (part.start, -part.end),
    )
    return text, refs, parts


def _crumb(division: ET.Element, name: str) -> Crumb:
    """The label and title of a division, from its ``label`` and its ``<kop>``."""
    kop = _child(division, "kop")
    label = division.get("label")
    if not label and kop is not None:
        label = " ".join(
            filter(None, (text_of(_child(kop, "label")), text_of(_child(kop, "nr"))))
        )
    title = " ".join(text_of(_child(kop, "titel")).split()) if kop is not None else ""
    return Crumb(type=name, label=label or None, title=title or None)


def _annex_number(annex: ET.Element) -> str | None:
    """The number of a ``<bijlage>`` as the JCI writes it: ``2`` of ``Bijlage 2``."""
    kop = _child(annex, "kop")
    nr = text_of(_child(kop, "nr")) if kop is not None else ""
    if nr:
        return nr
    label = (annex.get("label") or "").strip()
    rest = (
        label[len("bijlage") :].strip() if label.lower().startswith("bijlage") else ""
    )
    return rest or None


def _articles(
    element: ET.Element,
    breadcrumb: tuple[Crumb, ...] = (),
    annex: str | None = None,
) -> Iterator[ArticleXml]:
    """The articles under *element* in document order, each with the divisions it is in
    and, in an annex, the number of that annex."""
    for child in element:
        name = local_name(child.tag)
        if name == "artikel":
            yield _parse_article(child, breadcrumb, annex)
        elif name == "bijlage":
            crumb = _crumb(child, name)
            yield from _articles(child, (*breadcrumb, crumb), _annex_number(child))
        elif name in DIVISIONS:
            yield from _articles(child, (*breadcrumb, _crumb(child, name)), annex)
        else:
            yield from _articles(child, breadcrumb, annex)


def _parse_article(
    article: ET.Element, breadcrumb: tuple[Crumb, ...], annex: str | None
) -> ArticleXml:
    text, refs, parts = _article_text(article)
    origin, commencement = _brondata(article)
    number = _article_number(article)
    if annex and number:
        number = annex_article_number(annex, number)
    return ArticleXml(
        number=number,
        label=article_label(number) if number else _article_heading(article),
        text=text,
        stam_id=article.get("stam-id"),
        versie_id=article.get("versie-id"),
        path=article.get("bwb-ng-variabel-deel"),
        valid_from=article.get("inwerking"),
        source=article.get("bron"),
        effect=article.get("effect"),
        origin=origin,
        commencement=commencement,
        references=tuple(refs),
        parts=tuple(parts),
        breadcrumb=breadcrumb,
    )


# ── preamble: "Gelet op" ─────────────────────────────────────────────────────


def _basis(root: ET.Element) -> tuple[BasisRef, ...]:
    """References in the ``considerans`` paragraph(s) that start with 'Gelet op'."""
    found: dict[tuple[str, str | None], BasisRef] = {}
    for considerans in iter_named(root, "considerans"):
        for para in considerans.iter():
            if not local_name(para.tag).startswith("considerans"):
                continue
            if not text_of(para).lower().startswith("gelet op"):
                continue
            for ref in _flatten(para).refs:
                if ref.kind != "extref" or not ref.bwb_id:
                    continue
                found.setdefault(
                    (ref.bwb_id, ref.article),
                    BasisRef(ref.bwb_id, ref.article, ref.doc, ref.text),
                )
    return tuple(found.values())


# ── entry point ──────────────────────────────────────────────────────────────


def _title(root: ET.Element, name: str) -> str | None:
    """Whitespace-collapsed text of the first ``<name>``, ignoring its ``meta-data``."""
    element = next(iter_named(root, name), None)
    if element is None:
        return None
    return " ".join(_flatten(element).text.split()) or None


def parse_toestand(xml_text: str) -> ToestandXml:
    """Parse the XML of one toestand. Raises ``ET.ParseError`` on malformed XML."""
    root = ET.fromstring(xml_text)
    wetgeving = next(iter_named(root, "wetgeving"), None)
    origin, commencement = (
        _brondata(wetgeving) if wetgeving is not None else (None, None)
    )
    articles = tuple(_articles(root))
    return ToestandXml(
        bwb_id=root.get("bwb-id"),
        kind=wetgeving.get("soort") if wetgeving is not None else None,
        title=_title(root, "citeertitel") or _title(root, "intitule"),
        official_title=_title(root, "intitule"),
        citation_title=_title(root, "citeertitel"),
        valid_from=(
            wetgeving.get("inwerkingtredingsdatum") if wetgeving is not None else None
        )
        or root.get("inwerkingtreding"),
        origin=origin,
        commencement=commencement,
        basis=_basis(root),
        articles=articles,
        annexes=parse_annexes(root),
    )


# ── node props (pure builders shared by the normalize pipelines) ─────────────


def _drop_none(props: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if v is not None}


_CELEX_LINK = re.compile(
    r'<extref\b[^>]*\bdoc="(3\d{4}[A-Za-z]\d{4})"[^>]*>(.*?)</extref>', re.DOTALL
)
_TAGS_AND_SPACE_AT_A_SLASH = re.compile(r"<[^>]+>|\s+(?=/)|(?<=/)\s+")


def celex_refs(toestand_xml: str) -> list[str]:
    """The EU acts a toestand names: every CELEX id in it, a link's ``doc`` among them.

    An id with an impossible year is no act; as the ``doc`` of a link it is rebuilt from
    the text of the link (``rebuilt_celex``), and left out when that cannot be done.
    """
    named = {
        celex for celex in find_celex_ids(toestand_xml) if has_possible_year(celex)
    }
    for doc, inner in _CELEX_LINK.findall(toestand_xml):
        if not has_possible_year(doc):
            rebuilt = rebuilt_celex(doc, _TAGS_AND_SPACE_AT_A_SLASH.sub("", inner))
            if rebuilt:
                named.add(rebuilt)
    return sorted(named)


def instrument_props(
    toestand: ToestandXml, bwb_id: str, *, celex_refs: Iterable[str] = ()
) -> dict[str, Any]:
    """Props of the Instrument node for a regulation.

    ``basis`` and ``celex_refs`` are what the semantic steps link from (BASED_ON,
    IMPLEMENTS): kept here, where the toestand is parsed anyway, so they do not read and
    parse every toestand again. Both are always written: an empty list replaces a stale one.
    """
    origin = toestand.origin
    title = toestand.title or f"BWB-regeling {bwb_id}"
    return _drop_none(
        {
            "basis": [
                {"bwb_id": r.bwb_id, "article": r.article, "doc": r.doc, "text": r.text}
                for r in toestand.basis
            ],
            "celex_refs": sorted(set(celex_refs)),
            "source": SOURCE_BWB,
            "bwb_id": bwb_id,
            "title": title,
            "official_title": toestand.official_title,
            "citation_title": toestand.citation_title,
            "display_name": title,
            "kind": toestand.kind,
            "jurisdiction": "nl",
            "dossier_numbers": (
                list(origin.dossiers) if origin and origin.dossiers else None
            ),
            "date_signed": origin.signed if origin else None,
            "date_published": origin.published if origin else None,
            "date_in_force": toestand.valid_from,
        }
    )


def article_display_name(label: str | None, citation_title: str | None) -> str | None:
    """``Artikel 287 Wetboek van Strafrecht``, ``Algemene bepaling Grondwet``."""
    return " ".join(filter(None, (label, citation_title))) or None


def article_props(
    article: ArticleXml, bwb_id: str, citation_title: str | None, position: int
) -> dict[str, Any]:
    """Props of the (current) Article node; *position* is its place in the toestand."""
    references = [r.to_dict() for r in article.references if r.bwb_id]
    return _drop_none(
        {
            "bwb_id": bwb_id,
            "article_number": article.number,
            "label": article.label,
            "position": position,
            "text": article.text,
            "instrument_citation_title": citation_title,
            "display_name": article_display_name(article.label, citation_title),
            "stam_id": article.stam_id,
            "versie_id": article.versie_id,
            "valid_from": article.valid_from,
            "source_publication": article.source,
            # always written: an upsert merges props, so a stale true must be overwritten
            "repealed": article.is_repealed,
            "parts": [part.to_dict() for part in article.parts],
            "references": references,
            "breadcrumb": [crumb.to_dict() for crumb in article.breadcrumb] or None,
        }
    )


def article_version_props(
    article: ArticleXml, bwb_id: str, citation_title: str | None, position: int
) -> dict[str, Any]:
    """Props of one ArticleVersion node (``valid_until`` is filled in afterwards);
    *position* is its place in the toestand it was read from."""
    return _drop_none(
        {
            "bwb_id": bwb_id,
            "article_number": article.number,
            "label": article.label,
            "position": position,
            "text": article.text,
            "parts": [part.to_dict() for part in article.parts],
            "instrument_citation_title": citation_title,
            "display_name": article_display_name(article.label, citation_title),
            "stam_id": article.stam_id,
            "versie_id": article.versie_id,
            "path": article.path,
            "valid_from": article.valid_from,
            "effect": article.effect,
            "source_publication": article.source,
            "origin_publication": article.origin.to_dict() if article.origin else None,
            "commencement_publication": (
                article.commencement.to_dict() if article.commencement else None
            ),
        }
    )
