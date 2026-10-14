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

import datetime as dt
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from lawgraph.config.constants import SOURCE_BWB
from lawgraph.core.annex_xml import AnnexXml, parse_annexes
from lawgraph.core.eu_citations import implemented_acts
from lawgraph.core.identifiers import (
    find_celex_ids,
    has_possible_year,
    is_bwb_id,
    rebuilt_celex,
)
from lawgraph.core.models import make_node_key
from lawgraph.core.publications import koop_id, publication_citation, publication_series
from lawgraph.core.qualifiers import Qualifier, parse_qualifier, part_slug
from lawgraph.core.xml import (
    XML_TAG_RE,
    child_named,
    children_named,
    collapse_ws,
    find_descendant,
    iter_named,
    local_name,
    text_of,
    words_of,
)

# ``effect`` values on an article version, mapped to what the version did. A
# ``nieuwe-regeling`` is an article of a regulation as it was enacted (art. 1 Cbw, Stb.
# 2026, 187), a ``nieuw`` one an article added to an existing regulation. A
# ``tekstplaatsing`` places the text of the article again (the Grondwet as a whole after a
# revision, Stb. 2019, 33): a republication, which changes no text of its own.
EFFECT_ESTABLISHES = "establishes"
EFFECT_INTRODUCES = "introduces"
EFFECT_AMENDS = "amends"
EFFECT_REPEALS = "repeals"
EFFECT_REPUBLISHES = "republishes"
_EFFECT_KIND = {
    "nieuwe-regeling": EFFECT_ESTABLISHES,
    "nieuw": EFFECT_INTRODUCES,
    "wijziging": EFFECT_AMENDS,
    "tekstplaatsing-wijziging": EFFECT_REPUBLISHES,
    "tekstplaatsing-vernummering": EFFECT_REPUBLISHES,
    "vervallen": EFFECT_REPEALS,
}


def effect_kind(effect: str | None) -> str | None:
    """``establishes`` / ``introduces`` / ``amends`` / ``repeals`` / ``republishes`` for a
    BWB ``effect``, else None."""
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
PART_TEKST = "tekst"


