"""Parse a BWB *toestand* (one dated version of a regulation) — pure, no I/O.

The BWB XML already says most of what we need, so we read it instead of guessing:

* every ``<artikel>`` (``<enig-artikel>`` in a regulation of one article) has a stable
  identity across versions (``stam-id``), a version id (``versie-id``), the date it
  entered into force (``inwerking``) and the publication that created this version
  (``bron`` such as ``Stb.2019-33``) together with its ``effect`` (nieuw / wijziging /
  vervallen …);
* ``<meta-data><brondata>`` names the originating and the commencement
  publication, each optionally with ``<dossierref dossier="35786">`` — the
  parliamentary dossier of the amending bill;
* references in the text are ``<extref>`` / ``<intref>`` with a machine-readable
  ``doc="jci1.3:c:BWBR0001854&artikel=287"``;
* the preamble (``<aanhef>/<considerans>``) lists the legal basis in the
  paragraph that starts with "Gelet op" (``bevat="grondslag"``, also on the paragraphs it
  runs on into), or a law in a clause "Alzo Wij …, dat ingevolge artikel 133 van de Grondwet
  …", again as ``<extref>``; the whole ``<aanhef>`` is read as a text of its own
  (``PreambleXml``);
* an annex (``<bijlage>``) has a heading of its own (``Bijlage 1``, ``Lijst Ia``) and its
  text is read as that of an article (``AnnexXml``), without the articles it holds.

Text offsets of references, of the structure of the article (``ArticleXml.parts``: aanhef,
leden, onderdelen), of its tables (``ArticleXml.tables``) and of its headings
(``ArticleXml.headings``) and the markers of its footnotes (``ArticleXml.footnote_marks``)
refer to ``ArticleXml.text`` (same string). A footnote the XML writes where its marker
stands (``<noot>``) is no text of the article but one of ``ArticleXml.footnotes``.
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from lawgraph.config.constants import COLLECTION_INSTRUMENTS, SOURCE_BWB
from lawgraph.core.annex_xml import (
    NOTE,
    annex_node_key,
    extract_description,
    extract_entries,
    extract_kop,
    extract_name,
    words_without_notes,
)
from lawgraph.core.eu_citations import implemented_acts
from lawgraph.core.identifiers import (
    find_celex_ids,
    has_possible_year,
    is_bwb_id,
    rebuilt_celex,
)
from lawgraph.core.models import make_node_key, node_id
from lawgraph.core.publications import koop_id, publication_citation, publication_series
from lawgraph.core.qualifiers import Qualifier, parse_qualifier, part_slug
from lawgraph.core.text_tables import TextTable, read_cals
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

# The one article of a regulation that has only one: ``<enig-artikel>`` where an article is
# ``<artikel>``, without a ``<kop>`` or a number, at ``/Enig-artikel`` (wetten.overheid.nl
# ``#Enig-artikel``; the JCI has no address for it). The graph numbers it as the source
# names it, so its key, its address and its readable address follow from its number.
ENIG_ARTIKEL = "enig-artikel"
ENIG_ARTIKEL_LABEL = "Enig artikel"
# The elements of the toestand XML that are an article.
ARTICLE_ELEMENTS = frozenset({"artikel", ENIG_ARTIKEL})


def named_number(number: str) -> str | None:
    """The label of an article whose number is a name, as the source prints it: ``Enig
    artikel`` for ``enig-artikel``; None for a number."""
    return ENIG_ARTIKEL_LABEL if number == ENIG_ARTIKEL else None


def article_label(number: str) -> str:
    """``Artikel 287``; ``Artikel 9 van bijlage 2`` for an article of an annex; ``Enig
    artikel`` for the one article of a regulation (``named_number``)."""
    if named := named_number(number):
        return named
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
    # The EU act of a link of ``reeks="Celex"``: its CELEX number
    celex: str | None = None
    # The ``bwb-ng-variabel-deel`` of a link to an annex (``/Bijlage_1``), whose ``doc`` is
    # empty
    part: str | None = None
    # The footnote it stands in (its place in ``footnotes``): ``start`` and ``end`` are then
    # offsets into the text of that footnote; None for a reference of the text itself
    footnote: int | None = None

    def to_dict(self, annex: str | None = None) -> dict[str, Any]:
        """JSON-able form stored in ``props.references``; *annex* the key of the annex it
        names. ``celex``, ``annex`` and ``footnote`` only when it has one."""
        extra = {"celex": self.celex, "annex": annex}
        return {
            "kind": self.kind,
            "bwb_id": self.bwb_id,
            "article": self.article,
            "doc": self.doc,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            **self.qualifier.to_dict(),
            **{name: value for name, value in extra.items() if value},
            **({"footnote": self.footnote} if self.footnote is not None else {}),
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
class Heading:
    """A heading in the text of an article, as a span of ``ArticleXml.text``, on a line of
    its own: a ``<tussenkop>`` ("Artikel 17" in the one article of BWBR0007846) or the
    ``<title>`` of a table ("Tabel 1. Vereiste diploma's")."""

    start: int
    end: int

    def to_dict(self) -> dict[str, int]:
        """JSON-able form stored in ``props.headings``."""
        return {"start": self.start, "end": self.end}


@dataclass(frozen=True)
class FootnoteMark:
    """Where the marker of a footnote stood in the text of an article (``<sup>1</sup>``
    after "Richtlijn (EU) 2019/944"): ``text[:at]`` the words before it. The marker is no
    character of the text. The footnote itself is a paragraph of the text that opens with
    its number ("1 Richtlijn (EU) 2019/944 van het Europees Parlement …"), or, for a
    ``<noot>``, the one of ``footnotes`` at ``footnote``."""

    at: int
    number: str  # "1"; a marker printed ``1)`` is footnote 1
    footnote: int | None = None  # of a ``<noot>``: its place in ``footnotes``

    def to_dict(self) -> dict[str, Any]:
        """JSON-able form stored in ``props.footnote_marks``."""
        if self.footnote is None:
            return {"at": self.at, "number": self.number}
        return {"at": self.at, "number": self.number, "footnote": self.footnote}


@dataclass(frozen=True)
class Footnote:
    """A footnote the XML writes where its marker stands (``<noot>``): its number as its
    ``<noot.nr>`` prints it, without brackets (``1)`` is 1; empty without one), and its text
    (its ``<noot.al>``, a paragraph a line), with the links in it as offsets into ``text``."""

    number: str
    text: str
    references: tuple[Reference, ...] = ()

    def to_dict(self) -> dict[str, str]:
        """JSON-able form stored in ``props.footnotes``."""
        return {"number": self.number, "text": self.text}


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
    tables: tuple[TextTable, ...] = ()
    headings: tuple[Heading, ...] = ()
    footnote_marks: tuple[FootnoteMark, ...] = ()
    # its ``<noot>`` footnotes in document order, those of its heading first
    footnotes: tuple[Footnote, ...] = ()

    @property
    def is_repealed(self) -> bool:
        return effect_kind(self.effect) == EFFECT_REPEALS


@dataclass(frozen=True)
class AnnexXml:
    """A ``<bijlage>`` of a toestand. Its text is read as that of an article (offsets of its
    references, parts, tables and headings into ``text``), without its articles, which are
    articles of their own (``bijlage 2 artikel 9``)."""

    label: str | None  # "I", "2"; None for the one annex of a regulation
    # as its heading prints it: "Bijlage 1", "Lijst Ia"
    name: str
    title: str | None
    description: str | None
    entries: tuple[dict[str, Any], ...]
    # its ``bwb-ng-variabel-deel`` (``/Bijlage_1``): what a link to it names
    path: str | None = None
    text: str = ""
    references: tuple[Reference, ...] = ()
    parts: tuple[ArticlePart, ...] = ()
    tables: tuple[TextTable, ...] = ()
    headings: tuple[Heading, ...] = ()
    footnote_marks: tuple[FootnoteMark, ...] = ()
    footnotes: tuple[Footnote, ...] = ()


# The part of an aanhef that is a paragraph of its considerans stating the legal basis
PREAMBLE_GELET_OP = "gelet_op"


@dataclass(frozen=True)
class PreamblePart:
    """A block of the aanhef, as a span of ``PreambleXml.text``: ``kind`` is the element it
    is, as the XML names it (``wij``, ``wie``, ``considerans``, ``afkondiging``,
    ``preambule``), or ``gelet_op``: the text of the considerans that states the legal
    basis (``_basis_spans``), inside it. The parts are listed by ``start``, a block before the
    ``gelet_op`` inside it."""

    kind: str
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        """JSON-able form stored in ``props.preamble.parts``."""
        return {"kind": self.kind, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class PreambleXml:
    """The ``<aanhef>`` of a regulation: who enacts it, its considerans ("Gelet op …") and
    its afkondiging ("Besluit:"). A paragraph a line; ``parts`` its blocks and
    ``references`` its links, offsets into ``text``."""

    text: str
    parts: tuple[PreamblePart, ...] = ()
    references: tuple[Reference, ...] = ()


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
    # the text of its considerans that states the basis: a law it names without a link is read
    basis_preamble: str = ""
    # the EU acts its considerans says it implements (CELEX numbers), see ``implemented_acts``
    implements: tuple[str, ...] = ()
    preamble: PreambleXml | None = None
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
        self.tables: list[TextTable] = []
        self.headings: list[Heading] = []
        # the numbers of the footnotes of the article (``_footnote_numbers``): a ``<sup>``
        # of one of them in a paragraph is its marker, a mark, not text
        self.footnotes: frozenset[str] = frozenset()
        self.marks: list[FootnoteMark] = []
        # its ``<noot>`` footnotes, in document order
        self.notes: list[Footnote] = []
        self._open: list[_OpenPart] = []
        self._siblings: dict[tuple[str, str], list[str]] = {}

    def add(self, text: str) -> None:
        self.parts.append(text)
        self.length += len(text)

    def inline(self, element: ET.Element, *, one_line: bool = False) -> None:
        """Append the (stripped) inline text of *element*, tracking its references;
        *one_line*: its line breaks and tabs as spaces (the text of a table cell)."""
        raw = _flatten(element, self.footnotes)
        text = raw.text.strip()
        if one_line:
            text = text.translate(_ONE_LINE)  # one character for one: the offsets hold
        lead = len(raw.text) - len(raw.text.lstrip())
        base = self.length
        for ref in raw.refs:
            start, end = ref.start - lead, ref.end - lead
            if start < 0 or end > len(text):
                continue  # reference fell into stripped whitespace
            self.refs.append(replace(ref, start=base + start, end=base + end))
        # a marker in the whitespace around the text stands at its edge ("Dalfsen <noot>")
        self.marks.extend(
            replace(
                mark,
                at=base + min(max(mark.at - lead, 0), len(text)),
                footnote=None
                if mark.footnote is None
                else len(self.notes) + mark.footnote,
            )
            for mark in raw.marks
        )
        self.notes.extend(raw.notes)
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


_ONE_LINE = str.maketrans("\n\t\r", "   ")


@dataclass
class _Flat:
    text: str
    refs: list[Reference]
    marks: list[FootnoteMark] = field(default_factory=list)
    notes: list[Footnote] = field(default_factory=list)


def _footnote_number(marker: ET.Element | None) -> str:
    """The number of a footnote as its ``<sup>`` or ``<noot.nr>`` prints it, without
    brackets: ``1)`` and ``1.`` are 1."""
    return text_of(marker).strip("(). ")


def _note_lines(noot: ET.Element) -> Iterator[list[ET.Element]]:
    """The lines of a ``<noot>``: each ``<noot.al>``, and each item of a list in it
    (``<noot.li>``) its marker and its paragraphs."""
    for child in noot:
        name = local_name(child.tag)
        if name == "noot.al":
            yield [child]
        elif name == "noot.lijst":
            for li in iter_named(child, "noot.li"):
                marker = child_named(li, "li.nr")
                yield [
                    *([marker] if marker is not None else []),
                    *children_named(li, "noot.al"),
                ]


def _note(noot: ET.Element) -> Footnote:
    """The footnote of a ``<noot>``: its number and its lines, the pieces of a line
    separated by a space."""
    builder = TextBuilder()
    for line in _note_lines(noot):
        if builder.length:
            builder.add("\n")
        for index, piece in enumerate(line):
            if index:
                builder.add(" ")
            builder.inline(piece)
    return Footnote(
        _footnote_number(child_named(noot, "noot.nr")),
        builder.value(),
        tuple(builder.refs),
    )


def _opens_with(paragraph: ET.Element) -> ET.Element | None:
    """The element *paragraph* opens with, when no text stands before it."""
    first = next(iter(paragraph), None)
    return None if (paragraph.text or "").strip() else first


def _footnote_numbers(element: ET.Element) -> frozenset[str]:
    """The numbers of the footnotes under *element*: each a paragraph that opens with its
    number in a ``<sup>`` ("<al><sup>1</sup> Richtlijn (EU) 2019/944 …</al>")."""
    return frozenset(
        _footnote_number(first)
        for paragraph in iter_named(element, "al")
        if (first := _opens_with(paragraph)) is not None
        and local_name(first.tag) == "sup"
    )


# The ``bwb-ng-variabel-deel`` of an annex: ``/Bijlage``, ``/Bijlage_2``, ``/BijlageA``
_ANNEX_PART = re.compile(r"^/Bijlage[^/]*$")


def _linked_celex(link: ET.Element, doc: str, text: str) -> str | None:
    """The CELEX number of a link to an EU act (``reeks="Celex"``): its ``doc``, or, with an
    impossible year, the number rebuilt from the text of the link (``rebuilt_celex``)."""
    if link.get("reeks") != "Celex" or find_celex_ids(doc) != [doc.upper()]:
        return None
    celex = doc.upper()
    return celex if has_possible_year(celex) else rebuilt_celex(celex, text)


# A line break in the text of an element and the indent around it: the layout of the XML
# (``<al>\n    <sup>1</sup>\n    <extref>``), which prints as a space.
_LAYOUT = re.compile(r"\s*\n\s*")


def _unlaid(text: str) -> str:
    """*text* without the layout of the XML: each line break a space."""
    return _LAYOUT.sub(" ", text)


def _flatten(element: ET.Element, footnotes: frozenset[str] = frozenset()) -> _Flat:
    """Concatenate all text of *element*, a line break of its layout a space; note reference
    offsets (unstripped). A ``<sup>`` of one of *footnotes* is the marker of that footnote,
    noted as a mark and no text, unless a paragraph opens with it (the footnote itself). A
    ``<noot>`` is a mark and a footnote of its own (``_note``), no text."""
    out: list[str] = []
    refs: list[Reference] = []
    marks: list[FootnoteMark] = []
    notes: list[Footnote] = []
    length = 0

    def walk(node: ET.Element, opens: bool = False) -> None:
        nonlocal length
        name = local_name(node.tag)
        if name == "meta-data":
            return
        if name == "sup" and not opens and _footnote_number(node) in footnotes:
            marks.append(FootnoteMark(length, _footnote_number(node)))
            return
        if name == NOTE:
            note = _note(node)
            marks.append(FootnoteMark(length, note.number, footnote=len(notes)))
            notes.append(note)
            return
        start = length
        if node.text:
            text = _unlaid(node.text)
            out.append(text)
            length += len(text)
        first = _opens_with(node) if name == "al" else None
        for child in node:
            walk(child, child is first)
            if child.tail:
                tail = _unlaid(child.tail)
                out.append(tail)
                length += len(tail)
        if name in ("extref", "intref"):
            doc = node.get("doc") or ""
            jci = parse_jci(doc)
            bwb_id = node.get("bwb-id") or jci.bwb_id
            text = "".join(out)[start:length]
            part = node.get("bwb-ng-variabel-deel") or ""
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
                    celex=_linked_celex(node, doc, text),
                    part=part if _ANNEX_PART.match(part) else None,
                )
            )

    walk(element)
    return _Flat("".join(out), refs, marks, notes)


def _article_number(article: ET.Element) -> str | None:
    if local_name(article.tag) == ENIG_ARTIKEL:
        return ENIG_ARTIKEL
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
    """The number of an ``<artikel>`` ("1:1"), from its ``kop`` or its ``label``;
    ``ENIG_ARTIKEL`` for an ``<enig-artikel>``."""
    return _article_number(article)


def _article_title(article: ET.Element) -> str | None:
    """The ``<titel>`` of the ``<kop>`` of an article ("Definities"), whitespace collapsed,
    without its footnote (a ``<noot>``, one of the article's ``footnotes``)."""
    kop = child_named(article, "kop")
    return words_without_notes(child_named(kop, "titel")) or None


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


# The elements laid out as a table: a CALS ``<table>``, and the lists of an item and its
# value: ``<specificatielijst>`` (a distance and its amount, BWBR0007846) and
# ``<definitielijst>`` (a term and what it means), each item a row.
_TABULAR = frozenset({"table", "specificatielijst", "definitielijst"})
_HEADING = "tussenkop"
# The elements of an article, a lid or a list item that hold its text, besides its lists:
# its paragraphs, its headings and its tables.
_BLOCKS = frozenset({"al", _HEADING, *_TABULAR})
# Elements that only group blocks (and lists): what they hold is read as if it stood in
# the element that holds them.
_GROUPS = frozenset({"al-groep", "citaat"})
# The cells of a row of each list laid out as a table: its items, and per item its cells.
_ITEM_CELLS = {
    "specificatielijst": ("specificatie-item", ("specificatie", "waarde")),
    "definitielijst": ("definitie-item", ("term", "definitie")),
}


def _children(element: ET.Element) -> Iterator[ET.Element]:
    """The children of *element*, those of a group as if they stood in *element*."""
    for child in element:
        if local_name(child.tag) in _GROUPS:
            yield from _children(child)
        else:
            yield child


def _holds_items(element: ET.Element) -> bool:
    """Whether list items stand under *element*, not in a table (the text of its cells)."""
    return any(
        local_name(child.tag) == "li"
        or (local_name(child.tag) not in _TABULAR and _holds_items(child))
        for child in element
    )


# What a lid or a list item holds after its first list, in document order: a list (a
# child that holds list items) or the blocks between two lists or after the last.
_Piece = ET.Element | list[ET.Element]


def _sections(element: ET.Element) -> tuple[list[ET.Element], list[_Piece]]:
    """The blocks of *element* (a lid, a list item) before its first list, and what
    follows them (``_Piece``)."""
    lead: list[ET.Element] = []
    rest: list[_Piece] = []
    for child in _children(element):
        if local_name(child.tag) in _BLOCKS:
            if not rest:
                lead.append(child)
            elif isinstance(rest[-1], list):
                rest[-1].append(child)
            else:
                rest.append([child])
        elif _holds_items(child):
            rest.append(child)
    return lead, rest


def _holds_list(li: ET.Element) -> bool:
    """Whether a list item holds a list of its own (``aa.`` and its 1° to 4°)."""
    return any(
        local_name(child.tag) == "lijst"
        for child in _children(li)
        if local_name(child.tag) not in _BLOCKS
    )


def _add_heading(builder: TextBuilder, element: ET.Element) -> None:
    """Add the text of a heading and remember where it is."""
    start = builder.length
    builder.inline(element, one_line=True)
    if builder.length > start:
        builder.headings.append(Heading(start, builder.length))


def _add_paragraphs(builder: TextBuilder, blocks: list[ET.Element]) -> None:
    """Add *blocks*: paragraphs separated by a space; a heading, a table and what follows
    them on lines of their own."""
    own_line = False
    for index, block in enumerate(blocks):
        name = local_name(block.tag)
        if name in _TABULAR:
            _add_tabular(builder, block)
            own_line = True
            continue
        if index:
            builder.add("\n" if own_line or name == _HEADING else " ")
        own_line = name == _HEADING
        if own_line:
            _add_heading(builder, block)
        else:
            builder.inline(block)


def _add_cell(builder: TextBuilder, entry: ET.Element) -> None:
    """The paragraphs of a table cell and the markers of the list items among them, on one
    line separated by a space; a cell of text without paragraphs (the ``<waarde>`` of a
    specificatielijst) its text."""
    pieces = [e for e in entry.iter() if local_name(e.tag) in ("al", "li.nr")]
    if not pieces:
        builder.inline(entry, one_line=True)
    for index, piece in enumerate(pieces):
        if index:
            builder.add(" ")
        builder.inline(piece, one_line=True)


def _add_tabular(builder: TextBuilder, element: ET.Element) -> None:
    """Add a table, a specificatielijst or a definitielijst."""
    name = local_name(element.tag)
    if name == "table":
        _add_table(builder, element)
    else:
        _add_item_table(builder, element, *_ITEM_CELLS[name])


def _add_item_table(
    builder: TextBuilder, element: ET.Element, item: str, cells: tuple[str, str]
) -> None:
    """Add a list of an item and its value as a table without a header: an item a row, its
    marker (when the list has them) and its cells separated by a tab."""
    items = children_named(element, item)
    if not items:
        return
    markers = [text_of(child_named(entry, "li.nr")) for entry in items]
    if builder.parts:
        builder.add("\n")
    start = builder.length
    for index, (entry, marker) in enumerate(zip(items, markers, strict=True)):
        if index:
            builder.add("\n")
        if any(markers):
            builder.add(f"{marker}\t")
        for cell, name in enumerate(cells):
            if cell:
                builder.add("\t")
            content = child_named(entry, name)
            if content is not None:
                _add_cell(builder, content)
    builder.tables.append(
        TextTable(
            start=start,
            end=builder.length,
            head_rows=0,
            columns=len(cells) + (1 if any(markers) else 0),
        )
    )


def _add_table(builder: TextBuilder, table: ET.Element) -> None:
    """Add a CALS table on lines of its own: its title (a heading), then a row a line, its
    cells separated by a tab."""
    cals = read_cals(table)
    if cals is None:
        return
    if builder.parts:
        builder.add("\n")
    if cals.title is not None:
        _add_heading(builder, cals.title)
        builder.add("\n")
    start = builder.length
    for index, row in enumerate(cals.rows):
        if index:
            builder.add("\n")
        for place, cell in enumerate(row.cells):
            if place:
                builder.add("\t")
            _add_cell(builder, cell.entry)
    builder.tables.append(cals.text_table(start, builder.length))


def _add_after_list(builder: TextBuilder, blocks: list[ET.Element], depth: int) -> None:
    """Add the *blocks* after a list on a new line: the list items at *depth* and deeper
    end before them. An empty paragraph (``<al/>`` after the list) is nothing."""
    blocks = [
        block
        for block in blocks
        if local_name(block.tag) in _TABULAR or "".join(block.itertext()).strip()
    ]
    if not blocks:
        return
    builder.close_from(depth)
    if local_name(blocks[0].tag) not in _TABULAR:  # a table starts its own line
        builder.add("\n")
    _add_paragraphs(builder, blocks)


def _add_item(
    builder: TextBuilder, li: ET.Element, body: list[ET.Element], depth: int
) -> None:
    """Add one list item on a new line: its marker (``a.``, ``1°.``) and *body*, its
    paragraphs before a list of its own; an item of only a list of its own (``aa.``) its
    marker, the part that holds that list."""
    # The item before it ends here, not after the marker of this one.
    builder.close_from(depth)
    builder.add("\n")
    marker = text_of(child_named(li, "li.nr"))
    if marker:
        builder.add(f"{marker} " if body else marker)
    unmarked = not any(char.isalnum() for char in marker)
    term = leading_term(body[0]) if unmarked and body else None
    builder.open_part(PART_ONDERDEEL, "onder", marker.rstrip(".") or None, depth, term)
    _add_paragraphs(builder, body)


def _add_list(builder: TextBuilder, element: ET.Element, depth: int) -> bool:
    """Add the list items under *element* (a list) in document order, *depth* deep;
    whether one of them is a part."""
    added = False
    for child in element:
        name = local_name(child.tag)
        if name == "li":
            added = _add_list_item(builder, child, depth) or added
        elif name not in _TABULAR:
            added = _add_list(builder, child, depth) or added
    return added


def _add_list_item(builder: TextBuilder, li: ET.Element, depth: int) -> bool:
    """Add a list item, then its own lists and the paragraphs after them; whether it is a
    part (an item without text or list is none)."""
    body, rest = _sections(li)
    added = bool(body) or _holds_list(li)
    if added:
        _add_item(builder, li, body, depth)
    _add_rest(builder, rest, depth + 1)
    return added


def _add_rest(builder: TextBuilder, rest: list[_Piece], depth: int) -> bool:
    """Add what follows the first list of a lid or list item (``_sections``), its list
    items *depth* deep; whether one of them is a part."""
    added = False
    for piece in rest:
        if isinstance(piece, list):
            _add_after_list(builder, piece, depth)
        else:
            added = _add_list(builder, piece, depth) or added
    return added


def _add_lid(builder: TextBuilder, lid: ET.Element) -> None:
    """Add one ``lid``: ``1. paragraph`` (and its tables), its list items on new lines and
    the paragraphs after a list on new lines after it."""
    paragraphs, rest = _sections(lid)
    if not paragraphs and not rest:
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
    has_onderdelen = _add_rest(builder, rest, 1)
    builder.close_from(1)
    if has_onderdelen and paragraphs:  # the paragraphs lead up to the list
        builder.add_aanhef(aanhef_start, aanhef_end)
    builder.close_from(0)


def _holds_article(element: ET.Element) -> bool:
    """Whether an article stands in *element*."""
    return any(local_name(node.tag) in ARTICLE_ELEMENTS for node in element.iter())


def _add_division_heading(builder: TextBuilder, division: ET.Element) -> None:
    """Add the heading of a division on a line of its own: the label, number and title of
    its ``<kop>`` ("1.1 Structuurelement A"); a footnote of its title (``<noot>``) a mark at
    the end of the heading."""
    kop = child_named(division, "kop")
    title = child_named(kop, "titel")
    heading = " ".join(
        filter(
            None,
            (
                words_of(child_named(kop, "label")),
                words_of(child_named(kop, "nr")),
                words_without_notes(title),
            ),
        )
    )
    if not heading:
        return
    if builder.parts:
        builder.add("\n")
    builder.headings.append(Heading(builder.length, builder.length + len(heading)))
    builder.add(heading)
    for note in _flatten(title).notes if title is not None else ():
        builder.marks.append(
            FootnoteMark(builder.length, note.number, footnote=len(builder.notes))
        )
        builder.notes.append(note)


def _add_block(builder: TextBuilder, element: ET.Element, depth: int = 1) -> None:
    """Add the law text under *element* (paragraphs and list items) on new lines; a division
    (of an annex) its heading first. An article (of an annex), and a division that holds
    one, is a node of its own: not its text."""
    name = local_name(element.tag)
    if name in ("meta-data", "kop") or name in ARTICLE_ELEMENTS:
        return
    if name in DIVISIONS:
        if _holds_article(element):
            return
        _add_division_heading(builder, element)
    if name in ("al", _HEADING):
        if builder.parts:
            builder.add("\n")
        if name == _HEADING:
            _add_heading(builder, element)
        else:
            builder.inline(element)
        return
    if name in _TABULAR:
        _add_tabular(builder, element)
        return
    if name == "li":
        _add_list_item(builder, element, depth)
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
) -> tuple[
    str,
    list[Reference],
    list[ArticlePart],
    list[TextTable],
    list[Heading],
    list[FootnoteMark],
    list[Footnote],
]:
    """Article text in document order: leden as ``1. text``, other paragraphs and
    list items on their own lines. A paragraph next to the leden (for example
    "Dit artikel is nog niet in werking getreden") is part of the article.

    Also the offsets of the leden, onderdelen and aanhef in that text, and of the references,
    the tables, the headings and the markers of its footnotes (``_footnote_numbers``), and
    its ``<noot>`` footnotes, those of the title of its ``<kop>`` (which have no marker in
    the text) first.
    An article without leden but with a list has the paragraphs before it as its aanhef; a
    paragraph that is only a term ("adviseren:") holds the list after it."""
    builder = TextBuilder()
    builder.footnotes = _footnote_numbers(article)
    title = child_named(child_named(article, "kop"), "titel")
    if title is not None:
        builder.notes.extend(_flatten(title).notes)
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
        if name not in _BLOCKS:
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
    # Stripped, but not into a table: its first or last cell may be empty.
    first = min((table.start for table in builder.tables), default=len(raw))
    lead = first - len(raw[:first].lstrip())
    end = max([len(raw.rstrip()), *(table.end for table in builder.tables)])
    text = raw[lead:end]
    tables = [
        replace(table, start=table.start - lead, end=table.end - lead)
        for table in builder.tables
    ]
    headings = [
        Heading(heading.start - lead, heading.end - lead)
        for heading in builder.headings
        if heading.start >= lead and heading.end - lead <= len(text)
    ]
    refs = [
        replace(ref, start=ref.start - lead, end=ref.end - lead)
        for ref in builder.refs
        if ref.start >= lead and ref.end - lead <= len(text)
    ]
    marks = [
        replace(mark, at=min(max(mark.at - lead, 0), len(text)))
        for mark in builder.marks
    ]
    shifted = (_shift_part(part, raw, lead, len(text)) for part in builder.structure)
    parts = sorted(
        (part for part in shifted if part is not None),
        key=lambda part: (part.start, -part.end),
    )
    return text, refs, parts, tables, headings, marks, builder.notes


