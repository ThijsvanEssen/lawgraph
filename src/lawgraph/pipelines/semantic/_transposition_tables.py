"""The stored transposition tables, each read and checked against the laws it names: what
``semantic tk-transposition-tables`` writes and ``lawgraph succession-gaps`` reports.

A table comes from what ``retrieve tk-transposition-tables`` stored: a bijlage that is a PDF
of its own (read by ``core.transposition_tables``), or a Kamerstuk with a table in its XML
(read by ``core.transposition_xml``); or it is the concordance table of an EU act that
codifies or recasts others (its HTML as ``retrieve eurlex`` stored it, read by
``core.concordance_html``). The laws of a Kamerstuk's table are found by the names it gives
them. The one law of the BWB of a name is the one of that citation title, else the one of
that abbreviation (the WTI's, as the citation extractor reads "artikel 1 WVO", "artikel 1
Bal"):

* the new law: of that name, the law a publication of the table's dossier enacted or put
  articles in (``LEGISLATED_IN`` the dossier, ``ESTABLISHES`` or ``INTRODUCES`` its
  articles), else the one law of the BWB; a table that names none (``Huidig naar nieuw``),
  the one law of its dossier. A table of the law the paper proposes (``Wetsvoorstel``)
  names it by its column or its dossier's title, a year still open (``Mediawet 20..``)
  standing for any (``bwb_laws_named``): the law of the dossier of such a name, else the
  one law of the dossier, else the one law of the BWB of such a name;
* the old law: the one law of the BWB of that name that is not the new law; a table that
  names none, the one of the new law's name (the current text of a law recodified). Its
  articles are those of its current text and its historical identities (``normalize
  bwb-history``): a table names the articles of its day, also one the law has lost since
  (Woningwet 101a, moved into the Omgevingswet). A table of a proposed law names the old law
  by its column, else by its title (``Tabel 3. Boswet`` over ``Plaats``).

A table with a column per law names both; which is the new law is read from the sources,
not from the order of the columns (``new_column``): the one of them the dossier enacted or put
articles in, else the one the title does not name. A table whose laws are not found places
nothing and says why (``Table.problem``). The tables between the same two laws are checked
together (``Succession``): an article of the old law one table leaves out may be in another.
A place that names another law ("afdeling 3.5 Awb", "16.52 Omgevingswet") is of the law of
that name: the new law when it is its name, else the one law of the BWB of that citation
title, else the law the citation extractor reads in "artikel 1 <name>" ("Awb", "WED").
An article of the old law without a row is a gap only when the old law goes (``_replaced``):
it expired in the BWB no later than the new law came into force, it is recodified as a whole
under its own name, or the EU act of the table repeals it; of a law that stays (the Wet
milieubeheer after the Omgevingswet), or that went only after the new law came into force
(the Wet op het voortgezet onderwijs after the Wet register onderwijsdeelnemers), a table
names only what moves. Nor is it a gap when a table of the old law to another new law has a
row for it (the Monumentenwet 1988 to the Erfgoedwet and to the Omgevingswet); one no table
names is one gap, of the pair that places the most (the Activiteitenbesluit milieubeheer to
the Omgevingswet, the Bal, the Bkl, the Bbl and the Omgevingsbesluit).

The acts of an EU table are its own (the new act) and the one its column names by CELEX
(``core.concordance_html``), each as ``normalize eurlex`` made it; an old act the graph does
not hold places nothing (``retrieve eurlex --mode gaps`` fetches it).
"""

from __future__ import annotations

import base64
import binascii
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

from pypdf.errors import PyPdfError

from lawgraph.config.constants import (
    COLLECTION_DOSSIERS,
    RAW_KIND_TK_TRANSPOSITION_DOCUMENT,
)
from lawgraph.core.aliases import code_choices, curated_abbreviations, instrument_names
from lawgraph.core.citations import DutchCitationExtractor, article_order
from lawgraph.core.concordance_html import read_tables as read_concordance
from lawgraph.core.identifiers import KST_ID_PATTERN
from lawgraph.core.models import make_node_key, node_id
from lawgraph.core.raw_records import meta, payload_text
from lawgraph.core.succession import (
    LawArticle,
    Placed,
    SourceRow,
    division_label,
    place,
)
from lawgraph.core.transposition_tables import pdf_pages, read_table, source_rows
from lawgraph.core.transposition_xml import XmlTable
from lawgraph.core.transposition_xml import read_tables as read_xml_tables
from lawgraph.db.counting import Store
from lawgraph.db.queries import instrument_names as instrument_name_queries
from lawgraph.db.queries import successions as queries
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.pipelines.semantic._detection import build_extractor