@dataclass(frozen=True)
class ArticlePart:
    """A lid, an onderdeel, an aanhef or a tekst of an article, as a span of
    ``ArticleXml.text``.

    ``text[start:end]`` is the content without its printed number (``number``: ``"2"``,
    ``"a"``, ``"1°"``, None for an aanhef or an unnumbered item). A lid or onderdeel with
    onderdelen inside spans them too; the parts are listed by ``start``, an enclosing part
    before the parts inside it. The ``id`` says where the part sits:

    * ``aanhef``: the text before the onderdelen of an article without leden;
    * ``tekst-1``, ``tekst-2``: a paragraph of an article with parts that is in none of them
      (the lines between the lists of an article of a bijlage, a note next to the leden), so
      that the parts and their printed numbers cover the whole text;
    * ``lid-2``, ``lid-2a``; ``lid-2-aanhef``: the text of a lid before its onderdelen;
    * ``lid-2-onder-a``, ``onder-a`` (an article without leden), ``lid-2-onder-a-onder-1`` (an
      onderdeel of an onderdeel: the id of the part it sits in, then its own);
    * ``tekst-3-onder-a``: an onderdeel of the list that a definition paragraph leads
      ("<nadruk>adviseren:</nadruk>" and its own a, b: Wft 1:1).

    ``term`` is the term a definition without a letter or digit defines, from the
    ``<nadruk>`` its paragraph begins with: an unmarked onderdeel ("– netwerk- en
    informatiesysteem:", art. 1 Cbw) or a tekst (Wft 1:1). It is cited by it ("art. 1,
    definitie van 'netwerk- en informatiesysteem', onder a").

    The number of a lid or onderdeel is written as ``qualifiers.part_slug`` does (``1°`` is
    ``1``). An item without a letter or a digit is ``_<n>``, its position among its siblings;
    one whose marker repeats one before it gets ``_<n>``, its occurrence (``lid-1_2``). Ids
    are unique in an article.
    """

    id: str
    kind: str  # PART_AANHEF | PART_LID | PART_ONDERDEEL | PART_TEKST
    number: str | None
    start: int
    end: int
    term: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-able form stored in ``props.parts`` (offsets only: the text is in the article);
        ``term`` only where there is one."""
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "number": self.number,
            "start": self.start,
            "end": self.end,
        }
        if self.term:
            out["term"] = self.term
        return out


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
    # the ``urlidentifier`` as the BWB gives it, the id of officielebekendmakingen.nl;
    # None where it gives none (``identifier`` is then made from kind, year and number)
    url_identifier: str | None = None

    def to_dict(self) -> dict[str, object]:
        """JSON-able form stored in node props (``origin_publication`` etc.)."""
        return {
            "id": self.identifier,
            "url_identifier": self.url_identifier,
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
    # the ``<titel>`` of its ``<kop>`` ("Definities"), numbered or not; most articles have none
    heading: str | None = None

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
    # wetgeving@verdragnummer of a treaty: its Verdragenbank id, six digits ("005132")
    treaty_number: str | None
    title: str | None  # citation title, else the official title
    official_title: str | None
    citation_title: str | None
    valid_from: str | None  # the start of this toestand
    # The regulation as it was enacted: the publication in the ``meta-data`` of its
    # ``<intitule>`` and the date it entered into force. (The ``meta-data`` of
    # ``<wetgeving>`` names the last change to the structure of the law, not the law.)
    enacted: Publication | None = None
    enacted_in_force: str | None = None
    basis: tuple[BasisRef, ...] = ()
    # the EU acts its considerans says it implements (CELEX numbers), see ``implemented_acts``
    implements: tuple[str, ...] = ()
    articles: tuple[ArticleXml, ...] = field(default_factory=tuple)
    annexes: tuple[AnnexXml, ...] = ()


# ── keys (one definition, used by normalize, semantic and the API) ───────────


def publication_key(identifier: str) -> str:
    """Instrument key of an amending publication (``stb-2019-33`` -> node key)."""
    return make_node_key(identifier)


def publication_display_name(publication: Mapping[str, Any]) -> str:
    """``Stb. 2019, 33`` — falls back to the publication id when parts are missing."""
    series = publication_series(publication.get("kind"))
    year, number = publication.get("year"), publication.get("number")
    if series and year and number:
        return publication_citation(series, year, number)
    return str(publication.get("id") or "")


# The kind of an instrument node that is a publication (Stb. 2019, 33), not a regulation: kept
# out of the instrument lists and counts.
KIND_PUBLICATION = "publicatie"


def publication_props(publication: Mapping[str, Any]) -> dict[str, Any]:
    """Instrument props of a publication; unknown (None) values are left out.

    The argument is the dict form of :class:`Publication` as stored on article
    versions (``origin_publication`` / ``commencement_publication``). Leaving
    unknown values out matters: the node upsert merges props, so a missing value
    must not overwrite one written earlier. ``dossier_numbers`` is not included —
    the caller merges the dossiers of all versions naming the publication.
    """
    name = publication_display_name(publication)
    props: dict[str, Any] = {
        "display_name": name,
        "citation_title": name,
        "kind": KIND_PUBLICATION,
        "jurisdiction": "nl",
        "source": SOURCE_BWB,
        # the id of officielebekendmakingen.nl as the BWB gives it: "stb-2019-33"
        "official_id": publication.get("url_identifier") or None,
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


def _publication(element: ET.Element | None) -> Publication | None:
    """Parse the ``<publicatie>`` directly inside an ``oorspronkelijk``/``inwerkingtreding``."""
    if element is None:
        return None
    pub = child_named(element, "publicatie")
    if pub is None:
        return None
    kind = pub.get("soort") or ""
    year_text = text_of(child_named(pub, "publicatiejaar"))
    number = text_of(child_named(pub, "publicatienr")) or None
    year = int(year_text) if year_text.isdigit() else None
    identifier = pub.get("urlidentifier") or (
        koop_id(kind, year, number) if kind and year and number else ""
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
        url_identifier=pub.get("urlidentifier") or None,
        effect=pub.get("effect"),
        signed=_iso(child_named(pub, "ondertekeningsdatum")),
        published=_iso(child_named(pub, "uitgiftedatum")),
        dossiers=dossiers,
    )


def _enactment(root: ET.Element) -> tuple[Publication | None, str | None]:
    """The publication that enacted the regulation and the date it entered into force,
    from the ``meta-data`` of its ``<intitule>`` (``oorspronkelijk`` and
    ``inwerkingtreding.datum``); None for what it does not say."""
    intitule = next(iter_named(root, "intitule"), None)
    meta = child_named(intitule, "meta-data")
    brondata = child_named(meta, "brondata")
    if brondata is None:
        return None, None
    commencement = child_named(brondata, "inwerkingtreding")
    in_force = (
        _iso(child_named(commencement, "inwerkingtreding.datum"))
        if commencement is not None
        else None
    )
    return _publication(child_named(brondata, "oorspronkelijk")), in_force


def _brondata(container: ET.Element) -> tuple[Publication | None, Publication | None]:
    """(originating, commencement) publication from the element's own ``meta-data``."""
    meta = child_named(container, "meta-data")
    brondata = child_named(meta, "brondata")
    if brondata is None:
        return None, None
    return (
        _publication(child_named(brondata, "oorspronkelijk")),
        _publication(child_named(brondata, "inwerkingtreding")),
    )