def parse_annexes(root: ET.Element) -> tuple[AnnexXml, ...]:
    """The annexes of a toestand in document order, the first of each label."""
    seen: set[str | None] = set()
    annexes = []
    for element in iter_named(root, "bijlage"):
        label, title = extract_kop(element)
        if label in seen:
            continue
        seen.add(label)
        text, refs, parts, tables, headings, marks, notes = _article_text(element)
        annexes.append(
            AnnexXml(
                label=label,
                name=extract_name(element, label),
                title=title,
                description=extract_description(element),
                entries=tuple(extract_entries(element)),
                path=element.get("bwb-ng-variabel-deel") or None,
                text=text,
                references=tuple(refs),
                parts=tuple(parts),
                tables=tuple(tables),
                headings=tuple(headings),
                footnote_marks=tuple(marks),
                footnotes=tuple(notes),
            )
        )
    return tuple(annexes)


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
    title = words_without_notes(child_named(kop, "titel"))
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


def article_heads(
    element: ET.Element,
    breadcrumb: tuple[Crumb, ...] = (),
    annex: str | None = None,
) -> Iterator[ArticleHead]:
    """The articles under *element* in document order, each with the divisions it is in
    and, in an annex, the number of that annex."""
    for child in element:
        name = local_name(child.tag)
        if name in ARTICLE_ELEMENTS:
            yield ArticleHead(child, breadcrumb, annex)
        elif name == "bijlage":
            crumb = _crumb(child, name)
            yield from article_heads(child, (*breadcrumb, crumb), _annex_number(child))
        elif name in DIVISIONS:
            yield from article_heads(child, (*breadcrumb, _crumb(child, name)), annex)
        else:
            yield from article_heads(child, breadcrumb, annex)