@dataclass(frozen=True)
class Table:
    """One table of a source: its laws and rows, or why it places nothing."""

    identifier: str  # the source: blg-1081574, kst-34986-3, 32017R1001
    dossier: str  # empty for an EU act
    name: str = ""  # the table in its source: "h. Transponeringstabel Waterwet"
    problem: str | None = None
    old_law: str | None = None  # instruments/bwbr0001903
    new_law: str | None = None  # instruments/wet_stb_2026_56
    rows: tuple[SourceRow, ...] = ()
    repeals_old: bool = False  # the source repeals the old law (an EU act)

    @property
    def title(self) -> str:
        return f"{self.identifier} {self.name}".strip()

    @property
    def heading(self) -> str:
        """The title with the dossier, when there is one."""
        return f"{self.title} (dossier {self.dossier})" if self.dossier else self.title


@dataclass(frozen=True)
class Succession:
    """An old law and a new one, with what the tables between them place."""

    old_law: str
    new_law: str
    tables: tuple[Table, ...]
    placed: Placed
    replaced: bool  # the old law goes: an article of it without a row is a gap


def read_successions(store: Store) -> tuple[list[Table], list[Succession]]:
    """The tables that place nothing, and per pair of laws what the others place."""
    problems: list[Table] = []
    by_laws: dict[tuple[str, str], list[Table]] = {}
    other_laws = _OtherLaws(store)
    for table in _tables(store, other_laws):
        if table.old_law and table.new_law:
            by_laws.setdefault((table.old_law, table.new_law), []).append(table)
        else:
            problems.append(table)
    successions = []
    for (old, new), own in by_laws.items():
        laws = {str(law["id"]): law for law in queries.law_titles(store, [old, new])}
        rows = [row for table in own for row in table.rows]
        articles = _articles(store, new)
        replaced = any(t.repeals_old for t in own) or _replaced(laws, old, new)
        old_articles = _articles(store, old, historical=True)
        placed = place(
            rows,
            old_articles,
            articles,
            replaced=replaced,
            laws=other_laws.named(
                rows, {old: old_articles, new: articles}, laws.get(new) or {}
            ),
        )
        successions.append(Succession(old, new, tuple(own), placed, replaced))
    return problems, _rows_of_other_new_laws(successions)


def _replaced(laws: dict[str, dict[str, Any]], old: str, new: str) -> bool:
    """Whether the old law goes, as the sources say: the BWB has it expired no later than
    the new law came into force, or the new law bears its name (the whole law recodified,
    the new Wetboek van Strafvordering). *laws*: ``successions.law_titles`` by id."""
    old_law, new_law = laws.get(old) or {}, laws.get(new) or {}
    expired, in_force = old_law.get("date_expired"), new_law.get("date_in_force")
    if expired and in_force and str(expired) <= str(in_force):
        return True
    title = str(old_law.get("citation_title") or "")
    return bool(title) and _same(new_law.get("citation_title"), title)


def _rows_of_other_new_laws(successions: list[Succession]) -> list[Succession]:
    """*successions* without the gap "no row" of an old article a table of the same old law
    to another new law has a row for; of an old law with tables to more new laws, such a gap
    of an article no table names is one, of the pair that places the most articles."""
    named: dict[str, set[str]] = {}
    first: dict[str, Succession] = {}
    for succession in successions:
        named.setdefault(succession.old_law, set()).update(succession.placed.named)
        own = first.get(succession.old_law)
        if own is None or len(succession.placed.pairs) > len(own.placed.pairs):
            first[succession.old_law] = succession
    for succession in successions:
        succession.placed.gaps = [
            gap
            for gap in succession.placed.gaps
            if gap.kind != "no_row"
            or (
                gap.old_article not in named[succession.old_law]
                and first[succession.old_law] is succession
            )
        ]
    return successions