# ── article text with reference offsets ──────────────────────────────────────


@dataclass
class _OpenPart:
    id: str
    kind: str
    number: str | None
    start: int
    depth: int  # 0 for a lid, 1 + the nesting for an onderdeel
    term: str | None = None


class TextBuilder:
    """Accumulate text and remember where references and the parts of the article sit.

    Also builds the text and parts of an EU article (``core.eurlex_html``)."""

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

    def open_part(
        self,
        kind: str,
        label: str,
        number: str | None,
        depth: int,
        term: str | None = None,
    ) -> None:
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
        self._open.append(_OpenPart(ident, kind, number, self.length, depth, term))

    def open_lead(self, ident: str, start: int, term: str | None) -> None:
        """Start a tekst at *start* that holds the list after it (a definition paragraph
        and its own onderdelen); *ident* stands for its id until the teksten are numbered."""
        self._open.append(_OpenPart(ident, PART_TEKST, None, start, 0, term))

    def close_from(self, depth: int) -> None:
        """End the open parts at *depth* and deeper, here."""
        while self._open and self._open[-1].depth >= depth:
            part = self._open.pop()
            self.structure.append(
                ArticlePart(
                    part.id, part.kind, part.number, part.start, self.length, part.term
                )
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


def article_number(article: ET.Element) -> str | None:
    """The number of an ``<artikel>`` ("1:1"), from its ``kop`` or its ``label``."""
    return _article_number(article)


def _article_title(article: ET.Element) -> str | None:
    """The ``<titel>`` of the ``<kop>`` of an article ("Definities"), whitespace collapsed."""
    kop = child_named(article, "kop")
    title = collapse_ws(text_of(child_named(kop, "titel")))
    return title or None


def _article_heading(article: ET.Element) -> str | None:
    """The heading of an article without a number: the ``<titel>`` of its ``<kop>``
    ("Algemene bepaling"), else the ``<label>`` of its ``<kop>`` or its ``label`` attribute
    ("Slotartikel" of the Overgangswet nieuw Burgerlijk Wetboek); whitespace collapsed."""
    kop = child_named(article, "kop")
    for text in (
        _article_title(article) or "",
        text_of(child_named(kop, "label")),
        article.get("label") or "",
    ):
        heading = collapse_ws(text)
        if heading:
            return heading
    return None


def leading_term(al: ET.Element) -> str | None:
    """The term an ``<al>`` begins with in ``<nadruk>``, without its colon: inside it
    ("<nadruk>aanbieden:</nadruk>") or right after it ("<nadruk>bieder</nadruk>: een …")."""
    first = next(iter(al), None)
    if first is None or local_name(first.tag) != "nadruk" or (al.text or "").strip():
        return None
    term = words_of(first)
    if term.endswith(":"):
        term = term[:-1]
    elif not (first.tail or "").lstrip().startswith(":"):
        return None
    return term.strip() or None


def _leads_list(children: list[ET.Element], index: int) -> str | None:
    """The term of the paragraph at *index* when it is only a term and the list after it is
    its meanings ("<nadruk>adviseren:</nadruk>", then a, b: Wft 1:1)."""
    al = children[index]
    if index + 1 >= len(children) or local_name(children[index + 1].tag) != "lijst":
        return None
    term = leading_term(al)
    return term if term and words_of(al).rstrip(":").strip() == term else None


def _add_paragraphs(builder: TextBuilder, paragraphs: list[ET.Element]) -> None:
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
    builder: TextBuilder, li: ET.Element, body: list[ET.Element], depth: int
) -> None:
    """Add one list item on a new line: its marker (``a.``, ``1°.``) and its paragraphs."""
    # The item before it ends here, not after the marker of this one.
    builder.close_from(depth)
    builder.add("\n")
    marker = text_of(find_descendant(li, "li.nr"))
    if marker:
        builder.add(f"{marker} ")
    unmarked = not any(char.isalnum() for char in marker)
    term = leading_term(body[0]) if unmarked else None
    builder.open_part(PART_ONDERDEEL, "onder", marker.rstrip(".") or None, depth, term)
    _add_paragraphs(builder, body)