def _parse_article(
    article: ET.Element, breadcrumb: tuple[Crumb, ...], annex: str | None
) -> ArticleXml:
    text, refs, parts, tables, headings, marks, notes = _article_text(article)
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
        tables=tuple(tables),
        headings=tuple(headings),
        footnote_marks=tuple(marks),
        footnotes=tuple(notes),
    )


# ── preamble: "Gelet op" ─────────────────────────────────────────────────────

# The words of a considerans that open the references a regulation is issued under: a
# paragraph that starts with "Gelet op", or a clause of another ("Alzo Wij in overweging
# genomen hebben, dat ingevolge artikel 133 van de Grondwet …").
_BASIS_WORDS = ("gelet op", "ingevolge", "ter uitvoering van", "met toepassing van")
_BASIS_WORD = re.compile(
    r"\b(?:" + "|".join(w.replace(" ", r"\s+") for w in _BASIS_WORDS) + r")\b",
    re.IGNORECASE,
)
# Where the clause of a basis word ends: its first reference stands before it.
_CLAUSE_END = re.compile(r";|\bdat\b", re.IGNORECASE)
# What may stand between two references of one list ("de artikelen 6 en 9 en de additionele
# artikelen III en V"); anything else ends the list ("artikel VI van de Grondwet de termijn
# waarna artikel 10 …").
_LIST_GLUE = re.compile(
    r"[\s,]*(?:(?:en|alsmede|op|de|het|artikel(?:en)?|additione(?:el|le))[\s,]+)*",
    re.IGNORECASE,
)
# How a paragraph of the legal basis ends that the next one continues ("…, en").
_RUN_ON = re.compile(r"(?:[,:]|\b(?:en|alsmede|of))$", re.IGNORECASE)
# The BWB marks a paragraph of the considerans by what it holds: ``bevat="grondslag"`` the
# legal basis, ``gehoord``, ``gezien``, ``voordracht`` the others.
_BASIS_MARK = "grondslag"