class _OtherLaws:
    """The laws a place names by name ("Awb", "Omgevingswet"), with their articles."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._ids: dict[str, list[str]] = {}
        self._articles: dict[str, dict[str, LawArticle]] = {}
        self._extractor: DutchCitationExtractor | None = None
        self._codes: tuple[dict[str, str], dict[str, dict[str, str]]] | None = None

    def named(
        self,
        rows: list[SourceRow],
        own: dict[str, dict[str, LawArticle]],
        new: dict[str, Any],
    ) -> dict[str, dict[str, LawArticle] | None]:
        """The articles of the law of each name a place of *rows* gives, None for a law not
        found; of the old and the new law the articles *own* gives (by law id), the *new*
        law also by its citation title."""
        found: dict[str, dict[str, LawArticle] | None] = {}
        for name in dict.fromkeys(r.place.law for r in rows if r.place.law):
            law = (
                str(new["id"])
                if _same(new.get("citation_title"), name)
                else self.law(name)
            )
            if law in own:
                found[name] = own[law]
            elif law is not None:
                if law not in self._articles:
                    self._articles[law] = _articles(self.store, law)
                found[name] = self._articles[law]
            else:
                found[name] = None
        return found

    def law(self, name: str) -> str | None:
        """The one law of *name* (``laws``), None for none or more."""
        found = self.laws(name)
        return found[0] if len(found) == 1 else None

    def laws(self, name: str) -> list[str]:
        """The laws of the BWB of the citation title *name*, unless there is not one: those
        of that abbreviation of the WTI ("WVO BES", "Bal"), else the one the citation
        extractor reads in "artikel 1 <name>" ("Awb"), of the whole name, not of a part of
        it ("WVO" of "WVO-BES", "Waterleidingwet" of "Waterleidingwet of
        Waterleidingbesluit")."""
        if name not in self._ids:
            named = queries.bwb_laws_named(self.store, name)
            if len(named) != 1 and (bwb_ids := self.abbreviated(name)):
                named = list(
                    queries.laws_of_bwb_ids(self.store, sorted(bwb_ids)).values()
                )
            if not named:
                text = f"artikel 1 {name.strip()}"
                bwb_ids = {
                    hit.bwb_id
                    for hit in self.extractor().extract(text)
                    if hit.bwb_id and hit.end == len(text)
                }
                named = list(
                    queries.laws_of_bwb_ids(self.store, sorted(bwb_ids)).values()
                )
            self._ids[name] = named
        return self._ids[name]

    def abbreviated(self, name: str) -> set[str]:
        """The BWB ids of the laws of the abbreviation *name* (``code_choices``: the short
        titles and abbreviations of the WTI, and the curated ones; also one several laws
        have), compared as ``successions.folded``."""
        codes, shared = self.codes()
        key = queries.folded(name)
        found = {law for code, law in codes.items() if queries.folded(code) == key}
        for code, laws in shared.items():
            if queries.folded(code) == key:
                found.update(laws)
        return found

    def codes(self) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
        """The abbreviations of the laws of the graph (``code_choices``)."""
        if self._codes is None:
            self._codes = code_choices(
                instrument_name_queries.code_alias_rows(self.store),
                curated_abbreviations(),
            )
        return self._codes

    def extractor(self) -> DutchCitationExtractor:
        """The citation extractor of running text, with the abbreviations and names of the
        laws of the graph."""
        if self._extractor is None:
            self._extractor = build_extractor(
                self.codes()[0],
                instrument_names(semantic_bwb.instrument_alias_rows(self.store)),
            )
        return self._extractor


def _tables(store: Store, laws: _OtherLaws) -> Iterator[Table]:
    """Every stored table: of each PDF, and of each Kamerstuk stored with its XML."""
    for record in queries.transposition_tables(store):
        if record.get("kind") != RAW_KIND_TK_TRANSPOSITION_DOCUMENT:
            yield _pdf_table(store, record)
        elif payload_text(record):
            yield from _xml_tables(store, record, laws)
    for record in queries.eu_acts_with_concordance(store):
        yield from _eu_tables(store, record)


def _eu_tables(store: Store, record: dict[str, Any]) -> Iterator[Table]:
    """The concordance tables of the EU act of *record*, a table per old act."""
    celex = str(record.get("external_id") or "")
    if not (html := payload_text(record)):
        return
    tables = read_concordance(html, celex)
    acts = queries.eu_acts(store, [celex, *(t.old_act for t in tables if t.old_act)])
    for table in tables:
        found = Table(celex, "", table.name, table.problem)
        if table.problem or table.old_act is None:
            yield found
        elif celex not in acts:
            yield replace(found, problem=f"the act {celex} is not in the graph")
        elif table.old_act not in acts:
            yield replace(
                found,
                problem=f"the act {table.old_act} is not in the graph "
                f"(retrieve eurlex --celex {table.old_act})",
            )
        else:
            yield replace(
                found,
                old_law=acts[table.old_act],
                new_law=acts[celex],
                rows=table.rows,
                repeals_old=table.repealed,
            )


def _pdf_table(store: Store, record: dict[str, Any]) -> Table:
    identifier = str(record.get("external_id") or "")
    found = Table(identifier, str(meta(record).get("dossier") or ""))
    try:
        pages = pdf_pages(base64.b64decode(payload_text(record) or "", validate=True))
    except PyPdfError, binascii.Error, ValueError:
        return replace(found, problem="the PDF does not read")
    table = read_table(pages)
    if table is None:
        return replace(found, problem="no page headed 'Huidig <law> Nieuw <law>'")
    rows = tuple(source_rows(table, identifier))
    return _with_laws(store, replace(found, rows=rows), table.old_law, table.new_law)


def _xml_tables(
    store: Store, record: dict[str, Any], laws: _OtherLaws | None = None
) -> Iterator[Table]:
    laws = laws or _OtherLaws(store)
    identifier = str(record.get("external_id") or "")
    match = KST_ID_PATTERN.fullmatch(identifier)
    dossier = str(meta(record).get("dossier") or (match.group(1) if match else ""))
    if not (xml := payload_text(record)):
        return
    try:
        tables = read_xml_tables(xml, identifier)
    except ET.ParseError:
        yield Table(identifier, dossier, problem="the XML does not read")
        return
    for table in tables:
        found = Table(identifier, dossier, table.name, table.problem)
        if table.problem:
            yield found
        elif table.proposed is not None:
            yield _with_proposal(store, found, table, laws)
        elif table.columns is None:
            yield _with_laws(store, replace(found, rows=table.rows()), None, None)
        else:
            yield _with_columns(store, found, table, laws)


def _dossier_laws(store: Store, dossier: str) -> list[dict[str, Any]]:
    """``{id, citation_title}`` of the laws a publication of *dossier* enacted or put
    articles in."""
    if not dossier:
        return []
    return queries.laws_of_dossier(
        store, node_id(COLLECTION_DOSSIERS, make_node_key(dossier))
    )


def _with_laws(
    store: Store, table: Table, old_name: str | None, new_name: str | None
) -> Table:
    """*table* with the laws of these names (``None``: as the module docstring says), or
    with the reason they are not found."""
    laws = _dossier_laws(store, table.dossier)
    if new_name is None:
        new = laws
        named = f"of dossier {table.dossier or '?'}"
    else:
        new = [law for law in laws if _same(law.get("citation_title"), new_name)] or [
            {"id": law_id, "citation_title": new_name}
            for law_id in queries.bwb_laws_named(store, new_name)
        ]
        named = f"named {new_name!r}"
    if len(new) != 1:
        return replace(table, problem=f"{len(new)} laws {named}", rows=())
    new_id = str(new[0]["id"])
    old_name = old_name or str(new[0].get("citation_title") or "")
    old = [law for law in queries.bwb_laws_named(store, old_name) if law != new_id]
    if len(old) != 1:
        return replace(
            table,
            problem=f"{len(old)} laws of the BWB named {old_name!r}",
            rows=(),
        )
    return replace(table, old_law=old[0], new_law=new_id)


def _with_proposal(
    store: Store, table: Table, xml: XmlTable, laws: _OtherLaws
) -> Table:
    """*table* with the law the paper proposes and the old law of *xml*, its rows read from
    the old law's column to the proposed law's, or with the reason they are not found. The
    old law of a name: of that citation title, else of that abbreviation (``_OtherLaws``)."""
    assert xml.columns is not None and xml.proposed is not None
    new = _proposed_law(store, _dossier_laws(store, table.dossier), xml.proposed)
    if new is None:
        named = " or ".join(repr(name) for name in xml.proposed) or "none"
        return replace(
            table, problem=f"no one law of dossier {table.dossier} named {named}"
        )
    names = tuple(dict.fromkeys(n for n in (xml.columns[0], xml.title_law) if n))
    for name in names:
        old = [law for law in queries.bwb_laws_named(store, name) if law != new]
        if len(old) != 1:
            old = [law for law in laws.laws(name) if law != new]
        if len(old) > 1:
            old = _in_force_when(store, old, new)
        if len(old) == 1:
            return replace(table, old_law=old[0], new_law=new, rows=xml.rows())
    named = " or ".join(repr(name) for name in names)
    return replace(table, problem=f"no one law of the BWB named {named}")


def _in_force_when(store: Store, laws: list[str], new: str) -> list[str]:
    """Of *laws* of one name, those that had not expired when the *new* law came into force
    (the Wet voortgezet onderwijs BES of 2011, not the one of its first months); all of them
    when the BWB has no such date of the new law."""
    titles = {str(law["id"]): law for law in queries.law_titles(store, [*laws, new])}
    in_force = (titles.get(new) or {}).get("date_in_force")
    if not in_force:
        return laws
    return [
        law
        for law in laws
        if not (expired := (titles.get(law) or {}).get("date_expired"))
        or str(expired) >= str(in_force)
    ]


def _proposed_law(
    store: Store, dossier: list[dict[str, Any]], names: tuple[str, ...]
) -> str | None:
    """The law of the dossier of one of *names*, else the one law of the *dossier*, else the
    one law of the BWB of one of *names*."""
    for name in names:
        own = [
            str(law["id"]) for law in dossier if _same(law.get("citation_title"), name)
        ]
        if len(own) == 1:
            return own[0]
    if len(dossier) == 1:
        return str(dossier[0]["id"])
    for name in names:
        found = queries.bwb_laws_named(store, name)
        if len(found) == 1:
            return found[0]
    return None


def _with_columns(store: Store, table: Table, xml: XmlTable, laws: _OtherLaws) -> Table:
    """*table* with the laws of the two columns of *xml*, its rows read from the old law's
    column to the new law's (``new_column``), or with the reason they are not found."""
    assert xml.columns is not None
    dossier = _dossier_laws(store, table.dossier)
    found = [_named_law(dossier, name, laws) for name in xml.columns]
    titled = _named_law(dossier, xml.title_law, laws) if xml.title_law else None
    if titled is not None:
        # the column the title names by an abbreviation ("Artikel Wabo")
        found = [
            titled if law is None and other not in (None, titled) else law
            for law, other in zip(found, reversed(found), strict=True)
        ]
    first, second = found
    if first is None or second is None or first == second:
        return replace(table, problem=f"no two laws named {xml.columns!r}")
    new = new_column((first, second), {str(law["id"]) for law in dossier}, titled)
    if new is None:
        return replace(
            table, problem=f"which of {xml.columns!r} is the new law is not known"
        )
    return replace(
        table,
        old_law=(first, second)[1 - new],
        new_law=(first, second)[new],
        rows=xml.rows(reverse=new == 0),
    )


def new_column(
    laws: tuple[str, str], dossier: set[str], titled: str | None
) -> int | None:
    """Which of the *laws* of the two columns is the new law: the one law of them a
    publication of the table's dossier enacted or put articles in (*dossier*), else the one
    the title does not name (a table is named after the law it transposes, *titled*); None
    when neither tells."""
    enacted = [index for index, law in enumerate(laws) if law in dossier]
    if len(enacted) == 1:
        return enacted[0]
    if titled in laws:
        return 1 - laws.index(titled)
    return None


def _named_law(
    dossier: list[dict[str, Any]], name: str, laws: _OtherLaws
) -> str | None:
    """The one law of *name*: of the laws of the dossier, else of the BWB by its citation
    title or abbreviation (``_OtherLaws.law``)."""
    own = [str(law["id"]) for law in dossier if _same(law.get("citation_title"), name)]
    return own[0] if len(own) == 1 else laws.law(name)


def _same(title: Any, name: str) -> bool:
    """Whether the citation title *title* is *name*, as ``successions.bwb_laws_named``
    compares them: in any case, without spaces, hyphens and other marks, a year still open
    for any."""
    return bool(
        re.fullmatch(queries.name_pattern(name), queries.folded(str(title or "")))
    )


def _articles(
    store: Store, law_id: str, *, historical: bool = False
) -> dict[str, LawArticle]:
    """The articles of the law by number, in its order, each with the divisions it stands
    in: those of its current text, and with *historical* (the old law) its historical
    identities between them (``in_law_order``); of a number both have, the current
    article."""
    articles: dict[str, LawArticle] = {}
    rows = queries.law_articles(store, law_id, historical=historical)
    for row in in_law_order(rows):
        articles.setdefault(
            row["number"],
            LawArticle(
                row["id"],
                row["number"],
                frozenset(row["leden"] or ()),
                bool(row["repealed"]),
                tuple(
                    label
                    for label in map(division_label, row.get("divisions") or ())
                    if label
                ),
            ),
        )
    return articles


def in_law_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The articles of a law (``successions.law_articles``) in its order: a historical
    identity, which has no place in the current text, before the first current article whose
    number comes after its own (``article_order``); after them all when none does."""
    current = [row for row in rows if not row["historical"]]
    earlier = sorted(
        (row for row in rows if row["historical"]),
        key=lambda row: article_order(row["number"]),
    )
    ordered: list[dict[str, Any]] = []
    for row in current:
        while earlier and article_order(earlier[0]["number"]) < article_order(
            row["number"]
        ):
            ordered.append(earlier.pop(0))
        ordered.append(row)
    return ordered + earlier