def _add_lid(builder: TextBuilder, lid: ET.Element) -> None:
    """Add one ``lid``: ``1. paragraph`` followed by its list items on new lines."""
    paragraphs = children_named(lid, "al")
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
        body = children_named(li, "al")
        if not body:
            continue
        if paragraphs and not has_onderdelen:  # the paragraphs lead up to the list
            builder.add_aanhef(aanhef_start, aanhef_end)
        has_onderdelen = True
        _add_item(builder, li, body, depth)
    builder.close_from(0)


def _add_block(builder: TextBuilder, element: ET.Element, depth: int = 1) -> None:
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
        body = children_named(element, "al")
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


@dataclass
class _Paragraph:
    """A paragraph of an article outside its leden: its span and the term it defines."""

    start: int
    end: int
    term: str | None
    lead: str | None = (
        None  # the stand-in id of a definition paragraph with its own list
    )


def _article_text(
    article: ET.Element,
) -> tuple[str, list[Reference], list[ArticlePart]]:
    """Article text in document order: leden as ``1. text``, other paragraphs and
    list items on their own lines. A paragraph next to the leden (for example
    "Dit artikel is nog niet in werking getreden") is part of the article.

    Also the offsets of the leden, onderdelen and aanhef in that text, and of the references.
    An article without leden but with a list has the paragraphs before it as its aanhef; a
    paragraph that is only a term ("adviseren:") holds the list after it."""
    builder = TextBuilder()
    children = [c for c in article if local_name(c.tag) not in ("kop", "meta-data")]
    first_list = next(
        (i for i, c in enumerate(children) if local_name(c.tag) == "lijst"), None
    )
    has_leden = any(local_name(c.tag) == "lid" for c in children)
    intro: list[_Paragraph] = []  # the paragraphs before the list
    loose: list[_Paragraph] = []  # the other paragraphs outside the leden
    for index, child in enumerate(children):
        start = builder.length
        name = local_name(child.tag)
        if name == "lid":
            _add_lid(builder, child)
            continue
        lead_term = _leads_list(children, index) if name == "al" else None
        _add_block(builder, child)
        if name == "lijst":
            builder.close_from(0)  # the definition paragraph that led it, if any
        if name != "al":
            continue
        paragraph = _Paragraph(start, builder.length, leading_term(child))
        if lead_term:
            paragraph.lead = f"\0{index}"
            builder.open_lead(paragraph.lead, start, lead_term)
        before_list = first_list is not None and index < first_list
        intro_ = not has_leden and before_list and not lead_term
        (intro if intro_ else loose).append(paragraph)
    if intro and any(part.kind == PART_ONDERDEEL for part in builder.structure):
        builder.add_aanhef(intro[0].start, intro[-1].end)
    else:
        loose = intro + loose
    builder.close_from(0)
    if builder.structure:
        _number_teksten(builder, loose)
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


def _number_teksten(builder: TextBuilder, paragraphs: list[_Paragraph]) -> None:
    """Make the paragraphs outside the other parts ``tekst-1``, ``tekst-2`` in text order; a
    definition paragraph with its own list is a part already, under its stand-in id, which
    it and its onderdelen trade for its number."""
    ids: dict[str, str] = {}
    for number, paragraph in enumerate(paragraphs, start=1):
        ident = f"{PART_TEKST}-{number}"
        if paragraph.lead:
            ids[paragraph.lead] = ident
            continue
        builder.structure.append(
            ArticlePart(
                ident, PART_TEKST, None, paragraph.start, paragraph.end, paragraph.term
            )
        )
    if not ids:
        return
    builder.structure = [
        replace(part, id=ids[head] + part.id[len(head) :])
        if (head := part.id.split("-", 1)[0]) in ids
        else part
        for part in builder.structure
    ]