# A span of the flat text of a paragraph (``_flatten``): start and end.
_Span = tuple[int, int]


def _paragraphs(considerans: ET.Element) -> Iterator[ET.Element]:
    """The paragraphs and lists of a ``considerans``, in order."""
    return (child for child in considerans if local_name(child.tag) != "meta-data")


def _opens_basis(para: ET.Element, text: str) -> bool:
    """A paragraph that is the legal basis as a whole: so marked, or opening with "Gelet
    op"."""
    return para.get("bevat") == _BASIS_MARK or text.lower().startswith("gelet op")


def _runs_on(para: ET.Element, previous: str) -> bool:
    """A paragraph the basis paragraph before it runs on into: that one ends with ",", ":",
    "en", "alsmede" or "of", and this one is not marked as something else."""
    return bool(_RUN_ON.search(previous)) and para.get("bevat") in (None, _BASIS_MARK)


def _clause_spans(flat: _Flat) -> list[_Span]:
    """The spans of a paragraph from a basis word to the end of the list of links that
    follows it in its clause; a basis word without a link in its clause has none."""
    spans: list[_Span] = []
    for match in _BASIS_WORD.finditer(flat.text):
        clause = _CLAUSE_END.search(flat.text, match.end())
        limit = clause.start() if clause else len(flat.text)
        end = None
        for ref in sorted(flat.refs, key=lambda r: r.start):
            if ref.start < match.end():
                continue
            if end is None and ref.start >= limit:
                break
            if end is not None and not _LIST_GLUE.fullmatch(flat.text[end : ref.start]):
                break
            end = ref.end
        if end is not None:
            spans.append((match.start(), end))
    return spans


def _lead(flat: _Flat) -> int:
    """The whitespace a flat text starts with, which ``TextBuilder.inline`` strips."""
    return len(flat.text) - len(flat.text.lstrip())


def _basis_spans(root: ET.Element) -> Iterator[tuple[ET.Element, _Flat, list[_Span]]]:
    """The paragraphs of the ``considerans`` that state the legal basis, each with its flat
    text and the spans of it that do: the whole of a paragraph that is the basis
    (``_opens_basis``) and of each it runs on into, else each clause of a basis word."""
    for considerans in iter_named(root, "considerans"):
        previous: str | None = None  # the text of the basis paragraph before this one
        for para in _paragraphs(considerans):
            flat = _flatten(para)
            text = flat.text.strip()
            whole = _opens_basis(para, text) or (
                previous is not None and _runs_on(para, previous)
            )
            previous = text if whole else None
            lead = _lead(flat)
            spans = [(lead, lead + len(text))] if whole else _clause_spans(flat)
            if spans:
                yield para, flat, spans


def _basis(root: ET.Element) -> tuple[BasisRef, ...]:
    """The links of the spans of the ``considerans`` that state the legal basis."""
    found: dict[tuple[str, str | None], BasisRef] = {}
    for _, flat, spans in _basis_spans(root):
        for ref in flat.refs:
            if ref.kind != "extref" or not ref.bwb_id:
                continue
            if not any(start <= ref.start and ref.end <= end for start, end in spans):
                continue
            found.setdefault(
                (ref.bwb_id, ref.article),
                BasisRef(ref.bwb_id, ref.article, ref.doc, ref.text),
            )
    return tuple(found.values())