def _crumb(division: ET.Element, name: str) -> Crumb:
    """The label and title of a division, from its ``label`` and its ``<kop>``."""
    kop = child_named(division, "kop")
    label = division.get("label")
    if not label:
        label = " ".join(
            filter(
                None,
                (text_of(child_named(kop, "label")), text_of(child_named(kop, "nr"))),
            )
        )
    title = collapse_ws(text_of(child_named(kop, "titel")))
    return Crumb(type=name, label=label or None, title=title or None)


def _annex_number(annex: ET.Element) -> str | None:
    """The number of a ``<bijlage>`` as the JCI writes it: ``2`` of ``Bijlage 2``."""
    kop = child_named(annex, "kop")
    nr = text_of(child_named(kop, "nr"))
    if nr:
        return nr
    label = (annex.get("label") or "").strip()
    rest = (
        label[len("bijlage") :].strip() if label.lower().startswith("bijlage") else ""
    )
    return rest or None


class ArticleHead:
    """An article of a toestand before its text is read: the ids that name its version and
    the divisions it stands in. Reading the text, references and parts of every article is
    most of the cost of a toestand, and a reader of many toestanden of one law needs them
    only for the versions it has not met yet (``article``, read once)."""

    __slots__ = ("_annex", "_article", "_element", "breadcrumb", "stam_id", "versie_id")

    def __init__(
        self, element: ET.Element, breadcrumb: tuple[Crumb, ...], annex: str | None
    ) -> None:
        self._element = element
        self._annex = annex
        self._article: ArticleXml | None = None
        self.breadcrumb = breadcrumb
        self.stam_id = element.get("stam-id")
        self.versie_id = element.get("versie-id")

    @property
    def article(self) -> ArticleXml:
        if self._article is None:
            self._article = _parse_article(self._element, self.breadcrumb, self._annex)
        return self._article


def _article_heads(
    element: ET.Element,
    breadcrumb: tuple[Crumb, ...] = (),
    annex: str | None = None,
) -> Iterator[ArticleHead]:
    """The articles under *element* in document order, each with the divisions it is in
    and, in an annex, the number of that annex."""
    for child in element:
        name = local_name(child.tag)
        if name == "artikel":
            yield ArticleHead(child, breadcrumb, annex)
        elif name == "bijlage":
            crumb = _crumb(child, name)
            yield from _article_heads(child, (*breadcrumb, crumb), _annex_number(child))
        elif name in DIVISIONS:
            yield from _article_heads(child, (*breadcrumb, _crumb(child, name)), annex)
        else:
            yield from _article_heads(child, breadcrumb, annex)


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
        heading=_article_title(article),
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


def _implemented(root: ET.Element) -> tuple[str, ...]:
    """The EU acts the clauses of the ``considerans`` say the regulation implements."""
    clauses = [
        collapse_ws(_flatten(para).text)
        for considerans in iter_named(root, "considerans")
        for para in considerans.iter()
        if local_name(para.tag) == "considerans.al"
    ]
    return tuple(implemented_acts(clauses))


# ── entry point ──────────────────────────────────────────────────────────────


def _title(root: ET.Element, name: str) -> str | None:
    """Whitespace-collapsed text of the first ``<name>``, ignoring its ``meta-data``."""
    element = next(iter_named(root, name), None)
    if element is None:
        return None
    return collapse_ws(_flatten(element).text) or None


def parse_toestand(xml_text: str) -> ToestandXml:
    """Parse the XML of one toestand. Raises ``ET.ParseError`` on malformed XML."""
    toestand, heads = read_toestand(xml_text)
    return replace(toestand, articles=tuple(head.article for head in heads))