def _basis_preamble(root: ET.Element) -> str:
    """The text of the spans that state the legal basis: what names a basis without a
    link."""
    return " ".join(
        collapse_ws(flat.text[start:end])
        for _, flat, spans in _basis_spans(root)
        for start, end in spans
    )


def _implemented(root: ET.Element) -> tuple[str, ...]:
    """The EU acts the clauses of the ``considerans`` say the regulation implements."""
    clauses = [
        collapse_ws(_flatten(para).text)
        for considerans in iter_named(root, "considerans")
        for para in considerans.iter()
        if local_name(para.tag) == "considerans.al"
    ]
    return tuple(implemented_acts(clauses))


# ── preamble: the aanhef as a text ───────────────────────────────────────────

# The elements of an aanhef that are a paragraph of their own: a line of its text.
_PREAMBLE_LINES = frozenset({"al", "considerans.al", "wij", "wie"})


def _preamble_lines(element: ET.Element) -> Iterator[list[ET.Element]]:
    """The lines of a block of the aanhef: each paragraph, and each item of a list its
    marker and its paragraphs; an element with text of its own is a line."""
    name = local_name(element.tag)
    children = [child for child in element if local_name(child.tag) != "meta-data"]
    if name == "li":
        yield children
    elif name in _PREAMBLE_LINES or (element.text or "").strip() or not children:
        yield [element]
    else:
        for child in children:
            yield from _preamble_lines(child)


def _add_preamble_block(
    builder: TextBuilder, block: ET.Element, basis: Mapping[ET.Element, list[_Span]]
) -> list[PreamblePart]:
    """Add the lines of *block* to *builder*: its part, and after it a ``gelet_op`` part for
    each span of a paragraph of it that states the legal basis (*basis*, of
    ``_basis_spans``)."""
    start = None
    inner: list[PreamblePart] = []
    for line in _preamble_lines(block):
        pieces = [piece for piece in line if words_of(piece)]
        if not pieces:
            continue
        if builder.length:
            builder.add("\n")
        line_start = builder.length
        start = line_start if start is None else start
        for index, piece in enumerate(pieces):
            if index:
                builder.add(" ")
            builder.inline(piece)
        inner.extend(_gelet_op_parts(builder, line_start, basis.get(pieces[0], [])))
    if start is None:
        return []
    return [PreamblePart(local_name(block.tag), start, builder.length), *inner]


def _gelet_op_parts(
    builder: TextBuilder, line_start: int, spans: list[_Span]
) -> Iterator[PreamblePart]:
    """The ``gelet_op`` parts of the line from *line_start* on: *spans* of its paragraph,
    offsets into its stripped text (as ``inline`` adds it)."""
    for span_start, span_end in spans:
        yield PreamblePart(
            PREAMBLE_GELET_OP,
            line_start + span_start,
            min(line_start + span_end, builder.length),
        )