def read_toestand(xml_text: str) -> tuple[ToestandXml, tuple[ArticleHead, ...]]:
    """The toestand without its articles, and its articles unread (``ArticleHead``), in
    document order. Raises ``ET.ParseError`` on malformed XML."""
    root = ET.fromstring(xml_text)
    wetgeving = next(iter_named(root, "wetgeving"), None)
    heads = tuple(_article_heads(root))
    enacted, enacted_in_force = _enactment(root)
    toestand = ToestandXml(
        bwb_id=root.get("bwb-id"),
        kind=wetgeving.get("soort") if wetgeving is not None else None,
        treaty_number=(wetgeving.get("verdragnummer") or None)
        if wetgeving is not None
        else None,
        title=_title(root, "citeertitel") or _title(root, "intitule"),
        official_title=_title(root, "intitule"),
        citation_title=_title(root, "citeertitel"),
        valid_from=root.get("inwerkingtreding"),
        enacted=enacted,
        enacted_in_force=enacted_in_force,
        basis=_basis(root),
        implements=_implemented(root),
        annexes=parse_annexes(root),
    )
    return toestand, heads


# ── node props (pure builders shared by the normalize pipelines) ─────────────


def _drop_none(props: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if v is not None}


_CELEX_LINK = re.compile(
    r'<extref\b[^>]*\bdoc="(3\d{4}[A-Za-z]\d{4})"[^>]*>(.*?)</extref>', re.DOTALL
)
_TAGS_AND_SPACE_AT_A_SLASH = re.compile(rf"{XML_TAG_RE.pattern}|\s+(?=/)|(?<=/)\s+")


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


def expiry_date(end_date: str | None, read_at: str | None) -> str | None:
    """The first day a regulation is no longer in force (repealed or lapsed), from the SRU
    record of the toestand that counted as current when it was read at *read_at*: the day
    after its ``geldigheidsperiode_einddatum`` (*end_date*) when that had passed by then.
    None while the regulation is in force: its current toestand runs to 9999-12-31, or to
    the day before a toestand still to come. Of a repealed regulation the current toestand
    is the last there was (``BWBClient``): the Huurwet's ran to 2003-07-31, so it expired on
    2003-08-01."""
    try:
        end = dt.date.fromisoformat(str(end_date or "")[:10])
        read = dt.date.fromisoformat(str(read_at or "")[:10])
    except ValueError:
        return None
    return (end + dt.timedelta(days=1)).isoformat() if end < read else None


def instrument_props(
    toestand: ToestandXml,
    bwb_id: str,
    *,
    celex_refs: Iterable[str] = (),
    date_expired: str | None = None,
) -> dict[str, Any]:
    """Props of the Instrument node for a regulation.

    ``basis``, ``celex_refs`` (the EU acts the text names) and ``implements_celex`` (those
    its considerans says it implements) are what the semantic steps link from (BASED_ON,
    IMPLEMENTS, REFERS_TO): kept here, where the toestand is parsed anyway, so they do not
    read and parse every toestand again. They are always written: an empty list replaces a
    stale one. ``enacted_publication`` is the id of the publication that enacted it
    (``stb-2018-144``).

    ``date_signed``, ``date_published``, ``date_in_force`` and ``dossier_numbers`` are those
    of the regulation as it was enacted (``ToestandXml.enacted``), always written (null or
    empty when the toestand does not say them); ``version_date_in_force`` is the start of
    the toestand. ``date_expired`` (``expiry_date``) is always written, null for a
    regulation in force.
    """
    enacted = toestand.enacted
    title = toestand.title or f"BWB-regeling {bwb_id}"
    props = _drop_none(
        {
            "basis": [
                {"bwb_id": r.bwb_id, "article": r.article, "doc": r.doc, "text": r.text}
                for r in toestand.basis
            ],
            "celex_refs": sorted(set(celex_refs)),
            "implements_celex": sorted(toestand.implements),
            "source": SOURCE_BWB,
            "bwb_id": bwb_id,
            "title": title,
            "official_title": toestand.official_title,
            "citation_title": toestand.citation_title,
            "display_name": title,
            "kind": toestand.kind,
            "treaty_number": toestand.treaty_number,
            "jurisdiction": "nl",
            "version_date_in_force": toestand.valid_from,
        }
    )
    return {
        **props,
        "date_signed": enacted.signed if enacted else None,
        "date_published": enacted.published if enacted else None,
        "date_in_force": toestand.enacted_in_force,
        "date_expired": date_expired,
        "dossier_numbers": list(enacted.dossiers) if enacted else [],
        "enacted_publication": (enacted.identifier or None) if enacted else None,
    }


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
            "heading": article.heading,
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
            "heading": article.heading,
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