def _preamble(root: ET.Element) -> PreambleXml | None:
    """The first ``<aanhef>`` as a text, a block (its child) a part; None without one or
    when it holds no text."""
    aanhef = next(iter_named(root, "aanhef"), None)
    if aanhef is None:
        return None
    basis = {
        para: [(start - _lead(flat), end - _lead(flat)) for start, end in spans]
        for para, flat, spans in _basis_spans(aanhef)
    }
    builder = TextBuilder()
    parts = [
        part
        for block in aanhef
        if local_name(block.tag) != "meta-data"
        for part in _add_preamble_block(builder, block, basis)
    ]
    if not builder.length:
        return None
    return PreambleXml(builder.value(), tuple(parts), tuple(builder.refs))


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
    heads = tuple(article_heads(root))
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
        basis_preamble=_basis_preamble(root),
        implements=_implemented(root),
        preamble=_preamble(root),
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
    regulation in force, and so is ``preamble`` (``preamble_props``), null without one.
    """
    enacted = toestand.enacted
    title = toestand.title or f"BWB-regeling {bwb_id}"
    props = _drop_none(
        {
            "basis": [
                {"bwb_id": r.bwb_id, "article": r.article, "doc": r.doc, "text": r.text}
                for r in toestand.basis
            ],
            "basis_preamble": toestand.basis_preamble,
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
        "preamble": preamble_props(toestand.preamble),
    }


def preamble_props(preamble: PreambleXml | None) -> dict[str, Any] | None:
    """``props.preamble``: its text, its blocks and the links in it that name a regulation
    or an EU act, as the references of an article; None without a preamble."""
    if preamble is None:
        return None
    return {
        "text": preamble.text,
        "parts": [part.to_dict() for part in preamble.parts],
        "references": _references(preamble.references, (), None),
    }


def article_display_name(label: str | None, citation_title: str | None) -> str | None:
    """``Artikel 287 Wetboek van Strafrecht``, ``Algemene bepaling Grondwet``."""
    return " ".join(filter(None, (label, citation_title))) or None


def annex_keys(toestand: ToestandXml, bwb_id: str) -> dict[str, str]:
    """The key of each annex node of the toestand by its ``bwb-ng-variabel-deel``
    (``/Bijlage_1``): what a link to an annex names."""
    return {
        annex.path: annex_node_key(bwb_id, annex.label)
        for annex in toestand.annexes
        if annex.path
    }


def _references(
    references: Iterable[Reference],
    footnotes: Iterable[Footnote],
    annexes: Mapping[str, str] | None,
) -> list[dict[str, Any]]:
    """The references to store of a text and its *footnotes* (each with its ``footnote``):
    those that name a regulation or an EU act, one to an annex with the key of its node
    (*annexes*, ``annex_keys``)."""
    in_notes = (
        replace(reference, footnote=index)
        for index, note in enumerate(footnotes)
        for reference in note.references
    )
    return [
        r.to_dict((annexes or {}).get(r.part or ""))
        for r in (*references, *in_notes)
        if r.bwb_id or r.celex
    ]


def _footnotes(footnotes: Iterable[Footnote]) -> list[dict[str, str]] | None:
    """The ``<noot>`` footnotes to store (``props.footnotes``); None without one."""
    return [note.to_dict() for note in footnotes] or None


def annex_props(
    annex: AnnexXml,
    bwb_id: str,
    citation_title: str | None = None,
    position: int | None = None,
    *,
    annexes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Props of the Annex node; *citation_title* that of its law, which its title cites,
    *position* its place among the annexes of the toestand, *annexes* the keys of those
    annexes (``annex_keys``). Every prop is written, null where it has none: an upsert
    merges props, so a stale value must be overwritten."""
    return {
        "source": SOURCE_BWB,
        "bwb_id": bwb_id,
        "label": annex.label,
        "title": annex.title,
        "display_name": annex.name,
        "position": position,
        "description": annex.description,
        "entries": list(annex.entries) or None,
        "text": annex.text or None,
        "parts": [part.to_dict() for part in annex.parts] or None,
        "tables": [table.to_dict() for table in annex.tables] or None,
        "headings": [heading.to_dict() for heading in annex.headings] or None,
        "footnote_marks": [mark.to_dict() for mark in annex.footnote_marks] or None,
        "footnotes": _footnotes(annex.footnotes),
        "references": _references(annex.references, annex.footnotes, annexes) or None,
        "instrument_id": node_id(COLLECTION_INSTRUMENTS, make_node_key(bwb_id)),
        "instrument_citation_title": citation_title,
    }


def article_props(
    article: ArticleXml,
    bwb_id: str,
    citation_title: str | None,
    position: int,
    *,
    annexes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Props of the (current) Article node; *position* is its place in the toestand,
    *annexes* the keys of its annexes (``annex_keys``). A reference names a regulation or
    an EU act; one to an annex the key of its node."""
    references = _references(article.references, article.footnotes, annexes)
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
            "path": article.path,
            "valid_from": article.valid_from,
            "source_publication": article.source,
            # always written: an upsert merges props, so a stale true must be overwritten
            "repealed": article.is_repealed,
            "parts": [part.to_dict() for part in article.parts],
            "tables": [table.to_dict() for table in article.tables] or None,
            "headings": [heading.to_dict() for heading in article.headings] or None,
            "footnote_marks": [mark.to_dict() for mark in article.footnote_marks]
            or None,
            "footnotes": _footnotes(article.footnotes),
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
            "tables": [table.to_dict() for table in article.tables] or None,
            "headings": [heading.to_dict() for heading in article.headings] or None,
            "footnote_marks": [mark.to_dict() for mark in article.footnote_marks]
            or None,
            "footnotes": _footnotes(article.footnotes),
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
